#!/usr/bin/env python3
"""Summarize structured Lambda tool logs without printing tool inputs or secrets."""
from __future__ import annotations

import json
import time

import boto3

client = boto3.Session(profile_name="default", region_name="cn-north-1").client("logs")
response = client.filter_log_events(
    logGroupName="/aws/lambda/cost-agent-tools",
    startTime=int((time.time() - 7200) * 1000),
    limit=1000,
)
records = []
marker = '{"event":"tool_call"'
for event in response.get("events", []):
    message = event["message"]
    start = message.find(marker)
    if start < 0:
        continue
    try:
        records.append(json.loads(message[start:].strip()))
    except json.JSONDecodeError:
        continue
print(json.dumps({"structured_tool_log_count": len(records), "recent": records[-10:]}, indent=2))
if not records:
    raise SystemExit("no structured tool logs found")
