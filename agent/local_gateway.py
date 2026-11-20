"""P1/P2 local Gateway agent runner."""
from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

import boto3

from agent.common import load_dotenv, require_api_key
from agent.gateway_agent import invoke_gateway_agent

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="上個月成本 Top 5 服務及環比")
    parser.add_argument("--session-id", default=f"local-{uuid.uuid4().hex}")
    parser.add_argument("--no-s3", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    config = json.loads((ROOT / "resource_config.json").read_text(encoding="utf-8"))
    os.environ["GATEWAY_URL"] = config["gateway_url"]
    os.environ["SESSION_BUCKET"] = config.get("session_bucket", "")
    account = boto3.Session(profile_name="default", region_name="cn-north-1").client("sts").get_caller_identity()["Account"]
    result = invoke_gateway_agent(
        prompt=args.prompt,
        session_id=args.session_id,
        scope=f"account:{account}",
        api_key=require_api_key(),
        use_s3_session=not args.no_s3,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
