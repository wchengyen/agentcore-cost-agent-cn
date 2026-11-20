#!/usr/bin/env python3
"""Create the Runtime execution role after the user creates the LLM secret."""
from __future__ import annotations

import json
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent
REGION = "cn-north-1"
ROLE_NAME = "CostAgentRuntimeRole"
SECRET_NAME = "cost-agent/llm-api-key"
session = boto3.Session(profile_name="default", region_name=REGION)
iam = session.client("iam")
secrets = session.client("secretsmanager")
s3 = session.client("s3")
config_path = ROOT / "resource_config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))

# This confirms existence only. SecretString is never requested or printed.
secret_arn = secrets.describe_secret(SecretId=SECRET_NAME)["ARN"]
trust = {"Version": "2012-10-17", "Statement": [{
    "Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole"
}]}
try:
    role = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust),
        Description="Runtime role for AWS China Cost Analysis Agent",
        Tags=[{"Key": "Project", "Value": "cost-analysis-agent"}],
    )["Role"]
    time.sleep(10)
except iam.exceptions.EntityAlreadyExistsException:
    role = iam.get_role(RoleName=ROLE_NAME)["Role"]
    iam.update_assume_role_policy(RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust))

policy = {"Version": "2012-10-17", "Statement": [
    {"Sid": "InvokeCostGateway", "Effect": "Allow", "Action": "bedrock-agentcore:InvokeGateway", "Resource": config["gateway_arn"]},
    {"Sid": "CodeInterpreter", "Effect": "Allow", "Action": [
        "bedrock-agentcore:StartCodeInterpreterSession", "bedrock-agentcore:InvokeCodeInterpreter",
        "bedrock-agentcore:GetCodeInterpreterSession", "bedrock-agentcore:StopCodeInterpreterSession"
    ], "Resource": "*"},
    {"Sid": "SessionBucketList", "Effect": "Allow", "Action": ["s3:ListBucket"],
     "Resource": config["session_bucket_arn"], "Condition": {"StringLike": {"s3:prefix": ["sessions/*"]}}},
    {"Sid": "SessionObjects", "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
     "Resource": config["session_bucket_arn"] + "/sessions/*"},
    {"Sid": "KnowledgeAndCache", "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"],
     "Resource": [config["cache_table_arn"], config["knowledge_table_arn"]]},
    {"Sid": "ReadLlmSecret", "Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": secret_arn},
    {"Sid": "RuntimeLogs", "Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
     "Resource": f"arn:aws-cn:logs:{REGION}:{config['account_id']}:log-group:/aws/bedrock-agentcore/*"},
    {"Sid": "Observability", "Effect": "Allow", "Action": ["cloudwatch:PutMetricData", "xray:PutTraceSegments", "xray:PutSpans"],
     "Resource": "*"},
]}
iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="CostAgentRuntimePolicy", PolicyDocument=json.dumps(policy))
config["runtime_role_name"] = ROLE_NAME
config["runtime_role_arn"] = role["Arn"]
config["llm_secret_name"] = SECRET_NAME
config["llm_secret_arn"] = secret_arn

deployment_bucket = f"cost-agent-deploy-{config['account_id']}-{REGION}"
try:
    s3.head_bucket(Bucket=deployment_bucket)
except Exception:
    s3.create_bucket(Bucket=deployment_bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
s3.put_public_access_block(Bucket=deployment_bucket, PublicAccessBlockConfiguration={
    "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True
})
s3.put_bucket_encryption(Bucket=deployment_bucket, ServerSideEncryptionConfiguration={
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
})
config["deployment_bucket"] = deployment_bucket
config["deployment_bucket_arn"] = f"arn:aws-cn:s3:::{deployment_bucket}"
config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
print(json.dumps({"runtime_role_arn": role["Arn"], "secret_name": SECRET_NAME, "deployment_bucket": deployment_bucket}, indent=2))
