"""Unit tests for YAML validator."""

import pytest

from workflowx.guardrails import AgenticomYAMLValidator


VALID_YAML = """
id: workflow-1
name: Email Processing Workflow
agents:
  - id: parser
    role: Email Parser
    prompt: Extract key information from emails
  - id: classifier
    role: Email Classifier
    prompt: Classify emails by priority
steps:
  - id: step-1
    agent: parser
    input: raw_email
  - id: step-2
    agent: classifier
    input: parsed_email
"""

MINIMAL_VALID_YAML = """
id: wf-min
name: minimal
agents:
  - id: a1
    role: agent
    prompt: do something
steps:
  - id: s1
    agent: a1
    input: input_data
"""

MISSING_AGENTS_KEY = """
id: workflow-1
name: Test
steps:
  - id: step-1
    agent: parser
    input: data
"""

MISSING_STEPS_KEY = """
id: workflow-1
name: Test
agents:
  - id: parser
    role: Parser
    prompt: Parse data
"""

EMPTY_AGENTS = """
id: workflow-1
name: Test
agents: []
steps:
  - id: step-1
    agent: parser
    input: data
"""

EMPTY_STEPS = """
id: workflow-1
name: Test
agents:
  - id: parser
    role: Parser
    prompt: Parse data
steps: []
"""

UNRESOLVED_AGENT_REF = """
id: workflow-1
name: Test
agents:
  - id: parser
    role: Parser
    prompt: Parse data
steps:
  - id: step-1
    agent: unknown_agent
    input: data
"""

AGENT_MISSING_ROLE = """
id: workflow-1
name: Test
agents:
  - id: parser
    prompt: Parse data
steps:
  - id: step-1
    agent: parser
    input: data
"""

AGENT_MISSING_PROMPT = """
id: workflow-1
name: Test
agents:
  - id: parser
    role: Parser
steps:
  - id: step-1
    agent: parser
    input: data
"""

STEP_MISSING_INPUT = """
id: workflow-1
name: Test
agents:
  - id: parser
    role: Parser
    prompt: Parse data
steps:
  - id: step-1
    agent: parser
"""

INVALID_YAML_SYNTAX = """
id: workflow-1
name: [
  this is invalid yaml
  missing closing bracket
"""

COMPLEX_VALID_YAML = """
id: complex-workflow
name: Complex Processing Pipeline
description: Multi-agent workflow for data processing
agents:
  - id: fetcher
    role: Data Fetcher
    prompt: Fetch data from sources
    tools: [curl, wget]
  - id: transformer
    role: Data Transformer
    prompt: Transform and clean data
    tools: [python]
  - id: loader
    role: Data Loader
    prompt: Load data to destination
    tools: [postgresql]
steps:
  - id: fetch
    agent: fetcher
    input: source_config
    on_failure: skip
  - id: transform
    agent: transformer
    input: raw_data
  - id: load
    agent: loader
    input: transformed_data
"""

STEP_WITH_ON_FAILURE = """
id: workflow-1
name: Test
agents:
  - id: processor
    role: Processor
    prompt: Process data
steps:
  - id: step-1
    agent: processor
    input: data
    on_failure: retry
"""

AGENT_WITH_TOOLS = """
id: workflow-1
name: Test
agents:
  - id: processor
    role: Processor
    prompt: Process data
    tools: [python, bash]
steps:
  - id: step-1
    agent: processor
    input: data
"""


class TestAgenticomYAMLValidator:
    """Test AgenticomYAMLValidator."""

    def test_valid_yaml(self):
        """Well-formed YAML with agents and steps should pass."""
        passed, reason = AgenticomYAMLValidator.validate(VALID_YAML)
        assert passed is True
        assert reason == "OK"

    def test_missing_agents_key(self):
        """YAML without agents key should fail."""
        passed, reason = AgenticomYAMLValidator.validate(MISSING_AGENTS_KEY)
        assert passed is False
        assert "agent" in reason.lower() or "field" in reason.lower()

    def test_missing_steps_key(self):
        """YAML without steps key should fail."""
        passed, reason = AgenticomYAMLValidator.validate(MISSING_STEPS_KEY)
        assert passed is False
        assert "step" in reason.lower() or "field" in reason.lower()

    def test_empty_agents(self):
        """YAML with empty agents list should fail."""
        passed, reason = AgenticomYAMLValidator.validate(EMPTY_AGENTS)
        assert passed is False
        assert "empty" in reason.lower()

    def test_empty_steps(self):
        """YAML with empty steps list should fail."""
        passed, reason = AgenticomYAMLValidator.validate(EMPTY_STEPS)
        assert passed is False
        assert "empty" in reason.lower()

    def test_unresolved_agent_ref(self):
        """Step referencing undefined agent should fail."""
        passed, reason = AgenticomYAMLValidator.validate(UNRESOLVED_AGENT_REF)
        assert passed is False
        assert "unknown" in reason.lower() or "agent" in reason.lower()

    def test_agent_missing_role(self):
        """Agent without role field should fail."""
        passed, reason = AgenticomYAMLValidator.validate(AGENT_MISSING_ROLE)
        assert passed is False
        assert "role" in reason.lower() or "field" in reason.lower()

    def test_agent_missing_prompt(self):
        """Agent without prompt field should fail."""
        passed, reason = AgenticomYAMLValidator.validate(AGENT_MISSING_PROMPT)
        assert passed is False
        assert "prompt" in reason.lower() or "field" in reason.lower()

    def test_step_missing_input(self):
        """Step without input field should fail."""
        passed, reason = AgenticomYAMLValidator.validate(STEP_MISSING_INPUT)
        assert passed is False
        assert "input" in reason.lower() or "field" in reason.lower()

    def test_invalid_yaml_syntax(self):
        """Malformed YAML should fail."""
        passed, reason = AgenticomYAMLValidator.validate(INVALID_YAML_SYNTAX)
        assert passed is False
        assert "yaml" in reason.lower() or "syntax" in reason.lower()

    def test_multiple_agents_and_steps(self):
        """Complex valid YAML with multiple agents and steps should pass."""
        passed, reason = AgenticomYAMLValidator.validate(COMPLEX_VALID_YAML)
        assert passed is True
        assert reason == "OK"

    def test_step_with_on_failure(self):
        """Step with optional on_failure field should pass."""
        passed, reason = AgenticomYAMLValidator.validate(STEP_WITH_ON_FAILURE)
        assert passed is True
        assert reason == "OK"

    def test_agent_with_tools(self):
        """Agent with optional tools list should pass."""
        passed, reason = AgenticomYAMLValidator.validate(AGENT_WITH_TOOLS)
        assert passed is True
        assert reason == "OK"

    def test_none_yaml(self):
        """None input should return success with no-op message."""
        passed, reason = AgenticomYAMLValidator.validate(None)
        assert passed is True
        assert "no yaml" in reason.lower()

    def test_empty_yaml(self):
        """Empty string should return success with no-op message."""
        passed, reason = AgenticomYAMLValidator.validate("")
        assert passed is True
        assert "no yaml" in reason.lower()

    def test_minimal_valid_yaml(self):
        """Minimal valid YAML should pass."""
        passed, reason = AgenticomYAMLValidator.validate(MINIMAL_VALID_YAML)
        assert passed is True
        assert reason == "OK"
