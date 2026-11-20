#!/usr/bin/env python3
"""Read-only inventory of Cost Analysis Agent resources; never reads secret values."""
from __future__ import annotations

import json
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent
config = json.loads((ROOT / "resource_config.json").read_text(encoding="utf-8"))
session = boto3.Session(profile_name="default", region_name="cn-north-1")
cp = session.client("bedrock-agentcore-control", endpoint_url="https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn")
iam = session.client("iam")
lam = session.client("lambda")
ddb = session.client("dynamodb")
s3 = session.client("s3")
secrets = session.client("secretsmanager")

runtime = cp.get_agent_runtime(agentRuntimeId=config["runtime_id"])
gateway = cp.get_gateway(gatewayIdentifier=config["gateway_id"])
target = cp.get_gateway_target(gatewayIdentifier=config["gateway_id"], targetId=config["target_id"])
secret = secrets.describe_secret(SecretId=config["llm_secret_name"])
inventory = {
    "runtime": {"arn": runtime["agentRuntimeArn"], "status": runtime["status"], "version": runtime["agentRuntimeVersion"]},
    "runtime_role": iam.get_role(RoleName=config["runtime_role_name"])["Role"]["Arn"],
    "gateway": {"arn": gateway["gatewayArn"], "status": gateway["status"], "url": gateway["gatewayUrl"]},
    "gateway_target": {"id": target["targetId"], "status": target["status"]},
    "gateway_role": iam.get_role(RoleName=config["gateway_role_name"])["Role"]["Arn"],
    "lambda": {"arn": lam.get_function(FunctionName=config["lambda_name"])["Configuration"]["FunctionArn"],
               "state": lam.get_function(FunctionName=config["lambda_name"])["Configuration"]["State"]},
    "lambda_role": iam.get_role(RoleName=config["lambda_role_name"])["Role"]["Arn"],
    "dynamodb": {name: ddb.describe_table(TableName=name)["Table"]["TableStatus"]
                 for name in (config["cache_table"], config["knowledge_table"])},
    "s3": {bucket: s3.get_bucket_location(Bucket=bucket).get("LocationConstraint")
           for bucket in (config["session_bucket"], config["deployment_bucket"])},
    "secret": {"name": config["llm_secret_name"], "arn": secret["ARN"]},
    "runtime_log_group": config["runtime_log_group"],
    "lambda_log_group": "/aws/lambda/cost-agent-tools",
}
print(json.dumps(inventory, indent=2))
