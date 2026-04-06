"""Tests for configuration management."""

import os
from unittest.mock import patch

from workflowx.config import WorkflowXConfig, load_config


def test_default_config():
    config = WorkflowXConfig()
    assert config.llm_provider in ("anthropic", "openai", "ollama")
    assert config.session_gap_minutes == 5.0
    assert config.min_session_events == 2
    assert config.hourly_rate_usd == 75.0


def test_config_from_env():
    env = {
        "WORKFLOWX_LLM_PROVIDER": "openai",
        "WORKFLOWX_LLM_MODEL": "gpt-4o",
        "WORKFLOWX_GAP_MINUTES": "10",
        "WORKFLOWX_HOURLY_RATE": "150",
        "OPENAI_API_KEY": "sk-test",
    }
    with patch.dict(os.environ, env, clear=False):
        config = load_config()
        assert config.llm_provider == "openai"
        assert config.llm_model == "gpt-4o"
        assert config.session_gap_minutes == 10.0
        assert config.hourly_rate_usd == 150.0
        assert config.openai_api_key == "sk-test"


def test_ensure_data_dir(tmp_path):
    config = WorkflowXConfig(data_dir=str(tmp_path / "test_workflowx"))
    p = config.ensure_data_dir()
    assert p.exists()
    assert p.is_dir()
