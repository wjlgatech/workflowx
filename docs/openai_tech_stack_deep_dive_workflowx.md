# WorkflowX: OpenAI Tech Stack Deep Dive
*Application-specific deep dive — Workflow Mining, Friction Detection & AI-Driven Replacement*
*Last updated: 2026-03-03*

---

## The TRUE² Framework (Navigation System)

Every improvement below is evaluated against 8 dimensions: **T**ransferable · **T**ransformable · **R**eplicable · **R**efineable · **U**nderstandable · **U**sable · **E**xperiencable · **E**xperimentable

---

# Chapter 1: EVALS
## "Did the Flywheel Actually Turn?"

### Level 1 — The WorkflowX Problem

You open WorkflowX after three weeks of use. The dashboard says you've saved 4.2 hours/week. But you didn't add a single verified "after" measurement. The "savings" number was extrapolated from the proposal engine's estimate — which was an LLM guess.

The claim "saves 4.2 hours/week" is not a measurement. It's a hallucination with a progress bar.

WorkflowX's entire value proposition is the flywheel: friction detected → replacement proposed → replacement adopted → time actually saved → new workflow detected. If you can't close the loop with real measurement, you have a journaling app with a nice dashboard, not a productivity platform.

The eval system is what turns the flywheel from a story into a number.

### Level 2 — Eval Architecture for WorkflowX

```
Ground truth: annotated_sessions.json
(20 sessions with verified intent labels + friction levels + known replacement outcomes)
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                    WorkflowX EvalRunner                      │
│   Mode: unit (intent grader only)                           │
│          integration (full pipeline: capture→infer→propose) │
│          e2e (full pipeline + ROI measurement loop)         │
└──────────────┬──────────────────────────────────────────────┘
               │
    ┌──────────┼──────────────┐
    ▼          ▼              ▼
IntentGrader  FrictionGrader  ROIGrader
Intent       Friction level   Actual savings
accuracy     accuracy         vs. estimated
(F1)         (Weighted-κ)    (MAPE)
    │          │              │
    └──────────┴──────────────┘
               │
               ▼
     EvalReport → CI gate
     (block PR if intent F1 < 0.80 or friction-κ < 0.65)
```

### Level 3 — Implementation for WorkflowX

**What you have:**
- `src/workflowx/inference/intent.py` — `infer_intent()` via LLM (Claude Sonnet 4.6). Returns `(WorkflowSession, ClassificationQuestion | None)`.
- `src/workflowx/inference/clusterer.py` — `cluster_into_sessions()`. 5-min gap heuristic. Denoised 30-second window.
- `src/workflowx/inference/patterns.py` — `detect_patterns()`. SequenceMatcher-based intent grouping.
- `src/workflowx/measurement.py` — `measure_outcome()`. Intent-matching to post-adoption sessions.
- `tests/` — 12 test files. No gold eval dataset yet.
- No `EvalRunner` specific to WorkflowX (all tests are unit tests).

**What's missing:**
- No annotated gold dataset (`annotated_sessions.json`) with verified intent labels and friction levels.
- No `IntentGrader` (measures LLM intent inference quality against human-labeled ground truth).
- No `FrictionGrader` (was HIGH friction correctly identified, or was a MEDIUM session promoted?).
- No `ROIGrader` (does the claimed savings match the re-measured actual savings 2 weeks post-adoption?).
- No CI gate on inference quality (a bad prompt change silently degrades intent accuracy).

### Level 4 — TRUE² Mapping for WorkflowX

| Layer | WorkflowX Application |
|-------|----------------------|
| Transferable | The annotated_sessions.json + IntentGrader pattern applies to any observability tool that uses LLM to classify user behavior — swap app events, keep the framework |
| Transformable | Add a ProposalQualityGrader that scores whether LLM-proposed replacements are technically feasible, not just plausible-sounding |
| Replicable | `make eval-intent` reproducible from any machine with ANTHROPIC_API_KEY set |
| Refineable | Add sessions to gold dataset as the LLM misclassifies real-world edge cases (e.g., context switches during meetings vs. genuine task switching) |
| Understandable | Intent F1=0.85 means "85% of the time, the system correctly understood what the user was trying to do." Friction-κ=0.70 means "substantial agreement between LLM and human on severity." |
| Usable | Wire to GitHub Actions: block PR if any grader drops below threshold |
| Experiencable | Run `pytest tests/test_intent.py -v` on a real Screenpipe session and watch intent inference live |
| Experimentable | Change the INTENT_SYSTEM_PROMPT. Re-run eval. Watch F1 move. That's the prompt tuning loop. |

### Detailed Improvement Instructions

**Improvement 1: Build the annotated gold dataset**

The eval system can't exist without ground truth. Build `eval/datasets/annotated_sessions.json` — 20 sessions manually labeled:

```json
[
  {
    "session_id": "sess_20260115_0903",
    "events": [...],
    "ground_truth": {
      "intent": "Summarize weekly Slack threads into a status update email",
      "friction_level": "HIGH",
      "friction_details": "12 context switches, repeated copy-paste loops between Slack and Gmail",
      "is_recurring": true,
      "human_validated": true
    }
  }
]
```

Annotation guide: Label 5 sessions per friction level (LOW/MEDIUM/HIGH/CRITICAL). Make sure all 4 FrictionLevel enum values are represented. Intent labels should be action-oriented ("verb + object" format).

**Improvement 2: Implement IntentGrader**

