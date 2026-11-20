#!/usr/bin/env python3
"""Run CloudWatch Logs Insights summaries for final P3 invocations."""
from __future__ import annotations

import json
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent
config = json.loads((ROOT / "resource_config.json").read_text(encoding="utf-8"))
logs = boto3.Session(profile_name="default", region_name="cn-north-1").client("logs")
start = int(time.time()) - 30 * 60
end = int(time.time())


def query(group: str, query_string: str) -> list[dict[str, str]]:
    query_id = logs.start_query(
        logGroupName=group,
        startTime=start,
        endTime=end,
        queryString=query_string,
        limit=100,
    )["queryId"]
    for _ in range(60):
        response = logs.get_query_results(queryId=query_id)
        if response["status"] == "Complete":
            return [{field["field"]: field["value"] for field in row} for row in response["results"]]
        if response["status"] in {"Failed", "Cancelled", "Timeout"}:
            raise RuntimeError(f"Logs Insights query {response['status']}")
        time.sleep(2)
    raise TimeoutError("Logs Insights query did not complete")


by_tool = """
fields @message
| filter @message like /\"event\":\"tool_call\"/
| parse @message /\"tool\":\"(?<tool>[^\"]+)\"/
| stats count(*) as calls by tool
| sort calls desc
"""
runtime_events = """
fields @message
| stats count(*) as events
"""
runtime_errors = """
fields @message
| filter @message like /Traceback/ or @message like /\"level\":\"ERROR\"/
| stats count(*) as errors
"""
summary = {
    "window_minutes": 30,
    "runtime_log_group": config["runtime_log_group"],
    "runtime_events": query(config["runtime_log_group"], runtime_events),
    "runtime_errors": query(config["runtime_log_group"], runtime_errors),
    "runtime_tool_calls": query(config["runtime_log_group"], by_tool),
    "lambda_log_group": "/aws/lambda/cost-agent-tools",
    "lambda_tool_calls": query("/aws/lambda/cost-agent-tools", by_tool),
}
print(json.dumps(summary, indent=2))
