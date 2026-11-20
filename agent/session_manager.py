"""Kimi-compatible S3 session persistence."""
from __future__ import annotations

from copy import deepcopy

from strands.session.s3_session_manager import S3SessionManager
from strands.types.session import SessionMessage


def _without_reasoning(message: SessionMessage | None) -> SessionMessage | None:
    if message is None:
        return None
    clean = deepcopy(message)
    for attribute in ("message", "redact_message"):
        value = getattr(clean, attribute, None)
        if isinstance(value, dict) and isinstance(value.get("content"), list):
            value["content"] = [
                block for block in value["content"]
                if not (isinstance(block, dict) and "reasoningContent" in block)
            ]
    return clean


class KimiSafeS3SessionManager(S3SessionManager):
    """Persist and replay messages without provider-specific reasoning blocks."""

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