```python
# eval/graders/intent_grader.py
from sklearn.metrics import f1_score
from difflib import SequenceMatcher

class IntentGrader:
    """Evaluates LLM intent inference accuracy against annotated ground truth."""

    def __init__(self, similarity_threshold: float = 0.60):
        self.similarity_threshold = similarity_threshold

    def grade(
        self,
        predicted_sessions: list[WorkflowSession],
        gold_sessions: list[dict],
    ) -> dict:
        """
        Metric: Soft F1 using SequenceMatcher similarity.
        A prediction is a "true positive" if similarity ≥ threshold.
        """
        correct = 0
        for pred, gold in zip(predicted_sessions, gold_sessions):
            sim = SequenceMatcher(
                None,
                pred.inferred_intent.lower(),
                gold["ground_truth"]["intent"].lower(),
            ).ratio()
            if sim >= self.similarity_threshold:
                correct += 1

        accuracy = correct / len(gold_sessions)

        # Also grade friction level classification (exact match)
        friction_correct = sum(
            1 for p, g in zip(predicted_sessions, gold_sessions)
            if p.friction_level.value == g["ground_truth"]["friction_level"]
        )
        friction_accuracy = friction_correct / len(gold_sessions)

        return {
            "intent_accuracy": accuracy,
            "friction_accuracy": friction_accuracy,
            "n_sessions": len(gold_sessions),
        }
```

**Improvement 3: ROI grader — close the loop**

```python
# eval/graders/roi_grader.py

class ROIGrader:
    """
    Measures whether claimed savings (from ReplacementProposal.estimated_savings_minutes_per_week)
    match actual savings (from ReplacementOutcome.actual_savings_minutes).

    MAPE (Mean Absolute Percentage Error) is the primary metric.
    """

    def grade(self, outcomes: list[ReplacementOutcome]) -> dict:
        adopted = [o for o in outcomes if o.adopted and o.actual_savings_minutes > 0]
        if not adopted:
            return {"mape": None, "n_outcomes": 0}

        errors = []
        for o in adopted:
            estimated = o.proposal.estimated_savings_minutes_per_week * o.weeks_tracked
            actual = o.actual_savings_minutes
            if estimated > 0:
                errors.append(abs(estimated - actual) / estimated)

        mape = sum(errors) / len(errors) if errors else None
        return {
            "mape": mape,                          # Target: < 0.30 (within 30%)
            "n_outcomes": len(adopted),
            "avg_actual_savings_min": sum(o.actual_savings_minutes for o in adopted) / len(adopted),
        }
```

**CI threshold targets:**
- Intent accuracy ≥ 0.80
- Friction accuracy ≥ 0.70
- ROI MAPE ≤ 0.30 (proposals within 30% of actual savings)

---

# Chapter 2: GUARDRAILS
## "The Flywheel Must Not Lie"

### Level 1 — The WorkflowX Problem

The replacement engine generates proposals like: "Replace your Slack → Gmail workflow with a single Claude-powered agent that reads all threads and drafts the email automatically. Estimated savings: 2.1 hours/week."

This sounds great. But three things could make it a lie:
1. The proposed agent requires access to the Slack API — which you don't have.
2. "2.1 hours/week" was extrapolated from one session that was 127 minutes long. That session was an outlier.
3. The proposal says "automatically" but the Slack API rate limit means it would take 45 minutes to fetch all threads.

WorkflowX is a trust machine. Every proposal that turns out to be unfeasible breaks the flywheel. The guardrails protect the output quality — not the input quality.

### Level 2 — Guardrail Architecture for WorkflowX

```
ReplacementProposal (LLM output)
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                    ProposalGuardrail                          │
│                                                              │
│  1. MechanismValidator — does the mechanism describe         │
│     a real tool or approach? (reject "AI magic")            │
│                                                              │
│  2. SavingsEstimateValidator — is estimate within 3× of      │
│     observed session duration?                               │
│                                                              │
│  3. ToolAvailabilityChecker — are required tools in          │
│     user's installed app list?                               │
│                                                              │
│  4. FeasibilityConfidenceFloor — reject proposals with       │
│     confidence < 0.55                                        │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
                  PASS → user sees proposal
                  FAIL → proposal suppressed
                         OR downgraded to "speculative"
```

### Level 3 — Implementation for WorkflowX

**What you have:**
- `src/workflowx/replacement/engine.py` — `propose_replacement()`. LLM output as `ReplacementProposal`.
- `ReplacementProposal.confidence` — LLM self-reported confidence (0.0–1.0).
- `ReplacementProposal.requires_new_tools` — list of tools the replacement needs.
- `ReplacementProposal.mechanism` — free-text description of how the replacement works.
- No guardrail layer exists yet.

**What's missing:**
- No output validation on `mechanism` (LLM can say "leverage AI" without specifying what).
- No savings estimate bounding (outlier sessions inflate estimates by 5–10×).
- No check against user's installed tools (proposals requiring Zapier when user doesn't have it).
- No confidence floor enforcement (low-confidence proposals reach users).

### Level 4 — TRUE² Mapping for WorkflowX

| Layer | WorkflowX Application |
|-------|----------------------|
| Transferable | MechanismValidator logic (reject vague verbs: "leverage", "automate", "streamline") applies to any LLM proposal generator |
| Transformable | Add a PrivacyGuardrail that blocks proposals which require sending screen content to external APIs without consent |
| Replicable | All guardrails are stateless validators — wrap in pytest fixture for reproducible testing |
| Refineable | Add new vague-verb patterns as you discover LLM failure modes in production proposals |
| Understandable | "MechanismValidator blocked this proposal: 'leverage AI' does not describe a concrete tool or action" — actionable feedback |
| Usable | Guardrails run synchronously in `propose_replacement()` before returning to user |
| Experiencable | Run the replacement engine on a session that normally produces a vague proposal — watch guardrail intercept it |
| Experimentable | Lower the confidence floor from 0.55 to 0.45. Observe how many more proposals pass. Measure user adoption rate. |

### Detailed Improvement Instructions

**Improvement 1: MechanismValidator — reject hand-waving**

