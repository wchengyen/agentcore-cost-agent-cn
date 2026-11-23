#!/usr/bin/env python3
"""Create P1 DynamoDB, Lambda, IAM, and AWS_IAM AgentCore Gateway resources."""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent
REGION = "cn-north-1"
CP_ENDPOINT = "https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn"
LAMBDA_NAME = "cost-agent-tools"
LAMBDA_ROLE = "CostAgentToolsLambdaRole"
GATEWAY_ROLE = "CostAgentGatewayRole"
GATEWAY_NAME = "CostAgentGateway"
TARGET_NAME = "CostAgentTools"
CACHE_TABLE = "cost-agent-ce-cache"
KNOWLEDGE_TABLE = "cost-agent-knowledge"
TAGS = [{"Key": "Project", "Value": "cost-analysis-agent"}]

session = boto3.Session(profile_name="default", region_name=REGION)
iam = session.client("iam")
ddb = session.client("dynamodb")
lam = session.client("lambda")
cp = session.client("bedrock-agentcore-control", endpoint_url=CP_ENDPOINT)
account_id = session.client("sts").get_caller_identity()["Account"]


def ensure_table(name: str, key_schema: list[dict[str, str]], attributes: list[dict[str, str]]) -> str:
    try:
        response = ddb.create_table(
            TableName=name,
            KeySchema=key_schema,
            AttributeDefinitions=attributes,
            BillingMode="PAY_PER_REQUEST",
            Tags=TAGS,
        )
        arn = response["TableDescription"]["TableArn"]
    except ddb.exceptions.ResourceInUseException:
        arn = ddb.describe_table(TableName=name)["Table"]["TableArn"]
    waiter = ddb.get_waiter("table_exists")
    waiter.wait(TableName=name, WaiterConfig={"Delay": 3, "MaxAttempts": 40})
    return arn


def ensure_role(name: str, service: str, policy_name: str, policy: dict[str, Any]) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"
    }]}
    try:
        role = iam.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Cost Analysis Agent managed role",
            Tags=TAGS,
        )["Role"]
        time.sleep(10)
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=name)["Role"]
        iam.update_assume_role_policy(RoleName=name, PolicyDocument=json.dumps(trust))
    iam.put_role_policy(RoleName=name, PolicyName=policy_name, PolicyDocument=json.dumps(policy))
    return role["Arn"]


def lambda_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / "lambda" / "lambda_function.py", "lambda_function.py")
    return buffer.getvalue()


def ensure_lambda(role_arn: str) -> str:
    environment = {"Variables": {
        "DEPLOYING_ACCOUNT_ID": account_id,
        "CACHE_TABLE": CACHE_TABLE,
        "KNOWLEDGE_TABLE": KNOWLEDGE_TABLE,
    }}
    package = lambda_zip()
    try:
        response = lam.create_function(
            FunctionName=LAMBDA_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": package},
            Description="Account-scoped AWS China cost analysis tools",
            Timeout=120,
            MemorySize=512,
            Environment=environment,
            Tags={"Project": "cost-analysis-agent"},
        )
    except lam.exceptions.ResourceConflictException:
        lam.update_function_code(FunctionName=LAMBDA_NAME, ZipFile=package, Publish=False)
        lam.get_waiter("function_updated_v2").wait(FunctionName=LAMBDA_NAME)
        response = lam.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Description="Account-scoped AWS China cost analysis tools",
            Timeout=120,
            MemorySize=512,
            Environment=environment,
        )
    lam.get_waiter("function_active_v2").wait(FunctionName=LAMBDA_NAME)
    return lam.get_function(FunctionName=LAMBDA_NAME)["Configuration"]["FunctionArn"]


def find_gateway() -> dict[str, Any] | None:
    token = None
    while True:
        args = {"maxResults": 100}
        if token:
            args["nextToken"] = token
        response = cp.list_gateways(**args)
        for item in response.get("items", []):
            if item.get("name") == GATEWAY_NAME:
                return item
        token = response.get("nextToken")
        if not token:
            return None


def wait_gateway(gateway_id: str) -> dict[str, Any]:
    for _ in range(60):
        gateway = cp.get_gateway(gatewayIdentifier=gateway_id)
        if gateway["status"] == "READY":
            return gateway
        if gateway["status"] in {"FAILED", "DELETING"}:
            raise RuntimeError(f"Gateway entered {gateway['status']}: {gateway.get('statusReasons')}")
        time.sleep(5)
    raise TimeoutError("Gateway did not become READY in 300 seconds")


