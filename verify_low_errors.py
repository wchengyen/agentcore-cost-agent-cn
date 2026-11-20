#!/usr/bin/env python3
"""Summarize recent Runtime failures without prompts or secrets."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--session-id", action="append", default=[], help="Optional session ID filter; repeat as needed")
args = parser.parse_args()
config = json.loads((ROOT / "resource_config.json").read_text(encoding="utf-8"))
sessions = set(args.session_id)
logs = boto3.Session(profile_name="default", region_name="cn-north-1").client("logs")
response = logs.filter_log_events(
    logGroupName=config["runtime_log_group"],
    startTime=int((time.time() - 3600) * 1000),
    filterPattern="ERROR",
    limit=100,
)
errors = []
for event in response.get("events", []):
    try:
        record = json.loads(event["message"])
    except json.JSONDecodeError:
        continue
    if sessions and record.get("sessionId") not in sessions:
        continue
    errors.append({
        "timestamp": record.get("timestamp"),
        "session_id": record.get("sessionId"),
        "error_type": record.get("errorType"),
        "error_message": record.get("errorMessage"),
    })
print(json.dumps(errors, indent=2))
