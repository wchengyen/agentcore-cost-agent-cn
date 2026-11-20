"""AgentCore Runtime entrypoint for the AWS China Cost Analysis Agent."""
from __future__ import annotations

import json
import logging
import os
import re
import uuid

import boto3
from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import BedrockAgentCoreContext

from agent.gateway_agent import invoke_gateway_agent

REGION = "cn-north-1"
logger = logging.getLogger(__name__)


def _load_api_key_at_startup() -> str:
    secret_name = os.getenv("LLM_SECRET_NAME", "cost-agent/llm-api-key")
    response = boto3.client("secretsmanager", region_name=REGION).get_secret_value(SecretId=secret_name)
    value = response.get("SecretString")
    if not value:
        raise RuntimeError("LLM secret has no SecretString")
    # Accept the documented raw secret string and common JSON wrappers without logging either.
    if value.lstrip().startswith("{"):
        data = json.loads(value)
        value = data.get("LLM_API_KEY") or data.get("api_key")
    if not value:
        raise RuntimeError("LLM secret does not contain an API key")
    return value


LLM_API_KEY = _load_api_key_at_startup()
app = BedrockAgentCoreApp()


def _safe_session_id(value: str | None) -> str:
    value = value or f"runtime-{uuid.uuid4().hex}"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value):
        raise ValueError("session_id contains unsupported characters")
    return value


@app.entrypoint
def invoke(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
        raise ValueError("prompt must be a non-empty string of at most 20000 characters")
    runtime_session = BedrockAgentCoreContext.get_session_id()
    session_id = _safe_session_id(payload.get("session_id") or runtime_session)
    scope = payload.get("scope") or f"account:{os.environ['DEPLOYING_ACCOUNT_ID']}"
    return invoke_gateway_agent(prompt.strip(), session_id, scope, LLM_API_KEY, use_s3_session=True)


if __name__ == "__main__":
    app.run()
