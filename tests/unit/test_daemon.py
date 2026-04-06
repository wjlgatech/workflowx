"""Unit tests for WorkflowX daemon scheduling and trigger logic.

All tests are pure-unit: no asyncio, no I/O beyond tmp_path, no LLM calls.
Every function under test is a plain Python function isolated from side effects.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from workflowx.daemon import (
    ANALYZE_TIMES,
    BRIEF_TIMES,
    CAPTURE_TIMES,
    MEASURE_TIMES,
    DaemonState,
    JobState,
    format_morning_brief,
    generate_plist,
    is_daemon_running,
    next_fire_time,
    read_pid,
    read_state,
    seconds_until,
    should_measure,
    should_propose,
    write_pid,
    write_state,
)
from workflowx.models import FrictionLevel, ReplacementOutcome, WorkflowSession

# ── Fixtures & helpers ────────────────────────────────────────────────────────

# 2026-02-25 is Wednesday  (weekday 2)
# 2026-02-26 is Thursday   (weekday 3)
# 2026-02-27 is Friday     (weekday 4)
# 2026-02-28 is Saturday   (weekday 5)
# 2026-03-01 is Sunday     (weekday 6)
# 2026-03-02 is Monday     (weekday 0)

WED_NOON       = datetime(2026, 2, 25, 12,  0, 0)
WED_1330       = datetime(2026, 2, 25, 13, 30, 0)
WED_1900       = datetime(2026, 2, 25, 19,  0, 0)
FRI_1830       = datetime(2026, 2, 27, 18, 30, 0)   # past all slots for Friday
FRI_1700       = datetime(2026, 2, 27, 17,  0, 0)   # between analyze slots


def _session(
    friction: FrictionLevel = FrictionLevel.LOW,
    intent:   str = "coding session",
    sid:      str = "abc123",
    start:    datetime | None = None,
) -> WorkflowSession:
    t = start or datetime(2026, 2, 26, 9, 0, 0)
    return WorkflowSession(
        id=sid,
        start_time=t,
        end_time=t + timedelta(hours=1),
        friction_level=friction,
        inferred_intent=intent,
    )


def _outcome(
    adopted_date:  datetime | None = None,
    weeks_tracked: int = 0,
    status:        str = "measuring",
) -> ReplacementOutcome:
    return ReplacementOutcome(
        id="out_test",
        proposal_id="prop_test",
        intent="competitive research",
        adopted=True,
        adopted_date=adopted_date or datetime.now() - timedelta(days=10),
        before_minutes_per_week=50.0,
        weeks_tracked=weeks_tracked,
        status=status,
    )


# ── next_fire_time ────────────────────────────────────────────────────────────

class TestNextFireTime:
    def test_returns_next_slot_today_when_available(self):
        """Returns a later slot today if it hasn't fired yet."""
        result = next_fire_time([time(13, 0), time(18, 0)], weekdays_only=True, now=WED_NOON)
        assert result == datetime(2026, 2, 25, 13, 0, 0)

    def test_returns_second_slot_when_first_passed(self):
        """Returns the second slot when the first has already passed."""
        result = next_fire_time([time(13, 0), time(18, 0)], weekdays_only=True, now=WED_1330)
        assert result == datetime(2026, 2, 25, 18, 0, 0)

    def test_advances_to_next_weekday_when_all_slots_passed(self):
        """Advances to the next weekday when all of today's slots have passed."""
        result = next_fire_time([time(13, 0), time(18, 0)], weekdays_only=True, now=WED_1900)
        assert result == datetime(2026, 2, 26, 13, 0, 0)   # Thursday

    def test_skips_saturday_and_sunday_weekdays_only(self):
        """Skips Sat/Sun when weekdays_only=True — jumps to Monday."""
        result = next_fire_time([time(13, 0), time(18, 0)], weekdays_only=True, now=FRI_1830)
        assert result.weekday() == 0                         # Monday
        assert result == datetime(2026, 3, 2, 13, 0, 0)

    def test_includes_weekend_when_not_weekdays_only(self):
        """Includes Saturday when weekdays_only=False."""
        result = next_fire_time([time(7, 0)], weekdays_only=False, now=FRI_1830)
        assert result == datetime(2026, 2, 28, 7, 0, 0)     # Saturday

    def test_exact_now_does_not_fire_advances_to_next(self):
        """Does not fire when now == target; advances to the next occurrence."""
        exactly_1300 = datetime(2026, 2, 25, 13, 0, 0)
        result = next_fire_time([time(13, 0)], weekdays_only=True, now=exactly_1300)
        assert result > exactly_1300

    def test_single_slot_per_day(self):
        """Works correctly with a single daily slot."""
        now    = datetime(2026, 2, 25, 8, 0, 0)
        result = next_fire_time([time(8, 30)], weekdays_only=True, now=now)
        assert result == datetime(2026, 2, 25, 8, 30, 0)

    def test_between_friday_slots_returns_second_slot_same_day(self):
        """When between two Friday slots, returns the second slot on the same day."""
        result = next_fire_time([time(13, 0), time(18, 0)], weekdays_only=True, now=FRI_1700)
        assert result == datetime(2026, 2, 27, 18, 0, 0)

    def test_default_schedule_constants_are_sorted(self):
        """All schedule constant lists are properly ordered."""
        for times in (CAPTURE_TIMES, ANALYZE_TIMES, MEASURE_TIMES, BRIEF_TIMES):
            assert times == sorted(times), f"{times} is not sorted"

    def test_raises_if_no_time_found(self):
        """Raises RuntimeError if no time is findable (degenerate config)."""
        with pytest.raises(RuntimeError):
            # Empty list — no times ever fire
            next_fire_time([], weekdays_only=True, now=WED_NOON)


