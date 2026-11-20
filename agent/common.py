"""Shared configuration and result helpers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.verified_openai import VerifiedOpenAIModel

DEFAULT_MODEL = "k3.1-pro"
DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"


def load_dotenv(path: str | Path = ".env") -> None:
    path = Path(path)
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_api_key() -> str:
    key = os.getenv("LLM_API_KEY")
    if not key:
        raise RuntimeError("LLM_API_KEY is not set; create the user-owned .env file")
    return key


def make_model(api_key: str | None = None) -> VerifiedOpenAIModel:
    reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "low").lower()
    if reasoning_effort not in {"low", "high", "max"}:
        raise ValueError("LLM_REASONING_EFFORT must be low, high, or max")
    return VerifiedOpenAIModel(
        client_args={
            "api_key": api_key or require_api_key(),
            "base_url": os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
        },
        model_id=os.getenv("LLM_MODEL", DEFAULT_MODEL),
        params={
            "temperature": 1,
            "max_tokens": 8192,
            "reasoning_effort": reasoning_effort,
        },
    )


def message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        return "\n".join(
            block.get("text", "") for block in message.get("content", [])
            if isinstance(block, dict) and block.get("text")
        )
    return str(message)