def tool_schemas() -> list[dict[str, Any]]:
    date_props = {
        "start": {"type": "string", "description": "YYYY-MM-DD inclusive"},
        "end": {"type": "string", "description": "YYYY-MM-DD exclusive"},
    }
    return [
        {"name": "get_cost", "description": "本轮查询部署账号自身的成本 Top-N、Others 和总额；回答当前数字前必须调用；默认排除 Credit/Refund。",
         "inputSchema": {"type": "object", "properties": {
             **date_props,
             "granularity": {"type": "string", "description": "MONTHLY or DAILY; default MONTHLY"},
             "group_by": {"type": "string", "description": "SERVICE|USAGE_TYPE|REGION|LINKED_ACCOUNT|TAG:<key>"},
             "filter": {"type": "object", "description": "Optional Cost Explorer Expression"},
             "top_n": {"type": "integer", "description": "1 through 100; default 10"},
             "metric": {"type": "string", "description": "Cost metric; default UnblendedCost"},
         }, "required": ["start", "end"]}},
        {"name": "compare_periods", "description": "本轮以每日平均成本比较两个期间并列出主要变动；回答环比数字前必须调用本工具或本轮 get_cost 后用 run_python。",
         "inputSchema": {"type": "object", "properties": {
             "a_start": {"type": "string"}, "a_end": {"type": "string"},
             "b_start": {"type": "string"}, "b_end": {"type": "string"},
             "group_by": {"type": "string", "description": "Grouping dimension; default SERVICE"},
         }, "required": ["a_start", "a_end", "b_start", "b_end"]}},
        {"name": "get_forecast", "description": "本轮取得部署账号自身的 Cost Explorer 成本预测；过去的 start 会自动调整至当前 UTC 日期并在响应注明。",
         "inputSchema": {"type": "object", "properties": {**date_props,
             "granularity": {"type": "string", "description": "MONTHLY or DAILY; default MONTHLY"}},
             "required": ["start", "end"]}},
        {"name": "get_ri_sp_coverage_utilization", "description": "本轮取得 RI 与 Savings Plans 覆盖率及利用率；无适用数据时返回 unavailable 而非工具错误。",
         "inputSchema": {"type": "object", "properties": date_props, "required": ["start", "end"]}},
        {"name": "get_anomalies", "description": "本轮取得仅归属于部署账号的成本异常；回答当前异常数字前必须调用。",
         "inputSchema": {"type": "object", "properties": date_props, "required": ["start", "end"]}},
        {"name": "get_dimension_values", "description": "列出部署账号成本维度值。",
         "inputSchema": {"type": "object", "properties": {"dimension": {"type": "string"}, **date_props},
             "required": ["dimension", "start", "end"]}},
        {"name": "get_price", "description": "通过 AWS 中国区 Pricing API 查询 CNY 按需价格。",
         "inputSchema": {"type": "object", "properties": {
             "service_code": {"type": "string"},
             "filters": {"type": "array", "items": {"type": "object", "properties": {
                 "Type": {"type": "string", "description": "TERM_MATCH, EQUALS, CONTAINS, ANY_OF, or NONE_OF"},
                 "Field": {"type": "string"}, "Value": {"type": "string"}},
                 "required": ["Type", "Field", "Value"]}},
         }, "required": ["service_code", "filters"]}},
        {"name": "recall_context", "description": "每次分析首先调用。结果仅为带 saved_at 的背景参考，不是当前数据；除非用户明确要求不重查，否则所有回答数字仍须来自本轮成本工具。",
         "inputSchema": {"type": "object", "properties": {"scope": {"type": "string"}}, "required": ["scope"]}},
        {"name": "save_finding", "description": "每次分析结束前保存关键事实或待确认假设。",
         "inputSchema": {"type": "object", "properties": {
             "scope": {"type": "string"}, "type": {"type": "string"}, "content": {"type": "string"},
             "confirmed": {"type": "boolean"}},
             "required": ["scope", "type", "content", "confirmed"]}},
    ]


