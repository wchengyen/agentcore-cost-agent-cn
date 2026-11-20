#!/usr/bin/env python3
"""Delete project AWS resources. Dry-run by default; never run implicitly."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent
REGION = "cn-north-1"
CP_ENDPOINT = "https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn"


def ignore_not_found(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {
            "ResourceNotFoundException", "NoSuchEntity", "NoSuchBucket", "ResourceNotFound", "404"
        }:
            return None
        raise


def empty_bucket(s3, bucket: str) -> None:
    try:
        paginator = s3.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket):
            objects = [
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for key in ("Versions", "DeleteMarkers") for item in page.get(key, [])
            ]
            for offset in range(0, len(objects), 1000):
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objects[offset:offset + 1000], "Quiet": True})
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            for offset in range(0, len(objects), 1000):
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objects[offset:offset + 1000], "Quiet": True})
        s3.delete_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"NoSuchBucket", "404"}:
            raise


def delete_role(iam, name: str) -> None:
    try:
        for policy in iam.list_role_policies(RoleName=name).get("PolicyNames", []):
            iam.delete_role_policy(RoleName=name, PolicyName=policy)
        for policy in iam.list_attached_role_policies(RoleName=name).get("AttachedPolicies", []):
            iam.detach_role_policy(RoleName=name, PolicyArn=policy["PolicyArn"])
        iam.delete_role(RoleName=name)
    except iam.exceptions.NoSuchEntityException:
        pass


def plan(config: dict, delete_secret: bool) -> dict:
    return {
        "runtime": config.get("runtime_arn", "costagent"),
        "runtime_execution_role": config.get("runtime_role_arn"),
        "deployment_bucket": config.get("deployment_bucket"),
        "session_bucket": config.get("session_bucket"),
        "dynamodb_tables": [config.get("cache_table"), config.get("knowledge_table")],
        "gateway": config.get("gateway_arn"),
        "gateway_target": config.get("target_id"),
        "lambda": config.get("lambda_arn"),
        "iam_roles": [config.get("runtime_role_name"), config.get("gateway_role_name"), config.get("lambda_role_name")],
        "log_group_prefixes": ["/aws/bedrock-agentcore/runtimes/costagent", "/aws/lambda/cost-agent-tools"],
        "secret": config.get("llm_secret_arn") if delete_secret else "preserved (use --delete-secret to remove)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List resources without deleting them")
    parser.add_argument("--delete-secret", action="store_true", help="Also permanently delete cost-agent/llm-api-key")
    parser.add_argument("--confirm", help="Must be exactly DELETE for destructive execution")
    args = parser.parse_args()
    config = json.loads((ROOT / "resource_config.json").read_text(encoding="utf-8"))
    print(json.dumps(plan(config, args.delete_secret), indent=2))
    if args.dry_run or args.confirm != "DELETE":
        if not args.dry_run:
            print("No changes made. Use --dry-run to inspect or --confirm DELETE to execute.")
        return 0 if args.dry_run else 2

    session = boto3.Session(profile_name="default", region_name=REGION)
    cp = session.client("bedrock-agentcore-control", endpoint_url=CP_ENDPOINT)
    lam = session.client("lambda")
    ddb = session.client("dynamodb")
    s3 = session.client("s3")
    iam = session.client("iam")
    logs = session.client("logs")
    secrets = session.client("secretsmanager")

    # Runtime endpoint first, then every deployed Runtime version.
    runtimes = cp.list_agent_runtimes(maxResults=100).get("agentRuntimes", [])
    for runtime in [item for item in runtimes if item.get("agentRuntimeName") == "costagent"]:
        runtime_id = runtime["agentRuntimeId"]
        endpoints = cp.list_agent_runtime_endpoints(agentRuntimeId=runtime_id, maxResults=100).get("runtimeEndpoints", [])
        for endpoint in endpoints:
            ignore_not_found(cp.delete_agent_runtime_endpoint, agentRuntimeId=runtime_id, endpointName=endpoint["name"])
        for _ in range(60):
            if not cp.list_agent_runtime_endpoints(agentRuntimeId=runtime_id, maxResults=100).get("runtimeEndpoints", []):
                break
            time.sleep(5)
        versions = cp.list_agent_runtime_versions(agentRuntimeId=runtime_id, maxResults=100).get("agentRuntimes", [])
        for version in sorted(versions, key=lambda item: int(item["agentRuntimeVersion"]), reverse=True):
            ignore_not_found(
                cp.delete_agent_runtime,
                agentRuntimeId=runtime_id,
                agentRuntimeVersion=version["agentRuntimeVersion"],
            )

    # Gateway target before Gateway.
    gateway_id = config.get("gateway_id")
    if gateway_id:
        try:
            targets = cp.list_gateway_targets(gatewayIdentifier=gateway_id, maxResults=100).get("items", [])
            for target in targets:
                cp.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=target["targetId"])
            for _ in range(60):
                if not cp.list_gateway_targets(gatewayIdentifier=gateway_id, maxResults=100).get("items", []):
                    break
                time.sleep(5)
            ignore_not_found(cp.delete_gateway, gatewayIdentifier=gateway_id)
        except cp.exceptions.ResourceNotFoundException:
            pass

    ignore_not_found(lam.delete_function, FunctionName=config.get("lambda_name", "cost-agent-tools"))
    for table in (config.get("cache_table", "cost-agent-ce-cache"), config.get("knowledge_table", "cost-agent-knowledge")):
        ignore_not_found(ddb.delete_table, TableName=table)
    for bucket in (config.get("session_bucket"), config.get("deployment_bucket")):
        if bucket:
            empty_bucket(s3, bucket)

    for role in (
        config.get("runtime_role_name", "CostAgentRuntimeRole"),
        config.get("gateway_role_name", "CostAgentGatewayRole"),
        config.get("lambda_role_name", "CostAgentToolsLambdaRole"),
    ):
        delete_role(iam, role)

    if args.delete_secret:
        try:
            secrets.delete_secret(
                SecretId=config.get("llm_secret_name", "cost-agent/llm-api-key"),
                ForceDeleteWithoutRecovery=True,
            )
        except secrets.exceptions.ResourceNotFoundException:
            pass

    for prefix in ("/aws/lambda/cost-agent-tools", "/aws/bedrock-agentcore/runtimes/costagent"):
        for group in logs.describe_log_groups(logGroupNamePrefix=prefix).get("logGroups", []):
            logs.delete_log_group(logGroupName=group["logGroupName"])

    print("Project resources were submitted for deletion. Some services delete asynchronously.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
