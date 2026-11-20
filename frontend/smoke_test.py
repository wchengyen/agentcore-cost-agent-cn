#!/usr/bin/env python3
"""Programmatic quick-prompt smoke tests through the frontend backend."""
from __future__ import annotations

import json
import uuid

from backend import FrontendError, RuntimeClient

PROMPTS = {
    "forecast": "分析本月至今成本，並提供本月剩餘期間與整月成本預測。",
    "ri_sp": "分析上個完整月的 RI 與 Savings Plans 覆蓋率及使用率。",
    "anomalies": "查詢最近 30 天成本異常，只報告工具證實的異常。",
}

client = RuntimeClient()
results = {}
for name, prompt in PROMPTS.items():
    session_id = f"ui-smoke-{name}-{uuid.uuid4().hex}"
    try:
        response = client.invoke(prompt, session_id)
        results[name] = {
            "ok": True,
            "session_id": session_id,
            "latency_seconds": response.get("latency_seconds"),
            "tool_calls": response.get("tool_calls", {}),
            "models_returned": response.get("models_returned", []),
            "result_preview": response.get("result", "")[:300],
        }
    except FrontendError as exc:
        results[name] = {"ok": False, "session_id": session_id, "error": str(exc)}
print(json.dumps(results, ensure_ascii=False, indent=2))