def main() -> int:
    cache_arn = ensure_table(CACHE_TABLE, [{"AttributeName": "cache_key", "KeyType": "HASH"}],
                             [{"AttributeName": "cache_key", "AttributeType": "S"}])
    knowledge_arn = ensure_table(KNOWLEDGE_TABLE,
                                 [{"AttributeName": "scope", "KeyType": "HASH"}, {"AttributeName": "ts", "KeyType": "RANGE"}],
                                 [{"AttributeName": "scope", "AttributeType": "S"}, {"AttributeName": "ts", "AttributeType": "S"}])
    try:
        ddb.update_time_to_live(TableName=CACHE_TABLE, TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"})
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ValidationException":
            raise

    lambda_policy = {"Version": "2012-10-17", "Statement": [
        {"Sid": "CostExplorerRead", "Effect": "Allow", "Action": ["ce:Get*", "ce:Describe*", "ce:List*"], "Resource": "*"},
        {"Sid": "PricingRead", "Effect": "Allow", "Action": ["pricing:GetProducts", "pricing:DescribeServices"], "Resource": "*"},
        {"Sid": "DynamoTables", "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"],
         "Resource": [cache_arn, knowledge_arn]},
        {"Sid": "Logs", "Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
         "Resource": f"arn:aws-cn:logs:{REGION}:{account_id}:log-group:/aws/lambda/{LAMBDA_NAME}:*"},
    ]}
    lambda_role_arn = ensure_role(LAMBDA_ROLE, "lambda.amazonaws.com", "CostAgentToolsPolicy", lambda_policy)
    lambda_arn = ensure_lambda(lambda_role_arn)

    gateway_policy = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": lambda_arn
    }]}
    gateway_role_arn = ensure_role(GATEWAY_ROLE, "bedrock-agentcore.amazonaws.com", "InvokeCostTools", gateway_policy)

    existing = find_gateway()
    if existing:
        gateway_id = existing["gatewayId"]
    else:
        gateway_id = cp.create_gateway(
            name=GATEWAY_NAME,
            description="AWS China account-scoped cost analysis MCP gateway",
            roleArn=gateway_role_arn,
            protocolType="MCP",
            authorizerType="AWS_IAM",
            tags={"Project": "cost-analysis-agent"},
        )["gatewayId"]
    gateway = wait_gateway(gateway_id)

    targets = cp.list_gateway_targets(gatewayIdentifier=gateway_id, maxResults=100).get("items", [])
    target = next((item for item in targets if item.get("name") == TARGET_NAME), None)
    target_configuration = {"mcp": {"lambda": {
        "lambdaArn": lambda_arn,
        "toolSchema": {"inlinePayload": tool_schemas()},
    }}}
    credentials = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
    if target is None:
        target = cp.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=TARGET_NAME,
            description="Cost Explorer, Pricing, cache, and knowledge tools",
            targetConfiguration=target_configuration,
            credentialProviderConfigurations=credentials,
        )
    else:
        target = cp.update_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=target["targetId"],
            name=TARGET_NAME,
            description="Cost Explorer, Pricing, cache, and knowledge tools",
            targetConfiguration=target_configuration,
            credentialProviderConfigurations=credentials,
        )
    target_id = target["targetId"]
    for _ in range(60):
        target_detail = cp.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
        if target_detail["status"] == "READY":
            break
        if target_detail["status"] == "FAILED":
            raise RuntimeError(f"Gateway target failed: {target_detail.get('statusReasons')}")
        time.sleep(5)
    else:
        raise TimeoutError("Gateway target did not become READY")

    config = {
        "region": REGION,
        "account_id": account_id,
        "cache_table": CACHE_TABLE,
        "cache_table_arn": cache_arn,
        "knowledge_table": KNOWLEDGE_TABLE,
        "knowledge_table_arn": knowledge_arn,
        "lambda_name": LAMBDA_NAME,
        "lambda_arn": lambda_arn,
        "lambda_role_name": LAMBDA_ROLE,
        "lambda_role_arn": lambda_role_arn,
        "gateway_name": GATEWAY_NAME,
        "gateway_id": gateway_id,
        "gateway_arn": gateway["gatewayArn"],
        "gateway_url": gateway["gatewayUrl"],
        "gateway_role_name": GATEWAY_ROLE,
        "gateway_role_arn": gateway_role_arn,
        "target_name": TARGET_NAME,
        "target_id": target_id,
    }
    config_path = ROOT / "resource_config.json"
    if config_path.exists():
        existing_config = json.loads(config_path.read_text(encoding="utf-8"))
        existing_config.update(config)
        config = existing_config
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(json.dumps(config, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
