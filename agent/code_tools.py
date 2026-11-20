"""AgentCore Code Interpreter tool."""
from __future__ import annotations

import json
import time

from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands import tool

REGION = "cn-north-1"


@tool
def run_python(code: str) -> str:
    """在 AgentCore 隔离沙盒执行 Python 并返回输出；所有算术都必须使用本工具。

    Args:
        code: Python 源代码。用 print 输出结果；所有文件路径必须是相对路径。
    """
    started = time.perf_counter()
    ok = False
    try:
        stdout, stderr = [], []
        with code_session(REGION) as interpreter:
            response = interpreter.execute_code(code)
            for event in response["stream"]:
                content = event.get("result", {}).get("structuredContent", {})
                if content.get("stdout"):
                    stdout.append(content["stdout"])
                if content.get("stderr"):
                    stderr.append(content["stderr"])
                if content.get("exitCode") not in (None, 0):
                    stderr.append(f"exitCode={content['exitCode']}")
        ok = not stderr
        output = "\n".join(stdout)
        if stderr:
            output += "\n[stderr]\n" + "\n".join(stderr)
        return output.strip() or "(no output)"
    finally:
        print(json.dumps({
            "event": "tool_call", "tool": "run_python",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2), "ok": ok,
        }, separators=(",", ":")))
