"""Fresh-credential SigV4 authentication for AgentCore Gateway MCP."""
from __future__ import annotations

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


class FreshSigV4Auth(httpx.Auth):
    requires_request_body = True

    def __init__(self, region: str = "cn-north-1", service: str = "bedrock-agentcore") -> None:
        self.region = region
        self.service = service
        self.session = boto3.Session(region_name=region)

    def _sign(self, request: httpx.Request) -> None:
        credentials = self.session.get_credentials()
        if credentials is None:
            raise RuntimeError("AWS credentials are unavailable")
        # Runtime role credentials rotate. Freeze a fresh snapshot for this request only.
        frozen = credentials.get_frozen_credentials()
        excluded = {"authorization", "content-length", "x-amz-date", "x-amz-security-token"}
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content or b"",
            headers={k: v for k, v in request.headers.items() if k.lower() not in excluded},
        )
        SigV4Auth(frozen, self.service, self.region).add_auth(aws_request)
        request.headers.update(dict(aws_request.headers))

    def sync_auth_flow(self, request: httpx.Request):
        self._sign(request)
        yield request

    async def async_auth_flow(self, request: httpx.Request):
        self._sign(request)
        yield request
