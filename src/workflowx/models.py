"""Core domain models for WorkflowX."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventSource(str, Enum):
    """Where the raw event came from."""

    SCREENPIPE = "screenpipe"
    ACTIVITYWATCH = "activitywatch"
    MANUAL = "manual"
    CUSTOM = "custom"


class RawEvent(BaseModel):
    """A single observed event from the capture layer."""

    timestamp: datetime
    source: EventSource
    app_name: str = ""
    window_title: str = ""
    url: str = ""
    ocr_text: str = ""
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class FrictionLevel(str, Enum):
    """How much friction this workflow step causes."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkflowSession(BaseModel):
    """A cluster of events that form a coherent workflow session."""

    id: str
    start_time: datetime
    end_time: datetime
    events: list[RawEvent] = Field(default_factory=list)
    inferred_intent: str = ""
    confidence: float = 0.0
    apps_used: list[str] = Field(default_factory=list)
    total_duration_minutes: float = 0.0
    context_switches: int = 0
    friction_level: FrictionLevel = FrictionLevel.LOW
    friction_details: str = ""
    user_validated: bool = False
    user_label: str = ""


class ClassificationQuestion(BaseModel):
    """A question posed to the user to validate/correct inference."""

    session_id: str
    question: str
    options: list[str]
    context: str = ""
    answer: str = ""
    answered: bool = False


class WorkflowDiagnosis(BaseModel):
    """Diagnosis of a workflow's efficiency."""

    session_id: str
    intent: str
    total_time_minutes: float
    friction_points: list[str] = Field(default_factory=list)
    estimated_cost_usd: float = 0.0
    automation_potential: float = 0.0  # 0.0 to 1.0
    recommended_approach: str = ""


class ReplacementProposal(BaseModel):
    """A proposed replacement for an inefficient workflow."""

    diagnosis_id: str
    original_workflow: str
    proposed_workflow: str
    mechanism: str  # How exactly this works — no hand-waving
    estimated_time_after_minutes: float = 0.0
    estimated_savings_minutes_per_week: float = 0.0
    confidence: float = 0.0
    agenticom_workflow_yaml: str = ""  # If auto-generated
    requires_new_tools: list[str] = Field(default_factory=list)


class WeeklyReport(BaseModel):
    """Weekly workflow intelligence report."""

    week_start: datetime
    week_end: datetime
    total_sessions: int = 0
    total_hours_tracked: float = 0.0
    top_workflows: list[WorkflowSession] = Field(default_factory=list)
    top_friction_points: list[WorkflowDiagnosis] = Field(default_factory=list)
    proposals: list[ReplacementProposal] = Field(default_factory=list)
    total_estimated_savings_minutes: float = 0.0