# ── seconds_until ─────────────────────────────────────────────────────────────

class TestSecondsUntil:
    def test_positive_future(self):
        now    = datetime(2026, 2, 25, 12, 0, 0)
        target = datetime(2026, 2, 25, 12, 5, 0)
        assert seconds_until(target, now=now) == 300.0

    def test_past_returns_zero(self):
        now    = datetime(2026, 2, 25, 12, 0, 0)
        target = datetime(2026, 2, 25, 11, 0, 0)
        assert seconds_until(target, now=now) == 0.0

    def test_exact_same_returns_zero(self):
        now = datetime(2026, 2, 25, 12, 0, 0)
        assert seconds_until(now, now=now) == 0.0

    def test_one_hour(self):
        now    = datetime(2026, 2, 25, 12, 0, 0)
        target = datetime(2026, 2, 25, 13, 0, 0)
        assert seconds_until(target, now=now) == 3600.0


# ── should_measure ────────────────────────────────────────────────────────────

class TestShouldMeasure:
    def test_too_early_under_7_days(self):
        """Returns False when outcome is < 7 days old — no signal yet."""
        o = _outcome(adopted_date=datetime.now() - timedelta(days=3))
        assert should_measure(o) is False

    def test_exactly_7_days_never_measured(self):
        """Returns True at exactly 7 days if never measured."""
        o = _outcome(adopted_date=datetime.now() - timedelta(days=7), weeks_tracked=0)
        assert should_measure(o) is True

    def test_7_days_already_measured_once(self):
        """Returns False at 7 days if already measured once this cycle."""
        o = _outcome(adopted_date=datetime.now() - timedelta(days=7), weeks_tracked=1)
        assert should_measure(o) is False

    def test_14_days_measured_once_due_again(self):
        """Returns True at 14 days if only measured once (due twice)."""
        o = _outcome(adopted_date=datetime.now() - timedelta(days=14), weeks_tracked=1)
        assert should_measure(o) is True

    def test_14_days_measured_twice_not_due(self):
        """Returns False at 14 days if already measured twice."""
        o = _outcome(adopted_date=datetime.now() - timedelta(days=14), weeks_tracked=2)
        assert should_measure(o) is False

    def test_30_days_weekly_cadence_full(self):
        """At 30 days with 4 measurements, the weekly phase is complete."""
        o = _outcome(adopted_date=datetime.now() - timedelta(days=30), weeks_tracked=4)
        assert should_measure(o) is False   # 30//7 == 4, weeks_tracked == 4 → not due

    def test_monthly_cadence_after_30_days_due(self):
        """At 60 days with 4 measurements, monthly phase requires one more."""
        o = _outcome(adopted_date=datetime.now() - timedelta(days=60), weeks_tracked=4)
        assert should_measure(o) is True    # expected = 4 + (60-30)//30 = 5

    def test_monthly_cadence_already_done(self):
        """At 60 days with 5 measurements, not due until next month."""
        o = _outcome(adopted_date=datetime.now() - timedelta(days=60), weeks_tracked=5)
        assert should_measure(o) is False

    def test_no_adopted_date_returns_false(self):
        """Gracefully returns False when adopted_date is None."""
        o = _outcome()
        o.adopted_date = None
        assert should_measure(o) is False

    def test_monotonically_increasing_as_weeks_pass(self):
        """Measurement demand increases predictably over 12 weeks."""
        base = datetime.now()
        last_expected = 0
        for age_days in range(7, 84, 7):
            o = _outcome(
                adopted_date=base - timedelta(days=age_days),
                weeks_tracked=0,
            )
            # At any point with weeks_tracked=0, should_measure must be True
            assert should_measure(o) is True, f"Expected True at {age_days} days"

            # Check expected count is non-decreasing
            if age_days <= 30:
                expected = age_days // 7
            else:
                expected = 4 + (age_days - 30) // 30
            assert expected >= last_expected
            last_expected = expected


