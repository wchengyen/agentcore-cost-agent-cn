#!/usr/bin/env python3
"""Verify P1 resources, MCP discovery, and six-hour CE cache behavior."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import boto3
from strands.tools.mcp.mcp_client import MCPClient

from agent.sigv4 import FreshSigV4Auth

ROOT = Path(__file__).resolve().parent
REGION = "cn-north-1"
config = json.loads((ROOT / "resource_config.json").read_text(encoding="utf-8"))
session = boto3.Session(profile_name="default", region_name=REGION)

lam = session.client("lambda")
status = lam.get_function(FunctionName=config["lambda_name"])["Configuration"]["State"]
if status != "Active":
    raise RuntimeError(f"Lambda state is {status}")

end = date.today().replace(day=1)
start = (end - timedelta(days=1)).replace(day=1)
payload = {"tool": "get_cost", "start": start.isoformat(), "end": end.isoformat(),
           "granularity": "MONTHLY", "group_by": "SERVICE", "top_n": 5}

def invoke() -> dict:
    response = lam.invoke(FunctionName=config["lambda_name"], InvocationType="RequestResponse",
                          Payload=json.dumps(payload).encode("utf-8"))
    raw = response["Payload"].read()
    body = json.loads(raw)
    if response.get("FunctionError"):
        raise RuntimeError(json.dumps(body, ensure_ascii=False))
    return body

first = invoke()
second = invoke()
if not second.get("cache_hit"):
    raise AssertionError("second identical CE request was not a cache hit")

mcp = MCPClient(url=config["gateway_url"], auth_provider=FreshSigV4Auth(REGION), startup_timeout=60)
with mcp:
    tools = list(mcp.list_tools_sync())
names = [tool.tool_name for tool in tools]
expected_suffixes = {"get_cost", "compare_periods", "get_forecast", "get_ri_sp_coverage_utilization",
                     "get_anomalies", "get_dimension_values", "get_price", "recall_context", "save_finding"}
missing = sorted(name for name in expected_suffixes if not any(tool.endswith(name) for tool in names))
if missing:
    raise AssertionError(f"missing Gateway tools: {missing}")
print(json.dumps({
    "lambda_state": status,
    "tools": names,
    "first_cache_hit": first.get("cache_hit"),
    "second_cache_hit": second.get("cache_hit"),
    "period_total_cny": second.get("total"),
}, ensure_ascii=False, indent=2))
