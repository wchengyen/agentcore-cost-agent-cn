"""Build one Strands agent per request using Gateway MCP and Code Interpreter."""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from strands import Agent
from strands.tools.mcp.mcp_client import MCPClient

from agent.code_tools import run_python
from agent.common import make_model, message_text
from agent.session_manager import KimiSafeS3SessionManager
from agent.sigv4 import FreshSigV4Auth
from agent.system_prompt import SYSTEM_PROMPT

REGION = "cn-north-1"


def _all_tools(mcp: MCPClient) -> list[Any]:
    tools: list[Any] = []
    token = None
    while True:
        page = mcp.list_tools_sync(pagination_token=token)
        tools.extend(page)
        token = page.pagination_token
        if token is None:
            return tools


def invoke_gateway_agent(
    prompt: str,
    session_id: str,
    scope: str,
    api_key: str,
    use_s3_session: bool = True,
) -> dict[str, Any]:
    gateway_url = os.environ["GATEWAY_URL"]
    session_manager = None
    if use_s3_session:
        session_manager = KimiSafeS3SessionManager(
            session_id=session_id,
            bucket=os.environ["SESSION_BUCKET"],
            prefix="sessions/",
            region_name=REGION,
        )
    mcp = MCPClient(
        url=gateway_url,
        auth_provider=FreshSigV4Auth(REGION),
        startup_timeout=60,
        application_name="cost-analysis-agent",
        application_version="1.0.0",
    )
    with mcp:
        gateway_tools = _all_tools(mcp)
        tool_names = [tool.tool_name for tool in gateway_tools]
        model = make_model(api_key)
        agent = Agent(
            model=model,
            tools=gateway_tools + [run_python],
            system_prompt=SYSTEM_PROMPT,
            session_manager=session_manager,
            agent_id="costagent",
            callback_handler=None,
        )
        request = (
            f"固定分析 scope：{scope}。今天是 {date.today().isoformat()}。"
            "严格遵循先 recall_context、后分析、最后 save_finding 的顺序。\n用户问题：" + prompt
        )
        result = agent(request)
        tool_calls = {
            name: metric.call_count for name, metric in result.metrics.tool_metrics.items()
        }
        return {
            "result": message_text(result.message),
            "session_id": session_id,
            "tools": tool_names + ["run_python"],
            "tool_calls": tool_calls,
            "model_requested": model.requested_model,
            "models_returned": model.returned_models,
            "reasoning_effort": os.getenv("LLM_REASONING_EFFORT", "low"),
        }