# ── should_propose ────────────────────────────────────────────────────────────

class TestShouldPropose:
    def test_low_friction_returns_false(self):
        s = _session(friction=FrictionLevel.LOW, intent="writing code")
        assert should_propose(s, {}) is False

    def test_medium_friction_returns_false(self):
        s = _session(friction=FrictionLevel.MEDIUM, intent="reviewing PRs")
        assert should_propose(s, {}) is False

    def test_high_friction_new_session(self):
        s = _session(friction=FrictionLevel.HIGH, intent="competitive research")
        assert should_propose(s, {}) is True

    def test_critical_friction_new_session(self):
        s = _session(friction=FrictionLevel.CRITICAL, intent="multitasking during sync")
        assert should_propose(s, {}) is True

    def test_already_proposed_same_session_id(self):
        """Returns False when this exact session ID was already proposed."""
        s = _session(friction=FrictionLevel.CRITICAL, sid="sess001")
        proposed = {"sess001": datetime.now().isoformat()}
        assert should_propose(s, proposed) is False

    def test_different_session_id_not_blocked(self):
        """Dedup is per session ID — a different ID is allowed."""
        s = _session(friction=FrictionLevel.CRITICAL, sid="sess002")
        proposed = {"sess001": datetime.now().isoformat()}
        assert should_propose(s, proposed) is True

    def test_no_intent_returns_false(self):
        """Returns False when analysis hasn't run yet (no inferred_intent)."""
        s = _session(friction=FrictionLevel.CRITICAL, intent="")
        assert should_propose(s, {}) is False

    def test_multiple_sessions_only_eligible_flagged(self):
        """Mixed friction list: only HIGH/CRITICAL with no history are returned."""
        sessions = [
            _session(FrictionLevel.LOW,      "low",      "s1"),
            _session(FrictionLevel.HIGH,     "high1",    "s2"),
            _session(FrictionLevel.CRITICAL, "crit",     "s3"),
            _session(FrictionLevel.HIGH,     "high2",    "s4"),
            _session(FrictionLevel.CRITICAL, "old crit", "s5"),
        ]
        proposed = {"s5": datetime.now().isoformat()}   # s5 already handled
        result = [s for s in sessions if should_propose(s, proposed)]
        assert {s.id for s in result} == {"s2", "s3", "s4"}