```python
# src/workflowx/guardrails/mechanism_validator.py

VAGUE_MECHANISM_PATTERNS = [
    "leverage ai", "use automation", "automate this",
    "streamline the process", "use llm to handle",
    "ai can", "simply use", "just create an agent",
]

class MechanismValidator:
    """
    A valid mechanism must describe:
    - A named tool (Claude, GPT-4, Python script, Zapier)
    - A named action (reads Slack API, calls Gmail API, runs Python)
    - A named output (draft email, structured JSON, Slack message)
    """

    def validate(self, proposal: ReplacementProposal) -> tuple[bool, str]:
        mechanism = proposal.mechanism.lower()

        for pattern in VAGUE_MECHANISM_PATTERNS:
            if pattern in mechanism:
                return False, f"Vague mechanism: '{pattern}' does not describe a concrete tool or action."

        # Must mention at least one named tool
        known_tools = ["claude", "gpt", "python", "zapier", "make.com", "slack api",
                       "gmail api", "notion api", "github api", "openai", "anthropic"]
        if not any(tool in mechanism for tool in known_tools):
            return False, "Mechanism must name at least one specific tool (e.g., Claude, Python, Slack API)."

        return True, "OK"
```

**Improvement 2: Savings estimate bounding**

```python
# src/workflowx/guardrails/savings_validator.py

class SavingsEstimateValidator:
    """
    Estimated savings must be within [0.5×, 3×] of observed session duration.
    Outlier sessions (>120 min) get capped at 120 min for estimate bounding.
    """

    def validate(
        self,
        proposal: ReplacementProposal,
        session: WorkflowSession,
    ) -> tuple[bool, str]:
        observed_min = min(session.total_duration_minutes, 120.0)  # Cap outliers

        # Convert weekly savings to per-session estimate
        estimated_per_session = proposal.estimated_time_after_minutes

        # The "after" time should be < observed time (that's the point)
        if estimated_per_session >= observed_min:
            return False, (
                f"Replacement (est. {estimated_per_session:.0f} min) "
                f"is not faster than original ({observed_min:.0f} min)."
            )

        # Savings should not exceed 3× observed duration
        estimated_savings = proposal.estimated_savings_minutes_per_week
        weekly_observed = observed_min * 4  # rough weekly estimate
        if estimated_savings > weekly_observed * 3:
            return False, (
                f"Estimated savings ({estimated_savings:.0f} min/week) "
                f"exceeds 3× observed duration ({weekly_observed:.0f} min/week). "
                f"Likely extrapolation error."
            )

        return True, "OK"
```

**Improvement 3: Wire guardrails into the proposal pipeline**

```python
# src/workflowx/replacement/engine.py  (modified)

async def propose_replacement(
    diagnosis: WorkflowDiagnosis,
    session: WorkflowSession,
    llm_client: Any,
    model: str = "claude-sonnet-4-6",
) -> ReplacementProposal | None:
    """
    Returns None if guardrails block the proposal.
    Returns proposal with confidence downgraded to 0.4 if "speculative".
    """
    proposal = await _call_llm_for_proposal(diagnosis, session, llm_client, model)

    # Guardrail 1: confidence floor
    if proposal.confidence < 0.55:
        logger.info(f"Proposal suppressed: confidence={proposal.confidence:.2f} < 0.55")
        return None

    # Guardrail 2: mechanism must be concrete
    valid, reason = MechanismValidator().validate(proposal)
    if not valid:
        logger.warning(f"Proposal suppressed (MechanismValidator): {reason}")
        return None

    # Guardrail 3: savings estimate bounds
    valid, reason = SavingsEstimateValidator().validate(proposal, session)
    if not valid:
        # Don't suppress — downgrade to speculative
        proposal.confidence = min(proposal.confidence, 0.40)
        proposal.mechanism = f"[SPECULATIVE — estimate may be inaccurate] {proposal.mechanism}"
        logger.warning(f"Proposal downgraded: {reason}")

    return proposal
```

---

# Chapter 3: FRONTIER
## "Is WorkflowX a Human-in-the-Loop Risk?"

### Level 1 — The WorkflowX Problem

WorkflowX observes everything you do on your computer. It reads OCR text from your screen. It infers what you were trying to accomplish. It then proposes changes to how you work.

That sentence deserves a second read.

It's not an AI writing an email for you. It's an AI watching you work, labeling your behavior, and telling you what you're doing wrong. The failure mode isn't a bad email draft — it's systematic misclassification of human work patterns that trains you to adopt workflows designed around LLM assumptions rather than actual productivity.

That's a different category of risk. And it requires a Frontier-style assessment before the LLM is given any decision authority over proposals.

### Level 2 — Frontier Assessment for WorkflowX

**Criterion 1 — Plausibility (Is the harm real and quantifiable?)**
A user adopts a WorkflowX proposal that replaces their manual review process with an LLM agent. The agent misses an important context (client relationship history not in Screenpipe data). User sends incorrect email. Estimated harm: relationship damage, deal loss ($50K+ in B2B context). Plausibility: medium. Not catastrophic but not trivial.

