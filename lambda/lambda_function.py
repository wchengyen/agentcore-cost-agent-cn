"""Cost Analysis Agent Gateway Lambda tools for AWS China."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable

import boto3
from boto3.dynamodb.conditions import Key

REGION = os.getenv("AWS_REGION", "cn-north-1")
CE_REGION = "cn-northwest-1"
CE_ENDPOINT = "https://ce.cn-northwest-1.amazonaws.com.cn"
PRICING_ENDPOINT = "https://api.pricing.cn-northwest-1.amazonaws.com.cn"
ACCOUNT_ID = os.getenv("DEPLOYING_ACCOUNT_ID", "")
CACHE_TABLE = os.getenv("CACHE_TABLE", "cost-agent-ce-cache")
KNOWLEDGE_TABLE = os.getenv("KNOWLEDGE_TABLE", "cost-agent-knowledge")
CACHE_TTL_SECONDS = 6 * 60 * 60

logger = logging.getLogger()
logger.setLevel(logging.INFO)
_ce = boto3.client("ce", region_name=CE_REGION, endpoint_url=CE_ENDPOINT)
_pricing = boto3.client("pricing", region_name=CE_REGION, endpoint_url=PRICING_ENDPOINT)
_ddb = boto3.resource("dynamodb", region_name=REGION)

DIMENSIONS = {"SERVICE", "USAGE_TYPE", "REGION", "LINKED_ACCOUNT"}
GRANULARITIES = {"MONTHLY", "DAILY"}


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _validate_dates(start: str, end: str) -> None:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date >= end_date:
        raise ValueError("start must be earlier than end; CE end dates are exclusive")


def _account_filter() -> dict[str, Any]:
    if not ACCOUNT_ID:
        raise RuntimeError("DEPLOYING_ACCOUNT_ID is required to enforce single-account scope")
    return {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [ACCOUNT_ID]}}


def _exclude_adjustments_filter() -> dict[str, Any]:
    return {"Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}}


def _scoped_filter(user_filter: dict[str, Any] | None, exclude_adjustments: bool = True) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [_account_filter()]
    if exclude_adjustments:
        clauses.append(_exclude_adjustments_filter())
    if user_filter:
        if not isinstance(user_filter, dict):
            raise ValueError("filter must be a Cost Explorer Expression object")
        clauses.append(user_filter)
    return clauses[0] if len(clauses) == 1 else {"And": clauses}


def _cache_key(operation: str, request: dict[str, Any]) -> str:
    raw = _compact({"operation": operation, "request": request}).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cached(operation: str, request: dict[str, Any], call: Callable[[], Any]) -> tuple[Any, bool]:
    """Cache CE responses for six hours. Cache failures never block CE."""
    key = _cache_key(operation, request)
    table = _ddb.Table(CACHE_TABLE)
    now = int(time.time())
    try:
        item = table.get_item(Key={"cache_key": key}, ConsistentRead=False).get("Item")
        if item and int(item.get("expires_at", 0)) > now:
            return json.loads(item["payload"]), True
    except Exception as exc:  # cache is an optimization
        logger.warning(_compact({"event": "cache_read", "ok": False, "error": type(exc).__name__}))

    result = call()
    try:
        table.put_item(Item={
            "cache_key": key,
            "payload": _compact(result),
            "created_at": now,
            "expires_at": now + CACHE_TTL_SECONDS,
        })
    except Exception as exc:
        logger.warning(_compact({"event": "cache_write", "ok": False, "error": type(exc).__name__}))
    return result, False


def _ce_pages(method_name: str, request: dict[str, Any], token_name: str = "NextPageToken") -> list[dict[str, Any]]:
    method = getattr(_ce, method_name)
    pages: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        args = dict(request)
        if token:
            args[token_name] = token
        response = method(**args)
        pages.append(response)
        token = response.get(token_name)
        if not token:
            return pages


def _group_definition(group_by: str) -> tuple[dict[str, str], str]:
    normalized = group_by.upper()
    if normalized.startswith("TAG:"):
        key = group_by.split(":", 1)[1].strip()
        if not key:
            raise ValueError("TAG:<key> requires a tag key")
        return {"Type": "TAG", "Key": key}, f"TAG:{key}"
    if normalized not in DIMENSIONS:
        raise ValueError(f"unsupported group_by: {group_by}")
    return {"Type": "DIMENSION", "Key": normalized}, normalized


def get_cost(
    start: str,
    end: str,
    granularity: str = "MONTHLY",
    group_by: str = "SERVICE",
    filter: dict[str, Any] | None = None,
    top_n: int = 10,
    metric: str = "UnblendedCost",
) -> dict[str, Any]:
    """Return account-scoped Top-N cost groups, Others, and total."""
    _validate_dates(start, end)
    granularity = granularity.upper()
    if granularity not in GRANULARITIES:
        raise ValueError("granularity must be MONTHLY or DAILY")
    if not 1 <= int(top_n) <= 100:
        raise ValueError("top_n must be between 1 and 100")
    group, group_label = _group_definition(group_by)
    request = {
        "TimePeriod": {"Start": start, "End": end},
        "Granularity": granularity,
        "Metrics": [metric],
        "GroupBy": [group],
        "Filter": _scoped_filter(filter),
    }

    def fetch() -> list[dict[str, Any]]:
        return _ce_pages("get_cost_and_usage", request)

    pages, hit = _cached("get_cost_and_usage", request, fetch)
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    period_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    period_ends: dict[str, str] = {}
    period_estimated: defaultdict[str, bool] = defaultdict(bool)
    unit = "CNY"
    for page in pages:
        for period in page.get("ResultsByTime", []):
            period_start = period["TimePeriod"]["Start"]
            period_ends[period_start] = period["TimePeriod"]["End"]
            period_estimated[period_start] = period_estimated[period_start] or bool(period.get("Estimated", False))
            for group_result in period.get("Groups", []):
                key = group_result.get("Keys", ["(empty)"])[0] or "(empty)"
                amount_info = group_result.get("Metrics", {}).get(metric, {})
                amount = Decimal(amount_info.get("Amount", "0"))
                unit = amount_info.get("Unit", unit)
                totals[key] += amount
                period_totals[period_start] += amount
    periods = [{
        "start": period_start,
        "end": period_ends[period_start],
        "amount": float(period_totals[period_start]),
        "estimated": period_estimated[period_start],
    } for period_start in sorted(period_totals)]
    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    top = ordered[: int(top_n)]
    others = sum((amount for _, amount in ordered[int(top_n):]), Decimal("0"))
    total = sum(totals.values(), Decimal("0"))
    return {
        "start": start,
        "end_exclusive": end,
        "granularity": granularity,
        "group_by": group_label,
        "metric": metric,
        "unit": unit,
        "top": [{"name": name, "amount": float(amount)} for name, amount in top],
        "others": float(others),
        "total": float(total),
        "periods": periods,
        "cache_hit": hit,
        "scope_account": ACCOUNT_ID,
        "excluded_record_types": ["Credit", "Refund"],
    }


def compare_periods(a_start: str, a_end: str, b_start: str, b_end: str, group_by: str = "SERVICE") -> dict[str, Any]:
    """Compare periods using daily-average normalized costs and return top movers."""
    _validate_dates(a_start, a_end)
    _validate_dates(b_start, b_end)
    a = get_cost(a_start, a_end, "DAILY", group_by, top_n=100)
    b = get_cost(b_start, b_end, "DAILY", group_by, top_n=100)
    a_days = (date.fromisoformat(a_end) - date.fromisoformat(a_start)).days
    b_days = (date.fromisoformat(b_end) - date.fromisoformat(b_start)).days
    av = {x["name"]: Decimal(str(x["amount"])) / a_days for x in a["top"]}
    bv = {x["name"]: Decimal(str(x["amount"])) / b_days for x in b["top"]}
    movers = []
    for name in set(av) | set(bv):
        old = av.get(name, Decimal("0"))
        new = bv.get(name, Decimal("0"))
        delta = new - old
        movers.append({
            "name": name,
            "a_daily_avg": float(old),
            "b_daily_avg": float(new),
            "delta_daily_avg": float(delta),
            "pct": None if old == 0 else float(delta / old * 100),
        })
    movers.sort(key=lambda x: abs(x["delta_daily_avg"]), reverse=True)
    a_avg = Decimal(str(a["total"])) / a_days
    b_avg = Decimal(str(b["total"])) / b_days
    return {
        "a": {"start": a_start, "end_exclusive": a_end, "days": a_days, "daily_avg": float(a_avg)},
        "b": {"start": b_start, "end_exclusive": b_end, "days": b_days, "daily_avg": float(b_avg)},
        "delta_daily_avg": float(b_avg - a_avg),
        "pct": None if a_avg == 0 else float((b_avg - a_avg) / a_avg * 100),
        "top_movers": movers[:10],
        "unit": a["unit"],
        "cache_hit": bool(a["cache_hit"] and b["cache_hit"]),
    }


def get_forecast(start: str, end: str, granularity: str = "MONTHLY") -> dict[str, Any]:
    _validate_dates(start, end)
    request = {
        "TimePeriod": {"Start": start, "End": end},
        "Metric": "UNBLENDED_COST",
        "Granularity": granularity.upper(),
        "Filter": _scoped_filter(None),
        "PredictionIntervalLevel": 80,
    }
    response, hit = _cached("get_cost_forecast", request, lambda: _ce.get_cost_forecast(**request))
    return {
        "start": start,
        "end_exclusive": end,
        "granularity": granularity.upper(),
        "total": response.get("Total"),
        "forecast_results": response.get("ForecastResultsByTime", []),
        "cache_hit": hit,
    }


def get_ri_sp_coverage_utilization(start: str, end: str) -> dict[str, Any]:
    _validate_dates(start, end)
    period = {"Start": start, "End": end}
    # RI/SP APIs do not accept the RECORD_TYPE dimension used by cost-and-usage.
    scoped = _scoped_filter(None, exclude_adjustments=False)
    calls = {
        "ri_coverage": ("get_reservation_coverage", {"TimePeriod": period, "Granularity": "MONTHLY", "Filter": scoped}),
        "ri_utilization": ("get_reservation_utilization", {"TimePeriod": period, "Granularity": "MONTHLY", "Filter": scoped}),
        "sp_coverage": ("get_savings_plans_coverage", {"TimePeriod": period, "Granularity": "MONTHLY", "Filter": scoped}),
        "sp_utilization": ("get_savings_plans_utilization", {"TimePeriod": period, "Granularity": "MONTHLY", "Filter": scoped}),
    }
    output: dict[str, Any] = {}
    all_hit = True
    for name, (method, request) in calls.items():
        response, hit = _cached(method, request, lambda m=method, r=request: getattr(_ce, m)(**r))
        all_hit = all_hit and hit
        if name == "ri_coverage":
            output[name] = response.get("Total", {})
        elif name == "ri_utilization":
            output[name] = response.get("Total", {})
        elif name == "sp_coverage":
            output[name] = response.get("Total", {})
        else:
            output[name] = response.get("Total", {})
    output["cache_hit"] = all_hit
    output["start"] = start
    output["end_exclusive"] = end
    return output


def get_anomalies(start: str, end: str) -> dict[str, Any]:
    _validate_dates(start, end)
    request = {"DateInterval": {"StartDate": start, "EndDate": end}, "MaxResults": 100}
    pages, hit = _cached("get_anomalies", request, lambda: _ce_pages("get_anomalies", request))
    items = []
    for page in pages:
        for item in page.get("Anomalies", []):
            # GetAnomalies has no server-side linked-account filter. Keep only
            # root causes explicitly attributed to this deploying account.
            account_causes = [
                cause for cause in item.get("RootCauses", [])
                if cause.get("LinkedAccount") == ACCOUNT_ID
            ]
            if not account_causes:
                continue
            impact = item.get("Impact", {})
            items.append({
                "id": item.get("AnomalyId"),
                "start": item.get("AnomalyStartDate"),
                "end": item.get("AnomalyEndDate"),
                "dimension": item.get("DimensionValue"),
                "total_impact": impact.get("TotalImpact"),
                "impact_percentage": impact.get("TotalImpactPercentage"),
                "root_causes": account_causes[:5],
            })
    items.sort(key=lambda x: x.get("total_impact") or 0, reverse=True)
    return {"anomalies": items[:50], "count": len(items), "cache_hit": hit}


def get_dimension_values(dimension: str, start: str, end: str) -> dict[str, Any]:
    _validate_dates(start, end)
    dimension = dimension.upper()
    request = {
        "TimePeriod": {"Start": start, "End": end},
        "Dimension": dimension,
        "Context": "COST_AND_USAGE",
        "Filter": _scoped_filter(None),
        "MaxResults": 1000,
    }
    pages, hit = _cached("get_dimension_values", request, lambda: _ce_pages("get_dimension_values", request))
    values = []
    for page in pages:
        values.extend(x.get("Value") for x in page.get("DimensionValues", []) if x.get("Value"))
    return {"dimension": dimension, "values": sorted(set(values)), "count": len(set(values)), "cache_hit": hit}


def get_price(service_code: str, filters: list[dict[str, str]]) -> dict[str, Any]:
    """Query AWS China Pricing and return compact CNY on-demand dimensions."""
    if not isinstance(filters, list):
        raise ValueError("filters must be a list of Pricing API filter objects")
    request = {"ServiceCode": service_code, "Filters": filters, "FormatVersion": "aws_v1", "MaxResults": 100}
    products = []
    token = None
    while len(products) < 100:
        args = dict(request)
        if token:
            args["NextToken"] = token
        response = _pricing.get_products(**args)
        products.extend(response.get("PriceList", []))
        token = response.get("NextToken")
        if not token:
            break
    compact_products = []
    for raw in products:
        product = json.loads(raw) if isinstance(raw, str) else raw
        attributes = product.get("product", {}).get("attributes", {})
        dimensions = []
        for term in product.get("terms", {}).get("OnDemand", {}).values():
            for dim in term.get("priceDimensions", {}).values():
                cny = dim.get("pricePerUnit", {}).get("CNY")
                if cny is not None:
                    dimensions.append({
                        "description": dim.get("description"),
                        "unit": dim.get("unit"),
                        "begin": dim.get("beginRange"),
                        "end": dim.get("endRange"),
                        "price_cny": cny,
                    })
        if dimensions:
            compact_products.append({
                "sku": product.get("product", {}).get("sku"),
                "attributes": {k: attributes.get(k) for k in (
                    "servicecode", "servicename", "location", "instanceType", "operatingSystem",
                    "tenancy", "preInstalledSw", "capacitystatus", "usagetype", "operation"
                ) if attributes.get(k) is not None},
                "on_demand": dimensions,
            })
        if len(compact_products) >= 20:
            break
    return {"service_code": service_code, "currency": "CNY", "products": compact_products, "matched": len(products)}


def recall_context(scope: str) -> dict[str, Any]:
    if not scope or len(scope) > 256:
        raise ValueError("scope is required and must be <= 256 characters")
    response = _ddb.Table(KNOWLEDGE_TABLE).query(
        KeyConditionExpression=Key("scope").eq(scope),
        ScanIndexForward=False,
        Limit=20,
    )
    findings = [{k: v for k, v in item.items() if k in {"ts", "type", "content", "confirmed"}}
                for item in response.get("Items", [])]
    return {"scope": scope, "findings": findings}


def save_finding(scope: str, type: str, content: str, confirmed: bool) -> dict[str, Any]:
    if not scope or not type or not content:
        raise ValueError("scope, type, and content are required")
    if len(content) > 10000:
        raise ValueError("content must be <= 10000 characters")
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    _ddb.Table(KNOWLEDGE_TABLE).put_item(Item={
        "scope": scope,
        "ts": ts,
        "type": type[:100],
        "content": content,
        "confirmed": bool(confirmed),
    })
    return {"saved": True, "scope": scope, "ts": ts}


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_cost": get_cost,
    "compare_periods": compare_periods,
    "get_forecast": get_forecast,
    "get_ri_sp_coverage_utilization": get_ri_sp_coverage_utilization,
    "get_anomalies": get_anomalies,
    "get_dimension_values": get_dimension_values,
    "get_price": get_price,
    "recall_context": recall_context,
    "save_finding": save_finding,
}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    started = time.perf_counter()
    tool_name = event.pop("tool", "") if isinstance(event, dict) else ""
    client_context = getattr(context, "client_context", None)
    custom = getattr(client_context, "custom", None) if client_context else None
    if custom:
        tool_name = custom.get("bedrockAgentCoreToolName", tool_name)
    short_name = next((name for name in TOOLS if tool_name.endswith(name)), "")
    ok = False
    try:
        if not short_name:
            raise ValueError(f"unknown tool: {tool_name}")
        result = TOOLS[short_name](**event)
        ok = True
        return result
    finally:
        logger.info(_compact({
            "event": "tool_call",
            "tool": short_name or tool_name,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "ok": ok,
        }))