# ── format_morning_brief ──────────────────────────────────────────────────────

class TestFormatMorningBrief:
    _now = datetime(2026, 2, 26, 8, 30, 0)       # Thursday 08:30
    _yesterday = datetime(2026, 2, 25, 10, 0, 0)  # Wednesday — yesterday

    def test_no_sessions_returns_guidance(self):
        title, msg = format_morning_brief([], [], 0, now=self._now)
        assert "workflowx capture" in msg.lower() or "no data" in msg.lower()

    def test_critical_appears_in_message(self):
        s = _session(FrictionLevel.CRITICAL, start=self._yesterday)
        title, msg = format_morning_brief([s], [], 0, now=self._now)
        assert "CRITICAL" in msg

    def test_high_appears_in_message(self):
        s = _session(FrictionLevel.HIGH, start=self._yesterday)
        title, msg = format_morning_brief([s], [], 0, now=self._now)
        assert "HIGH" in msg

    def test_pending_validations_count_appears(self):
        s = _session(start=self._yesterday)
        title, msg = format_morning_brief([s], [], 3, now=self._now)
        assert "3" in msg
        assert "validation" in msg.lower()

    def test_all_low_friction_shows_positive(self):
        s = _session(FrictionLevel.LOW, start=self._yesterday)
        title, msg = format_morning_brief([s], [], 0, now=self._now)
        assert "low friction" in msg.lower() or "✓" in msg

    def test_today_sessions_excluded(self):
        """Only yesterday's sessions count — today's work hasn't happened yet."""
        today_session = _session(
            FrictionLevel.CRITICAL,
            start=datetime(2026, 2, 26, 7, 0, 0),  # today
            sid="today",
        )
        title, msg = format_morning_brief([today_session], [], 0, now=self._now)
        assert "CRITICAL" not in msg

    def test_title_contains_session_count(self):
        sessions = [
            _session(start=self._yesterday, sid="s1"),
            _session(start=self._yesterday, sid="s2"),
        ]
        title, _ = format_morning_brief(sessions, [], 0, now=self._now)
        assert "2" in title

    def test_measuring_outcomes_appear(self):
        s = _session(start=self._yesterday)
        o = _outcome(status="measuring")
        title, msg = format_morning_brief([s], [o], 0, now=self._now)
        assert "measuring" in msg.lower() or "in progress" in msg.lower()

    def test_returns_tuple_of_strings(self):
        title, msg = format_morning_brief([], [], 0, now=self._now)
        assert isinstance(title, str)
        assert isinstance(msg, str)
        assert len(title) > 0
        assert len(msg) > 0


# ── PID management ────────────────────────────────────────────────────────────

class TestPidManagement:
    def test_write_and_read_pid(self, tmp_path):
        pid_file = tmp_path / "daemon.pid"
        write_pid(pid_file)
        assert read_pid(pid_file) == os.getpid()

    def test_read_missing_file_returns_none(self, tmp_path):
        assert read_pid(tmp_path / "nonexistent.pid") is None

    def test_read_corrupt_file_returns_none(self, tmp_path):
        f = tmp_path / "daemon.pid"
        f.write_text("not_a_number")
        assert read_pid(f) is None

    def test_read_empty_file_returns_none(self, tmp_path):
        f = tmp_path / "daemon.pid"
        f.write_text("")
        assert read_pid(f) is None

    def test_is_running_own_process(self, tmp_path):
        pid_file = tmp_path / "daemon.pid"
        write_pid(pid_file)
        assert is_daemon_running(pid_file) is True

    def test_is_running_nonexistent_pid(self, tmp_path):
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("999999999")   # Almost certainly not a real PID
        assert is_daemon_running(pid_file) is False

    def test_is_running_missing_file(self, tmp_path):
        assert is_daemon_running(tmp_path / "nonexistent.pid") is False


