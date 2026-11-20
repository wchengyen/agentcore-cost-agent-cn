#!/usr/bin/env python3
"""Confirm Runtime READY state and recent CloudWatch log events."""
from __future__ import annotations

import json
import time

import boto3

REGION = "cn-north-1"
session = boto3.Session(profile_name="default", region_name=REGION)
cp = session.client("bedrock-agentcore-control", endpoint_url="https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn")
runtimes = cp.list_agent_runtimes(maxResults=100).get("agentRuntimes", [])
runtime = next((item for item in runtimes if item.get("agentRuntimeName") == "costagent"), None)
if not runtime:
    raise RuntimeError("costagent Runtime not found")
detail = cp.get_agent_runtime(agentRuntimeId=runtime["agentRuntimeId"])
if detail["status"] != "READY":
    raise RuntimeError(f"Runtime state is {detail['status']}: {detail.get('statusReasons')}")
logs = session.client("logs")
groups = logs.describe_log_groups(logGroupNamePrefix="/aws/bedrock-agentcore/runtimes/").get("logGroups", [])
matching = [g["logGroupName"] for g in groups if "costagent" in g["logGroupName"]]
events = 0
for group in matching:
    events += len(logs.filter_log_events(logGroupName=group, startTime=int((time.time() - 3600) * 1000), limit=100).get("events", []))
if not matching or not events:
    raise RuntimeError("no recent costagent CloudWatch logs found")
print(json.dumps({"runtime_arn": runtime["agentRuntimeArn"], "status": detail["status"], "log_groups": matching, "recent_events": events}, indent=2))