**Criterion 2 — Measurability (Can we detect when it's going wrong?)**
Yes. ROI grader measures whether savings claims are accurate. IntentGrader detects when inference quality drops. Confidence scores flag low-certainty proposals. Measurable.

**Criterion 3 — Severity (How bad is the worst case?)**
Moderate. The system proposes — it doesn't execute. Users always implement the replacement manually. No autonomous action. Worst case: user wastes time implementing a proposal that doesn't work.

**Criterion 4 — Net Novelty (Is this materially different from existing tools?)**
Yes. WorkflowX is observational + inferential + prescriptive. Most productivity tools are one of those three. The combination is new and creates a new class of algorithmic influence over human work patterns.

**Criterion 5 — Irreversibility (If wrong, can you undo it?)**
Partially. A bad proposal can be ignored. But behavioral habituation (users slowly reorganizing their work around LLM-suggested patterns) is gradual and hard to reverse. Proposal history + adoption tracking makes this recoverable.

**Frontier verdict: MEDIUM risk. Proceed with confidence guardrail + opt-in observability consent.**

### Level 3 — Implementation for WorkflowX

**What you have:**
- `ReplacementProposal.confidence` — LLM self-assessment.
- Privacy-first local JSON storage (screen data never leaves the machine).
- No human-review gate on proposals.
- No consent mechanism for screen observation.

**What's missing:**
- Explicit consent dialog on first run (screen observation is sensitive).
- No "decline proposal" tracking (if users consistently decline certain types, that's signal).
- No proposal review audit trail (what did I adopt, when, based on what evidence?).
- Missing `shadow_mode` for proposals: show them without recommending adoption.

### Level 4 — TRUE² Mapping for WorkflowX

| Layer | WorkflowX Application |
|-------|----------------------|
| Transferable | The 5-criteria Frontier assessment pattern applies to any productivity AI that observes + prescribes |
| Transformable | Add real-time risk scoring per proposal based on proposal type (workflow change vs. tool replacement vs. delegation) |
| Replicable | Frontier assessment as a written doc artifact, updated each major feature release |
| Refineable | Add new criteria as real harm cases emerge from users |
| Understandable | "This proposal carries MEDIUM risk because it involves delegating email drafting to an agent — verify the output before sending." |
| Usable | Confidence floor + shadow mode for new proposal types |
| Experiencable | Run WorkflowX on your own work for one week in shadow mode before enabling recommendations |
| Experimentable | Deploy shadow_mode vs. full_recommendations A/B to measure adoption vs. accuracy tradeoff |

### Detailed Improvement Instructions

**Improvement 1: Shadow mode for new proposal types**

```python
# src/workflowx/models.py  (extended)

class ProposalRiskLevel(str, Enum):
    LOW = "low"           # Workflow change, no delegation
    MEDIUM = "medium"     # Partial delegation to LLM
    HIGH = "high"         # Full delegation, autonomous action

class ReplacementProposal(BaseModel):
    # ... existing fields ...
    risk_level: ProposalRiskLevel = ProposalRiskLevel.LOW
    shadow_mode: bool = False   # If True, show proposal but mark as "for review"
```

```python
# src/workflowx/replacement/engine.py  (extended)

def _classify_risk(proposal: ReplacementProposal) -> ProposalRiskLevel:
    """Classify proposal risk by checking for autonomous delegation."""
    mechanism_lower = proposal.mechanism.lower()

    if any(w in mechanism_lower for w in ["sends automatically", "auto-sends", "no review needed"]):
        return ProposalRiskLevel.HIGH
    if any(w in mechanism_lower for w in ["draft", "generates", "creates", "agent handles"]):
        return ProposalRiskLevel.MEDIUM
    return ProposalRiskLevel.LOW
```

**Improvement 2: Consent-first screen observation**

```python
# src/workflowx/cli/main.py  (init command)

@cli.command()
def init():
    """Initialize WorkflowX — shows consent dialog."""

    consent_text = """
WorkflowX observes your screen activity (app titles, window names, OCR text)
to identify high-friction workflows and suggest improvements.

What it captures: app names, window titles, screen text, timing
What it does NOT capture: passwords, private messages sent to external servers
Where data goes: local storage only (~/.workflowx/sessions/)
How to stop: `workflowx stop` at any time

Proceed? [y/N]
    """

    if click.confirm(consent_text, default=False):
        config = load_config()
        config.consent_given = True
        config.consent_date = datetime.now().isoformat()
        save_config(config)
        click.echo("WorkflowX initialized. Run `workflowx capture` to start.")
    else:
        click.echo("Consent not given. WorkflowX will not capture screen data.")
```

---

# Chapter 4: CODEX
## "What an Async Engineer Would Build"

### Level 1 — The WorkflowX Problem

WorkflowX has 12 test files but several important engineering gaps that require focused, asynchronous engineering time — not ad hoc fixes during research sessions. These are well-defined tasks with clear acceptance criteria, real-world impact, and no ambiguity about what "done" looks like.

They're exactly the kind of task that OpenAI Codex was designed for: give a codebase, state the requirements, return a working implementation.

### Level 2 — Codex Task Map for WorkflowX

```
WorkflowX Codex Task Queue
        │
        ├── Task 1: Eval dataset builder CLI
        │   Input: raw sessions  Output: annotated_sessions.json
        │
        ├── Task 2: Intent grader test suite
        │   Input: IntentGrader class  Output: 15 pytest cases
        │
        ├── Task 3: Agenticom YAML validator
        │   Input: agenticom_workflow_yaml field  Output: schema validator
        │
        └── Task 4: Dashboard ROI accuracy widget
            Input: ReplacementOutcome data  Output: MAPE display widget
```

### Level 3 — Implementation for WorkflowX

**What you have:**
- `src/workflowx/cli/main.py` — 13 CLI commands, Click-based.
- `src/workflowx/storage.py` — `LocalStore` with full CRUD for sessions, questions, outcomes.
- `src/workflowx/dashboard.py` — HTML dashboard generator.
- `src/workflowx/mcp_server.py` — 12 MCP tool handlers.
- No YAML schema validation for generated Agenticom workflows.

**What's missing:**
- CLI command for annotating sessions to build the gold dataset.
- Schema validator for the `agenticom_workflow_yaml` field in `ReplacementProposal`.
- Dashboard widget showing ROI MAPE (accuracy of savings estimates).
- Integration tests for the full capture → cluster → infer → propose → measure loop.

### Level 4 — TRUE² Mapping for WorkflowX

| Layer | WorkflowX Application |
|-------|----------------------|
| Transferable | The "eval dataset builder CLI" pattern applies to any LLM app needing human annotation at scale |
| Transformable | Add a `workflowx export --format=openai-eval` command that converts annotated sessions to OpenAI eval format |
| Replicable | All 4 tasks have concrete acceptance criteria — assignable to Codex without further clarification |
| Refineable | YAML validator spec expands as Agenticom adds new workflow primitives |
| Understandable | "Codex task: implement `workflowx annotate` — a CLI that shows sessions one by one and prompts for intent label, friction level, and recurrence flag" |
| Usable | Run Codex against each task specification independently |
| Experiencable | After Codex delivers the eval dataset builder, run it on 20 real sessions from ~/.workflowx/ and inspect the annotation quality |
| Experimentable | Give Codex the same task spec twice with different context windows — compare implementations for structural differences |

### Detailed Improvement Instructions

**Codex Task 1: Eval dataset builder CLI**

```
Task specification for Codex:

File: src/workflowx/cli/main.py
Add: workflowx annotate command

Behavior:
- Load sessions from LocalStore for the past 7 days
- For each session, display:
  * Timestamp, duration, apps used, inferred_intent (if any)
  * Context switches count, friction_level (if inferred)
- Prompt user for:
  * Intent label (free text, e.g., "Summarize Slack threads into status update")
  * Friction level (LOW/MEDIUM/HIGH/CRITICAL)
  * Is this recurring? (y/n)
  * Skip this session? (s)
- Save annotations to eval/datasets/annotated_sessions.json

Acceptance criteria:
- `workflowx annotate --days 7` runs without error
- Produces valid annotated_sessions.json with schema matching examples/
- Sessions already in gold dataset are skipped automatically
- Handles KeyboardInterrupt gracefully (saves progress)
```

**Codex Task 2: Agenticom YAML schema validator**

```
Task specification for Codex:

File: src/workflowx/guardrails/yaml_validator.py (new file)

Behavior:
- Validate the agenticom_workflow_yaml field in ReplacementProposal
- Valid YAML must include:
  * Top-level 'id', 'name', 'agents', 'steps' keys
  * At least 1 agent with 'id', 'role', 'prompt' fields
  * At least 1 step with 'id', 'agent', 'input' fields
  * agent references in steps must match defined agent IDs
- Return (bool, str): (is_valid, error_message)

Schema (Pydantic for validation):
class AgenticomAgentSchema(BaseModel):
    id: str
    role: str
    prompt: str
    tools: list[str] = []

class AgenticomStepSchema(BaseModel):
    id: str
    agent: str
    input: str
    on_failure: dict | None = None

class AgenticomYAMLSchema(BaseModel):
    id: str
    name: str
    agents: list[AgenticomAgentSchema]
    steps: list[AgenticomStepSchema]

Acceptance criteria:
- Valid YAML returns (True, "OK")
- YAML missing 'agents' returns (False, "Missing required key: agents")
- YAML with unresolved agent reference returns (False, "Step 'X' references undefined agent 'Y'")
- 15 pytest cases covering all branches
```

---

# Chapter 5: AGENTS SDK
## "The MCP Server IS the Agent Interface"

### Level 1 — The WorkflowX Problem

WorkflowX already has a 12-tool MCP server. You run `workflowx mcp` and Claude Desktop can call `workflowx_capture`, `workflowx_analyze`, `workflowx_propose`. This is good.

But the MCP server is a thin wrapper over CLI commands. It's procedural — you call tools in sequence and assemble the result yourself. There's no orchestration, no error recovery, no specialist routing. If `workflowx_analyze` returns empty results because Screenpipe wasn't running, nothing handles that.

The OpenAI Agents SDK pattern turns the MCP tools into a directed workflow with specialists, handoffs, and error recovery. Instead of "call these tools in sequence," you get "run this flywheel end-to-end."

### Level 2 — Agent Architecture for WorkflowX

```
WorkflowX Flywheel Agent System
                    │
                    ▼
         ┌──────────────────────┐
         │  FlywheelOrchestrator│  (triage + route)
         │  (GPT-4o)            │
         └──────────┬───────────┘
                    │
        ┌───────────┼──────────────┐
        ▼           ▼              ▼
 ┌─────────────┐ ┌───────────┐ ┌──────────────┐
 │CaptureAgent │ │AnalysisAgent│ │ProposalAgent│
 │Screenpipe   │ │Cluster +  │ │Replacement  │
 │HealthCheck  │ │IntentInfer│ │+YAML export │
 │(Haiku)      │ │(Sonnet)   │ │(Sonnet)     │
 └──────┬──────┘ └─────┬─────┘ └──────┬──────┘
        │              │               │
        └──────────────┴───────────────┘
                       │
                       ▼
              ROIMeasurementAgent
              (Outcome tracking)
              (Haiku)
```

### Level 3 — Implementation for WorkflowX

**What you have:**
- `src/workflowx/mcp_server.py` — 12 MCP handlers: `handle_status`, `handle_capture`, `handle_analyze`, `handle_friction`, `handle_patterns`, `handle_propose`, `handle_adopt`, `handle_measure`, `handle_roi`, `handle_sessions`, `handle_trends`, `handle_diagnose`.
- MCP server runs on stdio or HTTP.
- No agent orchestration layer — all tools called manually by user via Claude Desktop.

**What's missing:**
- No `FlywheelOrchestrator` that runs the full pipeline automatically.
- No error recovery if `handle_capture` returns empty (Screenpipe not running).
- No handoff protocol from `CaptureAgent` to `AnalysisAgent`.
- No `ROIMeasurementAgent` that fires automatically 2 weeks post-adoption.

### Level 4 — TRUE² Mapping for WorkflowX

| Layer | WorkflowX Application |
|-------|----------------------|
| Transferable | FlywheelOrchestrator triage-and-route pattern applies to any observability tool with capture → analyze → propose pipeline |
| Transformable | Add a `ReportingAgent` that generates a formatted weekly summary and emails/Slacks it to the user |
| Replicable | Each agent spec is a YAML-definable Agenticom workflow — dog-fooding WorkflowX's own replacement |
| Refineable | Add HealthCheckAgent that validates Screenpipe connection before any analysis |
| Understandable | "CaptureAgent returned 0 events — Screenpipe appears to not be running. Handing off to HealthCheckAgent." |
| Usable | `workflowx run-flywheel` triggers the full orchestrated pipeline via a single command |
| Experiencable | Watch FlywheelOrchestrator route a 0-event capture result to HealthCheckAgent in real-time |
| Experimentable | Add a slow path where AnalysisAgent requests human validation when confidence < 0.7, measure how often this triggers |

### Detailed Improvement Instructions

**Improvement 1: FlywheelOrchestrator with error recovery**

```python
# src/workflowx/agents/flywheel.py

from openai import OpenAI
from agents import Agent, Runner, handoff

capture_agent = Agent(
    name="CaptureAgent",
    instructions="""
    You check Screenpipe health and capture recent events.

    Tools available:
    - workflowx_status: Check if Screenpipe is running
    - workflowx_capture: Read events from Screenpipe DB

    If status shows Screenpipe not running, return:
    {"status": "error", "reason": "screenpipe_not_running"}

    If capture returns < 5 events, return:
    {"status": "insufficient_data", "events_found": N}

    Otherwise return:
    {"status": "ok", "events_captured": N, "period_hours": 8}
    """,
    model="claude-haiku-4-5-20251001",
    tools=[workflowx_status_tool, workflowx_capture_tool],
)

analysis_agent = Agent(
    name="AnalysisAgent",
    instructions="""
    You cluster captured events into sessions and infer intent.

    Tools available:
    - workflowx_analyze: Run clustering + intent inference
    - workflowx_friction: Get friction-sorted session list

    Focus on sessions with FrictionLevel.HIGH or FrictionLevel.CRITICAL.
    Return top 3 friction sessions with intent and estimated cost.
    """,
    model="claude-sonnet-4-5-20250929",
    tools=[workflowx_analyze_tool, workflowx_friction_tool],
)

proposal_agent = Agent(
    name="ProposalAgent",
    instructions="""
    You generate replacement proposals for the highest-friction sessions.

    Tools available:
    - workflowx_propose: Generate replacement proposals

    For each proposal:
    - Verify mechanism is concrete (names a specific tool)
    - Verify savings estimate is plausible (< 3× observed duration)
    - If agenticom_workflow_yaml is present, validate YAML structure

    Return proposals with confidence ≥ 0.55 only.
    """,
    model="claude-sonnet-4-5-20250929",
    tools=[workflowx_propose_tool],
)

flywheel_orchestrator = Agent(
    name="FlywheelOrchestrator",
    instructions="""
    You run the WorkflowX flywheel: capture → analyze → propose.

    Step 1: Hand off to CaptureAgent.
    - If CaptureAgent returns "screenpipe_not_running": stop, tell user to start Screenpipe.
    - If CaptureAgent returns "insufficient_data": stop, tell user to work for at least 30 minutes.
    - If CaptureAgent returns "ok": proceed to Step 2.

    Step 2: Hand off to AnalysisAgent.
    - If AnalysisAgent finds 0 HIGH/CRITICAL sessions: tell user "No high-friction sessions detected today."
    - Otherwise: proceed to Step 3.

    Step 3: Hand off to ProposalAgent.
    - Present proposals to user for review.
    - Do not mark anything as adopted without explicit user confirmation.
    """,
    model="gpt-4o",
    handoffs=[
        handoff(capture_agent),
        handoff(analysis_agent),
        handoff(proposal_agent),
    ],
)
```

---

# Chapter 6: MEMORY
## "WorkflowX Forgets What It Observed Last Week"

### Level 1 — The WorkflowX Problem

You've used WorkflowX for 6 weeks. In week 2, you had a HIGH-friction session around invoice processing. You declined the proposal. In week 5, the same pattern appeared again. WorkflowX proposed the same thing. You declined again.

WorkflowX doesn't know you declined last time. It doesn't know you've tried this three times. It doesn't know that the proposal it's about to make has a 100% rejection history from you.

The three-tier memory architecture is what gives WorkflowX the ability to learn from its history with you, not just observe your present.

### Level 2 — Three-Tier Memory Architecture for WorkflowX

```
┌─────────────────────────────────────────────────────────────────┐
│  Tier 1: Working Memory (In-Context)                            │
│  Today's sessions + active proposals                            │
│  Ephemeral. Lost on session end.                                │
│  Source: LocalStore.load_sessions(today)                        │
├─────────────────────────────────────────────────────────────────┤
│  Tier 2: Semantic Memory (Vector Store — OpenAI File Search)    │
│  Intent patterns + proven proposals + declined proposals        │
│  Persistent. Searched by semantic similarity.                   │
│  Source: WorkflowPattern + ReplacementOutcome (adopted+declined)│
├─────────────────────────────────────────────────────────────────┤
│  Tier 3: Episodic Memory (SQLite)                               │
│  Per-proposal adoption history, rejection reasons, ROI outcomes │
│  Persistent. Queryable by proposal_id, intent, date, outcome.   │
│  Source: ReplacementOutcome table                               │
└─────────────────────────────────────────────────────────────────┘
```

### Level 3 — Implementation for WorkflowX

**What you have:**
- `src/workflowx/storage.py` — `LocalStore`. JSON files per day. Outcomes stored in `outcomes/outcomes_{date}.json`.
- `src/workflowx/models.py` — `ReplacementOutcome` with `status: str` ("pending", "adopted", "rejected", "measuring").
- `src/workflowx/measurement.py` — `measure_outcome()`. Intent-matching post-adoption.
- No vector search. No semantic retrieval of past patterns.
- No rejection reason storage.

**What's missing:**
- No OpenAI vector store indexing past proposals and outcomes.
- No semantic retrieval: "have I proposed something similar to this intent before?"
- No rejection reason field in `ReplacementOutcome`.
- No memory-augmented proposal generation (proposals don't know their own history).

### Level 4 — TRUE² Mapping for WorkflowX

| Layer | WorkflowX Application |
|-------|----------------------|
| Transferable | Three-tier memory pattern applies to any personalized AI productivity tool |
| Transformable | Add a ProposalMemory.find_similar() method that retrieves the 3 most similar past proposals (adopted or rejected) before generating a new one |
| Replicable | Vector store indexed from LocalStore.load_outcomes() — can be rebuilt from scratch |
| Refineable | Add rejection_reason field to ReplacementOutcome; use it to filter out repeatedly rejected proposal types |
| Understandable | "Found 2 similar past proposals for 'invoice processing workflow'. Both were rejected. Generating a more conservative proposal." |
| Usable | Memory retrieval runs synchronously in propose_replacement() before LLM call |
| Experiencable | Reject a proposal. Re-run WorkflowX 3 days later. Watch it surface a different approach for the same intent. |
| Experimentable | Compare proposal adoption rate with vs. without memory-augmented generation |

### Detailed Improvement Instructions

**Improvement 1: OpenAI vector store for proposal history**

```python
# src/workflowx/memory/semantic.py

from openai import OpenAI
import json

class SemanticProposalMemory:
    """
    Indexes past proposals and outcomes in an OpenAI vector store.
    Retrieved via File Search before generating new proposals.
    """

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.vector_store_id = None  # Loaded from config

    def initialize_store(self, name: str = "workflowx-proposals") -> str:
        """Create vector store if not exists."""
        store = self.client.vector_stores.create(name=name)
        self.vector_store_id = store.id
        return store.id

    def index_outcome(self, outcome: ReplacementOutcome) -> None:
        """Add a proposal outcome to the vector store."""
        document = {
            "intent": outcome.intent,
            "original_workflow": outcome.proposal.original_workflow,
            "proposed_workflow": outcome.proposal.proposed_workflow,
            "mechanism": outcome.proposal.mechanism,
            "outcome": outcome.status,  # "adopted" or "rejected"
            "rejection_reason": outcome.rejection_reason,
            "actual_savings_minutes": outcome.actual_savings_minutes,
            "weeks_tracked": outcome.weeks_tracked,
        }

        file_content = json.dumps(document, indent=2)
        # Upload to vector store
        file = self.client.files.create(
            file=(f"outcome_{outcome.id}.json", file_content.encode()),
            purpose="assistants",
        )
        self.client.vector_stores.files.create(
            vector_store_id=self.vector_store_id,
            file_id=file.id,
        )

    def find_similar(
        self,
        intent: str,
        top_k: int = 3,
    ) -> list[dict]:
        """
        Retrieve similar past proposals using File Search.
        Returns list of past outcomes ordered by similarity.
        """
        # This runs via Assistants API File Search tool
        response = self.client.beta.assistants.create(
            model="gpt-4o-mini",
            tools=[{"type": "file_search"}],
            tool_resources={"file_search": {"vector_store_ids": [self.vector_store_id]}},
            instructions="Retrieve the most relevant past workflow replacement proposals.",
        )
        # ... thread + run to get results
        return []  # Parsed results from File Search response
```

**Improvement 2: Rejection reason capture**

```python
# src/workflowx/models.py  (extended)

class RejectionReason(str, Enum):
    TOO_COMPLEX = "too_complex"
    WRONG_TOOLS = "wrong_tools"
    INACCURATE_SAVINGS = "inaccurate_savings"
    ALREADY_TRIED = "already_tried"
    NOT_RELEVANT = "not_relevant"
    OTHER = "other"

class ReplacementOutcome(BaseModel):
    # ... existing fields ...
    rejection_reason: RejectionReason | None = None
    rejection_notes: str | None = None
```

```python
# src/workflowx/cli/main.py  (extended)

@cli.command()
@click.argument("proposal_id")
@click.option("--reason", type=click.Choice([r.value for r in RejectionReason]))
@click.option("--notes", default="")
def reject(proposal_id: str, reason: str, notes: str):
    """Reject a proposal with a reason."""
    store = LocalStore(config.data_dir)
    outcomes = store.load_outcomes()

    for outcome in outcomes:
        if outcome.proposal_id == proposal_id:
            outcome.status = "rejected"
            outcome.rejection_reason = RejectionReason(reason) if reason else None
            outcome.rejection_notes = notes

    store.save_outcomes(outcomes)
    memory = SemanticProposalMemory(api_key=config.openai_api_key)
    memory.index_outcome(outcome)  # Index in vector store
```

---

# Chapter 7: REASONING
## "When Should WorkflowX Think Hard?"

### Level 1 — The WorkflowX Problem

WorkflowX makes decisions at three different speeds in three different contexts:

1. "Is this session worth showing to the user?" — a pattern match. Milliseconds. No deep reasoning needed.
2. "What is this user trying to accomplish across 47 events over 23 minutes?" — intent inference. Structured reasoning over noisy data. Seconds are acceptable.
3. "Given that this user rejected 3 similar proposals about invoice processing, what fundamentally different approach should we suggest?" — complex, multi-step analysis with conflicting evidence. This is where reasoning models matter.

Routing the right decision to the right model is the difference between WorkflowX being a fast productivity tool and a slow expensive one.

### Level 2 — Model Selection Architecture for WorkflowX

```
Decision point                     Model              Why
──────────────────────────────────────────────────────────────────────
Intent inference (single session)  GPT-4o / Sonnet    Fast structured output
Friction level classification      GPT-4o / Haiku     Simple classification
Savings estimate generation        GPT-4o / Sonnet    JSON + arithmetic
Proposal mechanism generation      GPT-4o / Sonnet    Creative + specific
Proposal quality grading (eval)    GPT-4o / Sonnet    Structured reasoning
Cross-session pattern synthesis    o4-mini            Multi-session reasoning
"Why does user keep rejecting?"    o4-mini            Conflicting evidence
Novel replacement for stuck intent o3                 Complex creative + feasibility
Weekly ROI analysis narrative      o4-mini            Structured multi-step
```

**Hard rule:** Never use o3 or o4-mini on the <2s latency path (live capture, session clustering, friction computation). These are pure computation — no LLM needed.

### Level 3 — Implementation for WorkflowX

**What you have:**
- `src/workflowx/inference/intent.py` — Uses `claude-sonnet-4-6` by default.
- `src/workflowx/replacement/engine.py` — Uses `claude-sonnet-4-6` by default.
- No model routing — everything uses the same model.
- No reasoning model usage for complex multi-session analysis.

**What's missing:**
- No `select_model()` routing function.
- No reasoning model invocation for "stuck intent" proposals (user has rejected 3+ times).
- No cost tracking per decision type.
- No prompt adaptation for o-series (specification-complete prompts, no "think step by step").

### Level 4 — TRUE² Mapping for WorkflowX

| Layer | WorkflowX Application |
|-------|----------------------|
| Transferable | `select_model()` routing logic applies to any multi-task LLM application with mixed latency requirements |
| Transformable | Add a "reasoning mode" CLI flag: `workflowx propose --deep` invokes o3 for complex stuck workflows |
| Replicable | Model routing captured in config.yaml — auditable, overridable |
| Refineable | Track cost per model per decision type; rebalance routing as usage patterns become clear |
| Understandable | "Intent inference: GPT-4o (0.8s, $0.003). Stuck-intent analysis: o3 (42s, $0.18). Total: $0.183." |
| Usable | Model selection is transparent to user but configurable via WORKFLOWX_MODEL_TIER env var |
| Experiencable | Run `workflowx propose --intent "invoice processing" --deep` and compare proposal quality vs. standard mode |
| Experimentable | Run the same stuck-intent through o4-mini vs. o3. Compare proposal novelty and feasibility. |

### Detailed Improvement Instructions

**Improvement 1: Model selection function**

```python
# src/workflowx/reasoning/model_selector.py

from enum import Enum

class DecisionType(str, Enum):
    # Fast path — no reasoning model
    INTENT_INFERENCE = "intent_inference"         # Single session
    FRICTION_CLASSIFY = "friction_classify"       # Simple classification
    SAVINGS_ESTIMATE = "savings_estimate"         # JSON generation

    # Moderate path — structured multi-step
    PATTERN_SYNTHESIS = "pattern_synthesis"       # Multi-session
    REJECTION_ANALYSIS = "rejection_analysis"     # Conflicting evidence
    WEEKLY_NARRATIVE = "weekly_narrative"         # ROI summary

    # Complex path — novel reasoning required
    STUCK_INTENT_PROPOSAL = "stuck_intent"        # 3+ rejections, need new approach
    MULTI_SYSTEM_DIAGNOSIS = "multi_system"       # Complex workflow spanning 5+ apps

MODEL_ROUTING = {
    # Fast path (GPT-4o ~1-2s)
    DecisionType.INTENT_INFERENCE: "gpt-4o",
    DecisionType.FRICTION_CLASSIFY: "gpt-4o",
    DecisionType.SAVINGS_ESTIMATE: "gpt-4o",

    # Moderate path (o4-mini ~10-15s)
    DecisionType.PATTERN_SYNTHESIS: "o4-mini",
    DecisionType.REJECTION_ANALYSIS: "o4-mini",
    DecisionType.WEEKLY_NARRATIVE: "o4-mini",

    # Complex path (o3 ~30-60s, ~$0.15/call — use sparingly)
    DecisionType.STUCK_INTENT_PROPOSAL: "o3",
    DecisionType.MULTI_SYSTEM_DIAGNOSIS: "o3",
}

def select_model(decision_type: DecisionType, override: str | None = None) -> str:
    if override:
        return override
    return MODEL_ROUTING[decision_type]
```

**Improvement 2: Stuck-intent proposal with o3**

A "stuck intent" is a workflow where the user has rejected 3+ proposals. The standard prompt fails here because it generates incrementally similar proposals. o3 + a specification-complete prompt breaks the pattern.

```python
# src/workflowx/replacement/engine.py  (extended)

async def propose_for_stuck_intent(
    intent: str,
    rejection_history: list[ReplacementOutcome],
    session: WorkflowSession,
) -> ReplacementProposal:
    """
    Use o3 for intents with 3+ rejections.
    Specification-complete prompt: no 'think step by step' instruction.
    """

    rejected_approaches = [o.proposal.proposed_workflow for o in rejection_history]
    rejected_reasons = [o.rejection_reason for o in rejection_history if o.rejection_reason]

    prompt = f"""
INTENT: {intent}

OBSERVED SESSION:
- Duration: {session.total_duration_minutes:.0f} minutes
- Apps: {', '.join(session.apps_used)}
- Context switches: {session.context_switches}
- Friction: {session.friction_details}

REJECTED APPROACHES (do not propose these or close variants):
{chr(10).join(f"- {a}" for a in rejected_approaches)}

REJECTION REASONS:
{chr(10).join(f"- {r.value if r else 'unspecified'}" for r in rejected_reasons)}

TASK: Propose a fundamentally different approach to accomplish this intent.
Requirements:
1. Must not resemble any rejected approach
2. Must name a specific tool or API
3. Must include a concrete mechanism (not "use AI to automate")
4. Must estimate realistic time savings based on the observed session data
5. Must list any new tools or access required

Output JSON:
{{
  "proposed_workflow": "...",
  "mechanism": "...",
  "estimated_time_after_minutes": N,
  "estimated_savings_minutes_per_week": N,
  "confidence": 0.0-1.0,
  "requires_new_tools": ["..."],
  "why_different": "..."
}}
"""

    # o3 prompt rules: specification-complete, no "think step by step"
    model = select_model(DecisionType.STUCK_INTENT_PROPOSAL)
    response = await llm_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_proposal_json(response.choices[0].message.content)
```

**Cost tracking:**

```python
# src/workflowx/reasoning/cost_logger.py

COST_PER_1M_INPUT_TOKENS = {
    "gpt-4o": 2.50,
    "o4-mini": 1.10,
    "o3": 15.00,
}

def log_model_call(model: str, input_tokens: int, output_tokens: int, decision_type: str):
    cost = (input_tokens / 1_000_000) * COST_PER_1M_INPUT_TOKENS.get(model, 0)
    logger.info(f"MODEL_CALL model={model} decision={decision_type} tokens={input_tokens}+{output_tokens} cost=${cost:.4f}")
```

---

*WorkflowX with the full OpenAI tech stack: continuous eval of intent accuracy, guardrails on every proposal, measured ROI that closes the flywheel, and o3 as the last resort for stuck workflows that nothing else can unlock.*