# ── DaemonState persistence ───────────────────────────────────────────────────

class TestDaemonState:
    def test_write_read_roundtrip(self, tmp_path):
        path  = tmp_path / "daemon_state.json"
        state = DaemonState()
        state.jobs["capture"] = JobState(last_status="ok")
        state.proposed_session_ids["s001"] = "2026-02-26T12:00:00"

        write_state(state, path)
        loaded = read_state(path)

        assert loaded.jobs["capture"].last_status == "ok"
        assert loaded.proposed_session_ids["s001"] == "2026-02-26T12:00:00"

    def test_missing_file_returns_fresh_state(self, tmp_path):
        state = read_state(tmp_path / "nonexistent.json")
        assert isinstance(state, DaemonState)
        assert state.jobs == {}
        assert state.proposed_session_ids == {}
        assert state.screenpipe_healthy is True

    def test_corrupt_file_returns_fresh_state(self, tmp_path):
        path = tmp_path / "daemon_state.json"
        path.write_text("{{{{ not valid json ####")
        state = read_state(path)
        assert isinstance(state, DaemonState)

    def test_partial_state_preserved(self, tmp_path):
        """Each loop updates its own job key without clobbering others."""
        path  = tmp_path / "daemon_state.json"
        state = DaemonState()
        state.jobs["capture"] = JobState(last_status="ok")
        write_state(state, path)

        # Simulate analyze loop reading and writing
        state2 = read_state(path)
        state2.jobs["analyze"] = JobState(last_status="ok")
        write_state(state2, path)

        final = read_state(path)
        assert final.jobs["capture"].last_status == "ok"
        assert final.jobs["analyze"].last_status == "ok"

    def test_proposed_ids_persist_across_reads(self, tmp_path):
        path  = tmp_path / "daemon_state.json"
        state = DaemonState()
        state.proposed_session_ids["abc"] = "2026-02-26T10:00:00"
        write_state(state, path)

        loaded = read_state(path)
        assert "abc" in loaded.proposed_session_ids

    def test_started_at_is_set(self):
        state = DaemonState()
        assert isinstance(state.started_at, datetime)


# ── Plist generation ──────────────────────────────────────────────────────────

class TestPlistGeneration:
    def test_plist_contains_label(self, tmp_path):
        xml = generate_plist(tmp_path / "daemon.log")
        assert "com.workflowx.daemon" in xml

    def test_plist_contains_daemon_run_args(self, tmp_path):
        xml = generate_plist(tmp_path / "daemon.log")
        assert "<string>daemon</string>" in xml
        assert "<string>run</string>"    in xml

    def test_plist_contains_keep_alive(self, tmp_path):
        xml = generate_plist(tmp_path / "daemon.log")
        assert "<key>KeepAlive</key>" in xml
        assert "<true/>"              in xml

    def test_plist_contains_log_path(self, tmp_path):
        log = tmp_path / "daemon.log"
        xml = generate_plist(log)
        assert str(log) in xml

    def test_plist_is_valid_xml(self, tmp_path):
        import xml.etree.ElementTree as ET
        xml = generate_plist(tmp_path / "daemon.log")
        # Should parse without raising
        ET.fromstring(xml)

    def test_plist_captures_anthropic_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-abc")
        xml = generate_plist(tmp_path / "daemon.log")
        assert "ANTHROPIC_API_KEY" in xml
        assert "sk-test-abc"       in xml

    def test_plist_omits_missing_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        xml = generate_plist(tmp_path / "daemon.log")
        assert "OPENAI_API_KEY" not in xml
