#!/usr/bin/env python3
"""Create the P2 S3 short-term session bucket."""
from __future__ import annotations

import json
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent
REGION = "cn-north-1"
session = boto3.Session(profile_name="default", region_name=REGION)
s3 = session.client("s3")
account = session.client("sts").get_caller_identity()["Account"]
bucket = f"cost-agent-mem-{account}-{REGION}"

try:
    s3.head_bucket(Bucket=bucket)
except ClientError as exc:
    code = exc.response.get("Error", {}).get("Code")
    if code not in {"404", "NoSuchBucket", "NotFound"}:
        raise
    s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})

s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
    "BlockPublicAcls": True,
    "IgnorePublicAcls": True,
    "BlockPublicPolicy": True,
    "RestrictPublicBuckets": True,
})
s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}, "BucketKeyEnabled": False}]
})
s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": [{"Key": "Project", "Value": "cost-analysis-agent"}]})

config_path = ROOT / "resource_config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
config["session_bucket"] = bucket
config["session_bucket_arn"] = f"arn:aws-cn:s3:::{bucket}"
config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
print(json.dumps({"session_bucket": bucket, "session_bucket_arn": config["session_bucket_arn"]}, indent=2))
