"""P0 local prototype: Strands + Kimi + direct boto3 Cost Explorer tools."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import date
from pathlib import Path

from strands import Agent, tool

from agent.common import load_dotenv, make_model, message_text
from agent.system_prompt import P0_SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
os.environ.setdefault("AWS_PROFILE", "default")
os.environ.setdefault("AWS_REGION", "cn-north-1")
if not os.getenv("DEPLOYING_ACCOUNT_ID"):
    import boto3
    os.environ["DEPLOYING_ACCOUNT_ID"] = boto3.Session(profile_name="default", region_name="cn-north-1").client("sts").get_caller_identity()["Account"]

_spec = importlib.util.spec_from_file_location("cost_lambda", ROOT / "lambda" / "lambda_function.py")
_cost = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_cost)


@tool
def get_cost(start: str, end: str, granularity: str = "MONTHLY", group_by: str = "SERVICE", top_n: int = 10) -> str:
    """查询部署账号自身的成本，返回 Top-N、Others 和总额；日期 end 不包含。

    Args:
        start: YYYY-MM-DD inclusive.
        end: YYYY-MM-DD exclusive.
        granularity: MONTHLY or DAILY.
        group_by: SERVICE, USAGE_TYPE, REGION, LINKED_ACCOUNT, or TAG:<key>.
        top_n: Number of groups.
    """
    return json.dumps(_cost.get_cost(start, end, granularity, group_by, top_n=top_n), ensure_ascii=False)


@tool
def compare_periods(a_start: str, a_end: str, b_start: str, b_end: str, group_by: str = "SERVICE") -> str:
    """按每日平均成本比较两个期间，B 相对 A，返回主要变动。

    Args:
        a_start: Baseline start, inclusive.
        a_end: Baseline end, exclusive.
        b_start: Comparison start, inclusive.
        b_end: Comparison end, exclusive.
        group_by: Cost grouping dimension.
    """
    return json.dumps(_cost.compare_periods(a_start, a_end, b_start, b_end, group_by), ensure_ascii=False)


def _month_bounds(today: date) -> tuple[str, str, str]:
    this_month = today.replace(day=1)
    previous_end = this_month
    previous_start = (this_month.replace(day=1) - __import__("datetime").timedelta(days=1)).replace(day=1)
    earlier_start = (previous_start - __import__("datetime").timedelta(days=1)).replace(day=1)
    return earlier_start.isoformat(), previous_start.isoformat(), previous_end.isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="上個月成本 Top 5 服務及環比")
    args = parser.parse_args()
    older, previous, current = _month_bounds(date.today())
    dated_prompt = (
        f"今天是 {date.today().isoformat()}。{args.prompt}。"
        f"上個月期間為 {previous} 到 {current}（end exclusive），前一個月從 {older} 到 {previous}。"
        "請調用 get_cost(top_n=5) 和 compare_periods，使用每日均值口徑。"
    )
    agent = Agent(model=make_model(), tools=[get_cost, compare_periods], system_prompt=P0_SYSTEM_PROMPT, callback_handler=None)
    result = agent(dated_prompt)
    print(message_text(result.message))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
