#!/usr/bin/env python3
"""Summarize P3 Runtime logs without emitting prompts, responses, or secrets."""
from __future__ import annotations

import json
import time
from pathlib import Path

import boto3

config = json.loads((Path(__file__).resolve().parent / "resource_config.json").read_text(encoding="utf-8"))
client = boto3.Session(profile_name="default", region_name="cn-north-1").client("logs")
response = client.filter_log_events(
    logGroupName=config["runtime_log_group"],
    startTime=int((time.time() - 7200) * 1000),
    limit=1000,
)
tool_records = []
error_types = []
for event in response.get("events", []):
    message = event["message"]
    marker = '{"event":"tool_call"'
    index = message.find(marker)
    if index >= 0:
        tail = message[index:]
        end = tail.find("}\n")
        raw = tail[:end + 1] if end >= 0 else tail.strip()
        try:
            record = json.loads(raw)
            tool_records.append({key: record.get(key) for key in ("tool", "duration_ms", "ok")})
        except json.JSONDecodeError:
            pass
    if "Traceback (most recent call last)" in message or '"level":"ERROR"' in message:
        error_types.append("runtime_error_event")
print(json.dumps({
    "log_group": config["runtime_log_group"],
    "events_scanned": len(response.get("events", [])),
    "structured_runtime_tool_logs": tool_records,
    "error_event_count": len(error_types),
}, indent=2))
