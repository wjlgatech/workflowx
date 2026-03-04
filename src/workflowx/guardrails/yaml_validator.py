"""Validates Agenticom workflow YAML structure and semantics."""

from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, ConfigDict, field_validator


class AgenticomAgentSchema(BaseModel):
    """Schema for an agent definition in Agenticom YAML."""

    model_config = ConfigDict(extra="allow")

    id: str
    role: str
    prompt: str
    tools: Optional[list[str]] = Field(default_factory=list)


class AgenticomStepSchema(BaseModel):
    """Schema for a step in an Agenticom workflow."""

    model_config = ConfigDict(extra="allow")

    id: str
    agent: str
    input: str
    on_failure: Optional[str] = None


class AgenticomYAMLSchema(BaseModel):
    """Top-level schema for an Agenticom workflow YAML."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    agents: list[AgenticomAgentSchema]
    steps: list[AgenticomStepSchema]
    description: Optional[str] = None

    @field_validator("agents")
    @classmethod
    def agents_not_empty(cls, v):
        if not v:
            raise ValueError("agents list cannot be empty")
        return v

    @field_validator("steps")
    @classmethod
    def steps_not_empty(cls, v):
        if not v:
            raise ValueError("steps list cannot be empty")
        return v


class AgenticomYAMLValidator:
    """Validates Agenticom workflow YAML structure and semantics."""

    @staticmethod
    def validate(yaml_str: str) -> tuple[bool, str]:
        """Validate an Agenticom workflow YAML.

        Args:
            yaml_str: The YAML string to validate.

        Returns:
            (True, "No YAML to validate") if yaml_str is None or empty.
            (True, "OK") if YAML is valid.
            (False, reason) if YAML is invalid.
        """
        # Handle None or empty input
        if not yaml_str or not yaml_str.strip():
            return (True, "No YAML to validate")

        try:
            # Parse YAML
            data = yaml.safe_load(yaml_str)

            if not data:
                return (True, "No YAML to validate")

            # Validate against Pydantic schema
            schema = AgenticomYAMLSchema(**data)

            # Check agent references in steps
            agent_ids = {agent.id for agent in schema.agents}
            for step in schema.steps:
                if step.agent not in agent_ids:
                    return (False, f"Step '{step.id}' references unknown agent '{step.agent}'")

            return (True, "OK")

        except yaml.YAMLError as e:
            return (False, f"Invalid YAML syntax: {str(e)}")
        except ValueError as e:
            return (False, f"Schema validation error: {str(e)}")
        except Exception as e:
            return (False, f"Validation error: {str(e)}")
