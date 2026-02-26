"""Configuration management for WorkflowX.

Loads settings from environment variables and .env file.
No cloud. No telemetry. Everything local.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class WorkflowXConfig(BaseModel):
    """Application configuration — all from env vars or defaults."""

    # Capture
    screenpipe_db_path: str = Field(
        default_factory=lambda: os.getenv(
            "WORKFLOWX_SCREENPIPE_DB",
            str(Path.home() / ".screenpipe" / "db.sqlite"),
        )
    )
    activitywatch_host: str = Field(
        default_factory=lambda: os.getenv("WORKFLOWX_AW_HOST", "http://localhost:5600")
    )

    # Inference
    llm_provider: Literal["anthropic", "openai", "ollama"] = Field(
        default_factory=lambda: os.getenv("WORKFLOWX_LLM_PROVIDER", "anthropic")  # type: ignore[arg-type]
    )
    llm_model: str = Field(
        default_factory=lambda: os.getenv("WORKFLOWX_LLM_MODEL", "claude-sonnet-4-6")
    )
    anthropic_api_key: str = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    openai_api_key: str = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )

    # Session clustering
    session_gap_minutes: float = Field(
        default_factory=lambda: float(os.getenv("WORKFLOWX_GAP_MINUTES", "5"))
    )
    min_session_events: int = Field(
        default_factory=lambda: int(os.getenv("WORKFLOWX_MIN_EVENTS", "2"))
    )

    # Cost
    hourly_rate_usd: float = Field(
        default_factory=lambda: float(os.getenv("WORKFLOWX_HOURLY_RATE", "75"))
    )

    # Storage
    data_dir: str = Field(
        default_factory=lambda: os.getenv(
            "WORKFLOWX_DATA_DIR",
            str(Path.home() / ".workflowx"),
        )
    )

    def get_llm_client(self):
        """Create the appropriate LLM client based on config."""
        if self.llm_provider == "anthropic":
            try:
                import anthropic
                return anthropic.AsyncAnthropic(api_key=self.anthropic_api_key)
            except ImportError:
                raise RuntimeError("pip install anthropic  (or: pip install workflowx[inference])")

        elif self.llm_provider == "openai":
            try:
                import openai
                return openai.AsyncOpenAI(api_key=self.openai_api_key)
            except ImportError:
                raise RuntimeError("pip install openai  (or: pip install workflowx[inference])")

        elif self.llm_provider == "ollama":
            try:
                import openai
                return openai.AsyncOpenAI(
                    base_url=f"{self.ollama_base_url}/v1",
                    api_key="ollama",
                )
            except ImportError:
                raise RuntimeError("pip install openai  (or: pip install workflowx[inference])")

        raise ValueError(f"Unknown LLM provider: {self.llm_provider}")

    def ensure_data_dir(self) -> Path:
        """Create data directory if it doesn't exist."""
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_config() -> WorkflowXConfig:
    """Load configuration from environment."""
    return WorkflowXConfig()
