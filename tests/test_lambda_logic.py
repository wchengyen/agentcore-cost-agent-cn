from __future__ import annotations

import importlib.util
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
os.environ["DEPLOYING_ACCOUNT_ID"] = "123456789012"
spec = importlib.util.spec_from_file_location("cost_lambda_test", ROOT / "lambda" / "lambda_function.py")
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class CostToolTests(unittest.TestCase):
    def test_scope_and_adjustment_filters_are_mandatory(self):
        expression = module._scoped_filter({"Dimensions": {"Key": "SERVICE", "Values": ["EC2"]}})
        text = str(expression)
        self.assertIn("123456789012", text)
        self.assertIn("Credit", text)
        self.assertIn("Refund", text)
        self.assertIn("EC2", text)

    def test_get_cost_top_others_total(self):
        pages = [{"ResultsByTime": [{
            "TimePeriod": {"Start": "2026-01-01", "End": "2026-02-01"},
            "Estimated": False,
            "Groups": [
                {"Keys": ["A"], "Metrics": {"UnblendedCost": {"Amount": "10", "Unit": "CNY"}}},
                {"Keys": ["B"], "Metrics": {"UnblendedCost": {"Amount": "7", "Unit": "CNY"}}},
                {"Keys": ["C"], "Metrics": {"UnblendedCost": {"Amount": "3", "Unit": "CNY"}}},
            ],
        }]}]
        with patch.object(module, "_cached", return_value=(pages, False)):
            result = module.get_cost("2026-01-01", "2026-02-01", top_n=2)
        self.assertEqual(result["total"], 20.0)
        self.assertEqual(result["others"], 3.0)
        self.assertEqual([x["name"] for x in result["top"]], ["A", "B"])

    def test_forecast_clamps_past_dates_to_utc_today(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 23, tzinfo=tz)

        captured = {}

        def cached(operation, request, call):
            captured.update(request)
            return ({"Total": {}, "ForecastResultsByTime": []}, False)

        with patch.object(module, "datetime", FixedDateTime), patch.object(module, "_cached", side_effect=cached):
            result = module.get_forecast("2026-11-01", "2026-11-02", "DAILY")
        self.assertEqual(captured["TimePeriod"], {"Start": "2026-11-23", "End": "2026-11-24"})
        self.assertTrue(result["start_adjusted"])
        self.assertTrue(result["end_adjusted"])
        self.assertIn("effective 2026-11-23..2026-11-24", result["start_adjusted_note"])

    def test_ri_sp_data_unavailable_is_a_structured_status(self):
        def cached(operation, request, call):
            if operation == "get_savings_plans_utilization":
                raise ClientError({"Error": {"Code": "DataUnavailableException", "Message": ""}}, operation)
            return ({"Total": {"value": "ok"}}, False)

        with patch.object(module, "_cached", side_effect=cached):
            result = module.get_ri_sp_coverage_utilization("2026-10-01", "2026-11-01")
        self.assertEqual(result["status"], "partial_unavailable")
        self.assertEqual(result["sp_utilization"]["status"], "unavailable")
        self.assertEqual(result["ri_coverage"]["status"], "available")

    def test_gateway_prefix_uses_suffix_matching(self):
        class ClientContext:
            custom = {"bedrockAgentCoreToolName": "CostAgentTools___recall_context"}
        class Context:
            client_context = ClientContext()
        with patch.object(module, "recall_context", return_value={"scope": "x", "findings": []}):
            old = module.TOOLS["recall_context"]
            module.TOOLS["recall_context"] = module.recall_context
            try:
                result = module.lambda_handler({"scope": "x"}, Context())
            finally:
                module.TOOLS["recall_context"] = old
        self.assertEqual(result["scope"], "x")


if __name__ == "__main__":
    unittest.main()
