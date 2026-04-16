from __future__ import annotations
from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).parent.parent
_AGENT_YAML = _ROOT / "config" / "agent.yaml"


def _load_yaml() -> dict[str, Any]:
    if _AGENT_YAML.exists():
        with _AGENT_YAML.open() as f:
            return yaml.safe_load(f) or {}
    return {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- secrets (from .env) ---
    openai_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    tavily_api_key: str = ""

    # --- agent config (from agent.yaml, overridable via env) ---
    model: str = "openai/gpt-4o-mini"
    system_prompt: str = "You are a helpful assistant."
    temperature: float = 0.7
    max_tool_iters: int = 10

    # --- app config ---
    debug: bool = False  # when True, skips Twilio signature validation
    db_path: str = str(_ROOT / "sessions.db")

    # --- memory config ---
    working_memory_size: int = 10
    long_term_memory_enabled: bool = True
    extraction_model: str = "anthropic/claude-haiku-4-5-20251001"
    memory_context_token_budget: int = 1500
    vector_db_path: str = str(_ROOT / "memory" / "qdrant")
    subject_wal_threshold: int = 5
    subject_vocabulary_k: int = 10
    subject_collection: str = "tamashi_subjects"
    allowed_relation_kinds: list = [
        "is_a", "has_a", "part_of",
        "enjoys", "avoids", "wants",
        "knows", "located_in", "works_at",
        "causes", "opposite_of",
        "related_to", "mentions",
    ]

    def model_post_init(self, __context: Any) -> None:
        yaml_data = _load_yaml()
        for key, val in yaml_data.items():
            if key in self.model_fields and val is not None:
                object.__setattr__(self, key, val)


settings = Settings()
