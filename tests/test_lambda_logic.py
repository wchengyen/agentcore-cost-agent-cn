from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

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
