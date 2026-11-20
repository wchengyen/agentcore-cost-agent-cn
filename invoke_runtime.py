#!/usr/bin/env python3
"""Invoke the deployed Runtime using boto3 without exposing credentials."""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import boto3

REGION = "cn-north-1"
ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="上個月成本 Top 5 服務及環比")
    parser.add_argument("--session-id", default=f"sdk-{uuid.uuid4().hex}")
    args = parser.parse_args()
    session = boto3.Session(profile_name="default", region_name=REGION)
    cp = session.client("bedrock-agentcore-control", endpoint_url="https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn")
    runtimes = cp.list_agent_runtimes(maxResults=100).get("agentRuntimes", [])
    runtime = next((item for item in runtimes if item.get("agentRuntimeName") == "costagent"), None)
    if not runtime:
        raise RuntimeError("costagent Runtime was not found")
    runtime_arn = runtime["agentRuntimeArn"]
    client = session.client("bedrock-agentcore", endpoint_url="https://bedrock-agentcore.cn-north-1.amazonaws.com.cn")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=args.session_id,
        qualifier="DEFAULT",
        payload=json.dumps({"prompt": args.prompt, "session_id": args.session_id}).encode("utf-8"),
    )
    body = bytearray()
    text_parts = []
    for chunk in response.get("response", []):
        if isinstance(chunk, bytes):
            body.extend(chunk)
        else:
            text_parts.append(str(chunk))
    response_text = body.decode("utf-8") + "".join(text_parts)
    print(json.dumps({"runtime_arn": runtime_arn, "response": json.loads(response_text)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
