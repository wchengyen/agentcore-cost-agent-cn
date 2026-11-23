"""Deterministic local conversation history for the Streamlit frontend."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HISTORY_PATH = Path(__file__).resolve().parent / ".history" / "sessions.json"
_LOCK = threading.Lock()
_CURRENCY = re.compile(r"(?:CNY\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*CNY)", re.I)
_PERCENT = re.compile(r"[+\-−]?\d+(?:\.\d+)?%")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_title(prompt: str, max_chars: int = 20) -> str:
    """Create a one-line title of at most max_chars Unicode characters."""
    title = re.sub(r"\s+", " ", prompt).strip().strip("。！？!?.,，") or "新對話"
    return title if len(title) <= max_chars else title[: max_chars - 1] + "…"


def _clean_line(line: str, max_chars: int = 96) -> str:
    line = line.strip()
    if line.startswith("|") and line.endswith("|"):
        cells = [cell.strip().strip("*`") for cell in line.strip("|").split("|")]
        line = " · ".join(cell for cell in cells if cell and not set(cell) <= {"-", ":"})
    line = re.sub(r"^[#>*\-\s]+", "", line)
    line = line.replace("**", "").replace("`", "")
    line = re.sub(r"\s+", " ", line).strip()
    return line if len(line) <= max_chars else line[: max_chars - 1] + "…"


def extract_key_facts(answer: str, limit: int = 2) -> list[str]:
    """Extract verbatim currency/percentage facts without adding interpretation."""
    facts: list[str] = []
    lines = answer.splitlines()
    for line in lines:
        if _CURRENCY.search(line) or _PERCENT.search(line):
            cleaned = _clean_line(line)
            if cleaned and cleaned not in facts:
                facts.append(cleaned)
        if len(facts) >= limit:
            return facts
    # Fall back to the first numeric Markdown table row.
    for line in lines:
        if line.strip().startswith("|") and re.search(r"\d", line):
            cleaned = _clean_line(line)
            if cleaned:
                facts.append(cleaned)
                break
    return facts[:limit]


def deterministic_summary(prompt: str, answer: str) -> dict[str, Any]:
    return {"title": make_title(prompt), "facts": extract_key_facts(answer)}


def empty_history() -> dict[str, Any]:
    return {"version": 1, "sessions": {}}


class HistoryStore:
    def __init__(self, path: str | Path = HISTORY_PATH) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_history()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data.get("sessions"), dict):
                raise ValueError("sessions must be an object")
            return data
        except (json.JSONDecodeError, OSError, ValueError):
            return empty_history()

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        with _LOCK:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(self.path)

    def ensure_session(self, session_id: str, model: str | None = None) -> dict[str, Any]:
        data = self.load()
        session = data["sessions"].get(session_id)
        if session is None:
            now = _now()
            session = {
                "session_id": session_id,
                "created_at": now,
                "updated_at": now,
                "turns": [],
                "summary": {"title": "新對話", "facts": []},
                "model": model,
            }
            data["sessions"][session_id] = session
            self.save(data)
        return session

    def append_turn(
        self,
        session_id: str,
        prompt: str,
        answer: str,
        latency: float,
        tool_counts: dict[str, int],
        model: str | None,
    ) -> dict[str, Any]:
        data = self.load()
        if session_id not in data["sessions"]:
            self.ensure_session(session_id, model)
            data = self.load()
        session = data["sessions"][session_id]
        session["turns"].append({
            "prompt": prompt,
            "answer": answer,
            "latency": latency,
            "tool_counts": tool_counts,
            "model": model,
            "created_at": _now(),
        })
        session["updated_at"] = _now()
        session["model"] = model or session.get("model")
        if not session.get("title_override"):
            session["summary"] = deterministic_summary(session["turns"][0]["prompt"], answer)
        else:
            session["summary"]["facts"] = extract_key_facts(answer)
        self.save(data)
        return session

    def rename(self, session_id: str, title: str) -> None:
        data = self.load()
        session = data["sessions"][session_id]
        clean = make_title(title)
        session["title_override"] = clean
        session["summary"]["title"] = clean
        session["updated_at"] = _now()
        self.save(data)

    def delete(self, session_id: str) -> None:
        data = self.load()
        data["sessions"].pop(session_id, None)
        self.save(data)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = list(self.load()["sessions"].values())
        return sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)
