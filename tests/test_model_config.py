from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent.common import make_model


class ModelConfigTests(unittest.TestCase):
    def test_reasoning_effort_low_is_forwarded_directly(self):
        with patch.dict(os.environ, {"LLM_REASONING_EFFORT": "low", "LLM_MODEL": "k3.1-pro"}, clear=False):
            model = make_model("not-a-real-key")
            request = model.format_request([{"role": "user", "content": [{"text": "ping"}]}])
        self.assertEqual(request["reasoning_effort"], "low")
        self.assertNotIn("extra_body", request)
        self.assertEqual(request["temperature"], 1)
        self.assertEqual(request["max_tokens"], 8192)

    def test_invalid_reasoning_effort_fails_before_request(self):
        with patch.dict(os.environ, {"LLM_REASONING_EFFORT": "none"}, clear=False):
            with self.assertRaisesRegex(ValueError, "low, high, or max"):
                make_model("not-a-real-key")

    def test_returned_model_mismatch_is_rejected(self):
        model = make_model("not-a-real-key")
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "model mismatch"):
                model.verify_returned_model("K2.8 Preview")


if __name__ == "__main__":
    unittest.main()
