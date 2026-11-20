"""Local frontend backend for invoking the deployed AgentCore Runtime."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError

REGION = "cn-north-1"
CP_ENDPOINT = "https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn"
DP_ENDPOINT = "https://bedrock-agentcore.cn-north-1.amazonaws.com.cn"
SESSION_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{33,200}")
ROOT = Path(__file__).resolve().parents[1]


class FrontendError(RuntimeError):
    pass


class RuntimeNotReadyError(FrontendError):
    pass


def load_runtime_arn() -> str:
    configured = os.getenv("COST_AGENT_RUNTIME_ARN")
    if configured:
        return configured
    state = json.loads((ROOT / "resource_config.json").read_text(encoding="utf-8"))
    return state["runtime_arn"]


def validate_session_id(session_id: str) -> None:
    if not SESSION_PATTERN.fullmatch(session_id):
        raise FrontendError("Session ID must contain 33-200 letters, numbers, dots, colons, underscores, or hyphens.")


def _friendly_error(exc: Exception) -> FrontendError:
    if isinstance(exc, (ReadTimeoutError, ConnectTimeoutError)):
        return FrontendError("請求逾時。成本分析可能需要數分鐘，請稍後重試。")
    if isinstance(exc, EndpointConnectionError):
        return FrontendError("無法連線到 AWS 中國區 AgentCore 端點。")
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", type(exc).__name__)
        if "Throttl" in code or code in {"TooManyRequestsException", "LimitExceededException"}:
            return FrontendError(f"AgentCore 正在限流（{code}），請稍後重試。")
        if code in {"ConflictException", "ResourceNotFoundException", "ValidationException"}:
            return FrontendError(f"Runtime 尚未就緒或不可用（{code}）。")
        if code == "RuntimeClientError":
            return FrontendError("Runtime 回傳伺服器錯誤（RuntimeClientError）；請查看 CloudWatch Runtime 日誌後重試。")
        return FrontendError(f"AWS 呼叫失敗（{code}）。")
    return FrontendError(f"呼叫失敗（{type(exc).__name__}）。")


class RuntimeClient:
    def __init__(self, profile: str = "default", runtime_arn: str | None = None) -> None:
        self.runtime_arn = runtime_arn or load_runtime_arn()
        self.runtime_id = self.runtime_arn.rsplit("/", 1)[-1]
        session = boto3.Session(profile_name=profile, region_name=REGION)
        config = Config(connect_timeout=15, read_timeout=600, retries={"mode": "standard", "max_attempts": 5})
        self.control = session.client("bedrock-agentcore-control", endpoint_url=CP_ENDPOINT, config=config)
        self.runtime = session.client("bedrock-agentcore", endpoint_url=DP_ENDPOINT, config=config)

    def assert_ready(self) -> None:
        status = self.control.get_agent_runtime(agentRuntimeId=self.runtime_id)["status"]
        if status != "READY":
            raise RuntimeNotReadyError(f"Runtime 尚未就緒，目前狀態：{status}")

    def invoke(self, prompt: str, session_id: str) -> dict[str, Any]:
        validate_session_id(session_id)
        if not prompt.strip():
            raise FrontendError("請輸入問題。")
        started = time.perf_counter()
        try:
            self.assert_ready()
            response = self.runtime.invoke_agent_runtime(
                agentRuntimeArn=self.runtime_arn,
                runtimeSessionId=session_id,
                qualifier="DEFAULT",
                payload=json.dumps({"prompt": prompt.strip(), "session_id": session_id}).encode("utf-8"),
            )
            body = bytearray()
            text_parts = []
            for chunk in response.get("response", []):
                if isinstance(chunk, bytes):
                    body.extend(chunk)
                else:
                    text_parts.append(str(chunk))
            decoded = body.decode("utf-8") + "".join(text_parts)
            result = json.loads(decoded)
            result["latency_seconds"] = round(time.perf_counter() - started, 3)
            return result
        except FrontendError:
            raise
        except Exception as exc:
            raise _friendly_error(exc) from exc


def build_prompt(base_prompt: str, start: str | None = None, end: str | None = None, group_by: str | None = None) -> str:
    additions = []
    if start and end:
        additions.append(f"指定查詢日期為 {start} 至 {end}，結束日不包含。")
    if group_by:
        additions.append(f"分組維度使用 {group_by}。")
    return base_prompt if not additions else base_prompt + "\n" + " ".join(additions)
