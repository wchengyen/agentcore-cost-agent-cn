#!/usr/bin/env python3
"""P0 environment checks. Never prints credentials or secret values."""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").exists() else []:
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

PINNED = {
    "bedrock-agentcore": "1.24.1",
    "bedrock-agentcore-starter-toolkit": "0.3.14",
    "strands-agents": "1.59.0",
    "openai": "2.54.0",
    "mcp": "2.1.1",
    "httpx": "0.28.1",
    "boto3": "1.43.110",
}
failed: list[str] = []


def report(ok: bool, name: str, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + (f" ({detail})" if detail else ""))
    if not ok:
        failed.append(name)


def main() -> int:
    report(sys.version_info[:2] == (3, 12), "Python 3.12", sys.version.split()[0])
    for package, expected in PINNED.items():
        try:
            actual = metadata.version(package)
            report(actual == expected, f"package {package}", actual)
        except metadata.PackageNotFoundError:
            report(False, f"package {package}", "not installed")

    import boto3
    session = boto3.Session(profile_name="default", region_name="cn-north-1")
    try:
        identity = session.client("sts").get_caller_identity()
        report(identity["Arn"].startswith("arn:aws-cn:"), "STS partition aws-cn", f"account {identity['Account']}")
    except Exception as exc:
        report(False, "STS partition aws-cn", type(exc).__name__)
        identity = None

    try:
        control = session.client(
            "bedrock-agentcore-control",
            endpoint_url="https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn",
        )
        control.list_gateways(maxResults=1)
        report(True, "AgentCore control plane", control.meta.endpoint_url)
    except Exception as exc:
        report(False, "AgentCore control plane", f"{type(exc).__name__}: {str(exc)[:120]}")

    if identity:
        try:
            end = date.today()
            start = end - timedelta(days=1)
            ce = session.client("ce", region_name="cn-northwest-1", endpoint_url="https://ce.cn-northwest-1.amazonaws.com.cn")
            ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                Filter={"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [identity["Account"]]}},
            )
            report(True, "Cost Explorer reachable", ce.meta.endpoint_url)
        except Exception as exc:
            report(False, "Cost Explorer reachable", f"{type(exc).__name__}: {str(exc)[:120]}")

    key = os.getenv("LLM_API_KEY")
    report(bool(key), "LLM_API_KEY present in .env")
    if key:
        try:
            from openai import OpenAI
            response = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL", "https://api.kimi.com/coding/v1")).chat.completions.create(
                model=os.getenv("LLM_MODEL", "k3.1-pro"),
                max_tokens=8,
                messages=[{"role": "user", "content": "reply pong"}],
            )
            report(bool(response.choices), "Kimi LLM reachable")
        except Exception as exc:
            report(False, "Kimi LLM reachable", type(exc).__name__)

    print()
    if failed:
        print(f"{len(failed)} check(s) failed: " + ", ".join(failed))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
