"""Shared provider-agnostic LLM configuration and result helpers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.verified_openai import VerifiedOpenAIModel

DEFAULT_MODEL = "glm-5.3-flash"
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
DEFAULT_MAX_TOKENS = 8192


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


def _optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return float(raw)


def make_model(api_key: str | None = None) -> VerifiedOpenAIModel:
    params: dict[str, Any] = {
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
    }
    temperature = _optional_float("LLM_TEMPERATURE")
    if temperature is not None:
        params["temperature"] = temperature
    reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "").strip().lower()
    if reasoning_effort:
        if reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("LLM_REASONING_EFFORT must be unset, low, high, or max")
        params["reasoning_effort"] = reasoning_effort
    return VerifiedOpenAIModel(
        client_args={
            "api_key": api_key or require_api_key(),
            "base_url": os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
        },
        model_id=os.getenv("LLM_MODEL", DEFAULT_MODEL),
        params=params,
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
