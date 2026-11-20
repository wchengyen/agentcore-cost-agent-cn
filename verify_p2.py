#!/usr/bin/env python3
"""Demonstrate S3 multi-turn continuity and DynamoDB cross-session recall."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

from agent.common import load_dotenv, require_api_key
from agent.gateway_agent import invoke_gateway_agent

ROOT = Path(__file__).resolve().parent
REGION = "cn-north-1"
load_dotenv(ROOT / ".env")
config = json.loads((ROOT / "resource_config.json").read_text(encoding="utf-8"))
os.environ["GATEWAY_URL"] = config["gateway_url"]
os.environ["SESSION_BUCKET"] = config["session_bucket"]
api_key = require_api_key()
scope = f"account:{config['account_id']}"
session_one = "p2-" + uuid.uuid4().hex
session_two = "p2-" + uuid.uuid4().hex

first = invoke_gateway_agent("分析上個月成本 Top 5 服務及環比，保存最重要的已确认事实。", session_one, scope, api_key, True)
follow_up = invoke_gateway_agent("延续刚才的分析：最高成本服务是什么？只引用已有分析并说明口径。", session_one, scope, api_key, True)
cross_session = invoke_gateway_agent("这是新会话。先回忆之前保存的成本发现，再简要列出已确认事实。", session_two, scope, api_key, True)

s3 = boto3.Session(profile_name="default", region_name=REGION).client("s3")
objects = s3.list_objects_v2(Bucket=config["session_bucket"], Prefix=f"sessions/session_{session_one}/").get("Contents", [])
ddb = boto3.Session(profile_name="default", region_name=REGION).resource("dynamodb").Table(config["knowledge_table"])
findings = ddb.query(KeyConditionExpression=Key("scope").eq(scope), Limit=20).get("Items", [])
if not objects:
    raise AssertionError("no S3 session objects were written")
if not findings:
    raise AssertionError("no DynamoDB finding was saved")
print(json.dumps({
    "session_one": session_one,
    "session_two": session_two,
    "s3_object_count": len(objects),
    "knowledge_count": len(findings),
    "first": first["result"],
    "follow_up": follow_up["result"],
    "cross_session": cross_session["result"],
}, ensure_ascii=False, indent=2, default=str))
