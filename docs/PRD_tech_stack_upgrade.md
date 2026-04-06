# PRD: WorkflowX Tech Stack Upgrade v0.4
*Derived from: OpenAI Tech Stack Deep Dive (2026-03-03)*
*Aligned with: Flywheel Roadmap Phase 3→4 transition*

---

## Problem Statement

WorkflowX proposes workflow replacements but has no way to prove they work.
The "savings" numbers are LLM guesses with progress bars. Three critical gaps:

1. **No eval system** — Can't measure if intent inference is accurate
2. **No guardrails** — Vague/inflated proposals reach users unchecked
3. **No proposal memory** — Same rejected proposal offered repeatedly

These gaps break the flywheel at the trust layer. Without trust, no adoption.
Without adoption, no measurement. Without measurement, no compounding.

---

## Scope: 5 Features, Each with Before/After Proof

### Feature 1: Guardrails (Chapter 2)
**Why first:** Prevents garbage proposals NOW. Highest immediate value.

| Before | After |
|--------|-------|
| Proposal with "leverage AI to streamline" passes to user | MechanismValidator blocks: "vague mechanism, no named tool" |
| Savings estimate of 500 min/week from a 30-min session passes | SavingsEstimateValidator caps: "exceeds 3× observed duration" |
| Confidence=0.3 proposal shown to user | Confidence floor suppresses proposals < 0.55 |

**Deliverables:**
- `src/workflowx/guardrails/__init__.py`
- `src/workflowx/guardrails/mechanism_validator.py`
- `src/workflowx/guardrails/savings_validator.py`
- Wire into `replacement/engine.py`
- `tests/unit/test_guardrails.py` — 15+ test cases

### Feature 2: Eval System (Chapter 1)
**Why second:** Proves the flywheel turns with real numbers.

| Before | After |
|--------|-------|
| No way to measure intent inference accuracy | `workflowx eval` → intent_accuracy=0.85, friction_accuracy=0.75 |
| Prompt changes silently degrade quality | CI gate: block if intent F1 < 0.80 |
| ROI claims are extrapolations | ROI MAPE tracks estimate vs actual |

**Deliverables:**
- `eval/datasets/annotated_sessions.json` — 20 gold sessions
- `eval/graders/intent_grader.py` — IntentGrader (soft F1)
- `eval/graders/friction_grader.py` — FrictionGrader (exact match)
- `eval/graders/roi_grader.py` — ROIGrader (MAPE)
- `eval/runner.py` — EvalRunner (unit/integration/e2e modes)
- `tests/unit/test_eval.py` — 12+ test cases

### Feature 3: Agenticom YAML Validator (Chapter 4)
**Why third:** Ensures generated YAML is machine-executable.

| Before | After |
|--------|-------|
| YAML missing `agents` key passes through | Validator catches: "Missing required key: agents" |
| Step references non-existent agent ID | Validator catches: "Step X references undefined agent Y" |
| No schema enforcement on Agenticom output | Pydantic schema validates all fields |

**Deliverables:**
- `src/workflowx/guardrails/yaml_validator.py`
- Wire into guardrail pipeline
- `tests/unit/test_yaml_validator.py` — 15 test cases

### Feature 4: Proposal Memory (Chapter 6, lightweight)
**Why fourth:** Stops the "rejected proposal loop."

| Before | After |
|--------|-------|
| User rejects proposal, same one offered next week | History check finds 2 prior rejections, generates different approach |
| No rejection reason stored | `RejectionReason` enum + notes captured |
| Proposals don't know their own history | `find_similar_proposals()` retrieves past outcomes before generation |

**Deliverables:**
- `RejectionReason` enum + fields on `ReplacementOutcome`
- `src/workflowx/memory/__init__.py`
- `src/workflowx/memory/proposal_history.py` — local similarity search (no OpenAI dependency)
- Wire into `replacement/engine.py`
- MCP tool: `workflowx_reject(intent, reason, notes)`
- `tests/unit/test_proposal_memory.py` — 10+ test cases

### Feature 5: Model Routing (Chapter 7, Anthropic-native)
**Why fifth:** Right model for right task. Cost-aware.

| Before | After |
|--------|-------|
| Everything uses claude-sonnet-4-6 | Intent inference=Haiku (fast), proposals=Sonnet, stuck intents=Opus |
| No cost tracking | Per-call cost logging with decision type |
| No "stuck intent" detection | 3+ rejections → escalate to stronger model |

**Deliverables:**
- `src/workflowx/reasoning/__init__.py`
- `src/workflowx/reasoning/model_selector.py` — DecisionType enum + routing table
- `src/workflowx/reasoning/cost_logger.py` — Per-call cost tracking
- Wire into intent.py + engine.py
- `tests/unit/test_model_routing.py` — 8+ test cases

---

## Out of Scope (This Round)

| Chapter | Why Deferred |
|---------|-------------|
| Ch3: Frontier (shadow mode, consent) | Important for multi-user, not urgent for personal use |
| Ch5: Agents SDK (FlywheelOrchestrator) | MCP server already IS the agent interface. Adding orchestrator layer is premature before first flywheel spin completes |
| Ch6: OpenAI vector store | Local-first tool shouldn't depend on OpenAI cloud. Using local similarity search instead |

---

## Success Criteria

- All 5 features have passing tests proving before→after behavior change
- `make test` passes with 0 failures across new + existing tests
- Each guardrail has a test showing blocked/passed proposals
- Eval graders produce numeric scores on gold dataset
- Model routing is configurable via env var override
- README updated with links to new docs

---

## Version: 0.4.0 — "Trust Layer"
