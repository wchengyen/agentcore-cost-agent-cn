"""Provider-agnostic S3 session persistence without reasoning traces."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from strands.session.s3_session_manager import S3SessionManager
from strands.types.session import SessionMessage

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_REASONING_KEYS = {"reasoningContent", "reasoning_content", "reasoning"}


def _sanitize_blocks(blocks: list[Any]) -> list[Any]:
    clean_blocks = []
    for block in blocks:
        if not isinstance(block, dict):
            clean_blocks.append(block)
            continue
        if any(key in block for key in _REASONING_KEYS):
            continue
        clean_block = deepcopy(block)
        if isinstance(clean_block.get("text"), str):
            clean_block["text"] = _THINK_BLOCK.sub("", clean_block["text"]).strip()
            if not clean_block["text"]:
                continue
        clean_blocks.append(clean_block)
    return clean_blocks


def _without_reasoning(message: SessionMessage | None) -> SessionMessage | None:
    if message is None:
        return None
    clean = deepcopy(message)
    for attribute in ("message", "redact_message"):
        value = getattr(clean, attribute, None)
        if isinstance(value, dict) and isinstance(value.get("content"), list):
            value["content"] = _sanitize_blocks(value["content"])
    return clean


class ReasoningSafeS3SessionManager(S3SessionManager):
    """Persist and replay text/tool history without provider reasoning traces."""

    def create_message(self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs) -> None:
        clean = _without_reasoning(session_message)
        assert clean is not None
        super().create_message(session_id, agent_id, clean, **kwargs)

    def read_message(self, session_id: str, agent_id: str, message_id: int, **kwargs) -> SessionMessage | None:
        return _without_reasoning(super().read_message(session_id, agent_id, message_id, **kwargs))

    def update_message(self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs) -> None:
        clean = _without_reasoning(session_message)
        assert clean is not None
        super().update_message(session_id, agent_id, clean, **kwargs)


# Backward-compatible import for existing local integrations.
KimiSafeS3SessionManager = ReasoningSafeS3SessionManager
