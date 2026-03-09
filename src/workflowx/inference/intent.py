"""Intent inference engine — uses LLM to understand what the user was trying to do.

This is the core differentiator. Raw events are meaningless.
Inferred intent + user validation = gold.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from workflowx.models import (
    ClassificationQuestion,
    WorkflowDiagnosis,
    WorkflowSession,
)

logger = structlog.get_logger()

INTENT_SYSTEM_PROMPT = """You are a workflow analyst. Given a sequence of application
events (app names, window titles, URLs, OCR text), infer:

1. **Intent**: What was the user trying to accomplish? Be specific and action-oriented.
2. **Friction points**: Where did they get stuck, loop, or waste time?
3. **Confidence**: How confident are you in this inference? (0.0 to 1.0)
4. **Classification question**: If confidence < 0.7, generate ONE short multiple-choice
   question to ask the user for validation. 3-4 options max.

Respond in JSON:
{
  "intent": "string",
  "friction_points": ["string"],
  "confidence": 0.0,
  "question": {"text": "string", "options": ["a", "b", "c"]} | null
}"""


def build_session_summary(session: WorkflowSession) -> str:
    """Compress a session into a text summary for the LLM."""
    lines = [
        f"Session: {session.start_time.strftime('%H:%M')} - {session.end_time.strftime('%H:%M')}",
        f"Duration: {session.total_duration_minutes} min",
        f"Apps: {', '.join(session.apps_used)}",
        f"Context switches: {session.context_switches}",
        f"Friction: {session.friction_level.value}",
        "",
        "Event timeline:",
    ]

    # Sample events (don't send all to LLM — cost control)
    sample_size = min(20, len(session.events))
    step = max(1, len(session.events) // sample_size)

    for i in range(0, len(session.events), step):
        e = session.events[i]
        time_str = e.timestamp.strftime("%H:%M:%S")
        text_preview = e.ocr_text[:100] if e.ocr_text else ""
        lines.append(
            f"  [{time_str}] {e.app_name} | {e.window_title[:60]} | {text_preview}"
        )

    return "\n".join(lines)


_RETRY_NOTE = (
    "\n\nNOTE: Be concise — keep 'intent' under 40 words, 'friction_points' to 2 items max."
)


async def _call_llm(
    llm_client: Any,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    """Call the LLM and return raw text content."""
    if hasattr(llm_client, "messages"):
        response = await llm_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text
    else:
        response = await llm_client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content


def _strip_fences(content: str) -> str:
    """Strip markdown code fences if present (```json ... ```)."""
    s = content.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        s = s.rsplit("```", 1)[0].strip()
    return s


async def infer_intent(
    session: WorkflowSession,
    llm_client: Any,  # anthropic.AsyncAnthropic or openai.AsyncOpenAI
    model: str = "claude-sonnet-4-6",
) -> tuple[WorkflowSession, ClassificationQuestion | None]:
    """Infer the intent of a workflow session using an LLM.

    Retries once with a higher token budget and a conciseness hint if the
    first response is truncated (json.JSONDecodeError). Other errors (network,
    auth) do not benefit from retry and fail immediately.

    Returns the updated session and optionally a classification question.
    """
    summary = build_session_summary(session)

    last_error: Exception | None = None
    for attempt in range(2):
        # Give more budget on retry; ask for brevity to avoid another truncation.
        max_tokens = 1024 if attempt == 0 else 1200
        system = INTENT_SYSTEM_PROMPT if attempt == 0 else INTENT_SYSTEM_PROMPT + _RETRY_NOTE

        try:
            content = await _call_llm(llm_client, model, system, summary, max_tokens)
            result = json.loads(_strip_fences(content))

            session.inferred_intent = result.get("intent", "unknown")
            session.confidence = result.get("confidence", 0.0)
            session.friction_details = "; ".join(result.get("friction_points", []))

            question = None
            if result.get("question") and session.confidence < 0.7:
                # Don't prompt for short audio-only sessions — these are ambient mic
                # captures (background conversations, media playing nearby), not
                # actionable workflow data. Asking about them wastes validation budget.
                is_audio_only = all(
                    e.app_name in ("", "audio") for e in session.events
                )
                is_ambient = (
                    is_audio_only
                    and session.confidence < 0.5
                    and session.total_duration_minutes < 10
                )
                if not is_ambient:
                    q_data = result["question"]
                    question = ClassificationQuestion(
                        session_id=session.id,
                        question=q_data["text"],
                        options=q_data["options"],
                        context=f"Session at {session.start_time.strftime('%H:%M')}, "
                        f"{session.total_duration_minutes}min, "
                        f"apps: {', '.join(session.apps_used[:3])}",
                    )

            logger.info(
                "intent_inferred",
                session_id=session.id,
                intent=session.inferred_intent,
                confidence=session.confidence,
                has_question=question is not None,
            )
            return session, question

        except json.JSONDecodeError as e:
            last_error = e
            if attempt == 0:
                logger.warning(
                    "intent_json_truncated_retrying",
                    session_id=session.id,
                    error=str(e),
                )
                continue  # retry with larger budget
        except Exception as e:
            last_error = e
            break  # network/auth errors won't improve with retry

    logger.error("intent_inference_failed", session_id=session.id, error=str(last_error))
    session.inferred_intent = "inference_failed"
    session.confidence = 0.0
    return session, None


def diagnose_workflow(
    session: WorkflowSession,
    hourly_rate_usd: float = 75.0,
) -> WorkflowDiagnosis:
    """Diagnose a workflow session's efficiency.

    Uses the inferred intent + friction signals to estimate waste and automation potential.
    """
    cost = (session.total_duration_minutes / 60.0) * hourly_rate_usd

    # Heuristic: automation potential scales with friction and repetition
    automation_score = 0.0
    if session.friction_level.value == "critical":
        automation_score = 0.9
    elif session.friction_level.value == "high":
        automation_score = 0.7
    elif session.friction_level.value == "medium":
        automation_score = 0.4
    else:
        automation_score = 0.1

    return WorkflowDiagnosis(
        session_id=session.id,
        intent=session.inferred_intent,
        total_time_minutes=session.total_duration_minutes,
        friction_points=session.friction_details.split("; ") if session.friction_details else [],
        estimated_cost_usd=round(cost, 2),
        automation_potential=automation_score,
    )
