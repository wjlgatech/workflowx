"""Replacement engine — generates reimagined workflows from diagnoses.

This is NOT RPA. We don't copy the old workflow.
We ask: "Given this goal, what's the best way to achieve it with AI?"
Then we generate an Agenticom workflow YAML if applicable.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from workflowx.models import ReplacementProposal, WorkflowDiagnosis, WorkflowSession

logger = structlog.get_logger()

REPLACEMENT_SYSTEM_PROMPT = """You are a workflow architect. Given a diagnosed workflow
(what the user was doing, how long it took, where friction occurred), propose a
REIMAGINED workflow that achieves the same goal in fundamentally less time.

Rules:
1. Do NOT replicate the old workflow with automation. Rethink from the goal.
2. Be specific about the mechanism — how exactly does the replacement work?
3. If an Agenticom multi-agent workflow could solve this, describe the pipeline steps.
4. Estimate realistic time savings (don't over-promise).
5. List any new tools required.

Respond in JSON:
{
  "proposed_workflow": "Short description of the new approach",
  "mechanism": "Detailed explanation of how it works step by step",
  "estimated_time_after_minutes": 5.0,
  "confidence": 0.8,
  "requires_new_tools": ["tool1", "tool2"],
  "agenticom_pipeline": [
    {"step": "step_name", "agent": "agent_role", "task": "what this step does"}
  ] | null
}"""


async def propose_replacement(
    diagnosis: WorkflowDiagnosis,
    session: WorkflowSession,
    llm_client: Any,
    model: str = "claude-sonnet-4-6",
) -> ReplacementProposal:
    """Generate a replacement proposal for a diagnosed workflow."""

    context = _build_diagnosis_context(diagnosis, session)

    try:
        if hasattr(llm_client, "messages"):
            response = await llm_client.messages.create(
                model=model,
                max_tokens=1500,
                system=REPLACEMENT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            content = response.content[0].text
        else:
            response = await llm_client.chat.completions.create(
                model=model,
                max_tokens=1500,
                messages=[
                    {"role": "system", "content": REPLACEMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
            )
            content = response.choices[0].message.content

        # Strip markdown code fences if present (```json ... ```)
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            stripped = stripped.rsplit("```", 1)[0].strip()
        result = json.loads(stripped)

        # Generate Agenticom YAML if pipeline was proposed
        agenticom_yaml = ""
        if result.get("agenticom_pipeline"):
            agenticom_yaml = _generate_agenticom_yaml(
                diagnosis.intent,
                result["agenticom_pipeline"],
            )

        proposal = ReplacementProposal(
            diagnosis_id=diagnosis.session_id,
            original_workflow=f"{diagnosis.intent} ({diagnosis.total_time_minutes:.0f}min, "
            f"friction: {', '.join(diagnosis.friction_points[:3])})",
            proposed_workflow=result.get("proposed_workflow", ""),
            mechanism=result.get("mechanism", ""),
            estimated_time_after_minutes=result.get("estimated_time_after_minutes", 0),
            estimated_savings_minutes_per_week=max(
                0,
                (diagnosis.total_time_minutes - result.get("estimated_time_after_minutes", 0)),
            ),
            confidence=result.get("confidence", 0.0),
            agenticom_workflow_yaml=agenticom_yaml,
            requires_new_tools=result.get("requires_new_tools", []),
        )

        logger.info(
            "replacement_proposed",
            session_id=diagnosis.session_id,
            savings_min=proposal.estimated_savings_minutes_per_week,
            confidence=proposal.confidence,
        )
        return proposal

    except Exception as e:
        logger.error("replacement_generation_failed", error=str(e))
        return ReplacementProposal(
            diagnosis_id=diagnosis.session_id,
            original_workflow=diagnosis.intent,
            proposed_workflow="(generation failed)",
            mechanism=f"Error: {e}",
        )


def _build_diagnosis_context(diagnosis: WorkflowDiagnosis, session: WorkflowSession) -> str:
    """Build context string for the LLM."""
    lines = [
        f"Workflow Intent: {diagnosis.intent}",
        f"Total Time: {diagnosis.total_time_minutes:.0f} minutes",
        f"Estimated Cost: ${diagnosis.estimated_cost_usd:.2f}",
        f"Automation Potential: {diagnosis.automation_potential:.0%}",
        f"Apps Used: {', '.join(session.apps_used)}",
        f"Context Switches: {session.context_switches}",
        f"Friction Points: {', '.join(diagnosis.friction_points)}",
    ]
    return "\n".join(lines)


def _generate_agenticom_yaml(intent: str, pipeline: list[dict[str, str]]) -> str:
    """Generate Agenticom-compatible workflow YAML from a pipeline description."""
    # Sanitize intent for use as workflow name
    name = intent.lower().replace(" ", "-").replace("/", "-")[:40]

    lines = [
        f"# Auto-generated by WorkflowX for: {intent}",
        f"name: {name}",
        f'description: "Automated workflow replacing manual {intent}"',
        "",
        "steps:",
    ]

    for step in pipeline:
        step_name = step.get("step", "unnamed")
        agent = step.get("agent", "planner")
        task = step.get("task", "")

        lines.extend([
            f"  - name: {step_name}",
            f"    agent: {agent}",
            f'    prompt: "{task}"',
            f"    depends_on: [{pipeline[pipeline.index(step) - 1]['step']}]"
            if pipeline.index(step) > 0 else "",
            "",
        ])

    return "\n".join(line for line in lines if line is not None)
