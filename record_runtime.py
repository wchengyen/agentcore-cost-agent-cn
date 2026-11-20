#!/usr/bin/env python3
"""Record the deployed Runtime identifiers in resource_config.json."""
from __future__ import annotations

import json
from pathlib import Path

import boto3

path = Path(__file__).resolve().parent / "resource_config.json"
config = json.loads(path.read_text(encoding="utf-8"))
client = boto3.Session(profile_name="default", region_name="cn-north-1").client(
    "bedrock-agentcore-control",
    endpoint_url="https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn",
)
runtime = next(
    item for item in client.list_agent_runtimes(maxResults=100)["agentRuntimes"]
    if item["agentRuntimeName"] == "costagent"
)
config.update({
    "runtime_name": "costagent",
    "runtime_id": runtime["agentRuntimeId"],
    "runtime_arn": runtime["agentRuntimeArn"],
    "runtime_version": runtime["agentRuntimeVersion"],
    "runtime_log_group": f"/aws/bedrock-agentcore/runtimes/{runtime['agentRuntimeId']}-DEFAULT",
})
path.write_text(json.dumps(config, indent=2), encoding="utf-8")
print(json.dumps({key: config[key] for key in ("runtime_id", "runtime_arn", "runtime_version", "runtime_log_group")}, indent=2))
