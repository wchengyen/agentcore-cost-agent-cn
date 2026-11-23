from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent.common import make_model


class ModelConfigTests(unittest.TestCase):
    def test_optional_sampling_and_reasoning_are_omitted(self):
        with patch.dict(os.environ, {"LLM_MODEL": "glm-5.3-flash"}, clear=False):
            os.environ.pop("LLM_REASONING_EFFORT", None)
            os.environ.pop("LLM_TEMPERATURE", None)
            model = make_model("not-a-real-key")
            request = model.format_request([{"role": "user", "content": [{"text": "ping"}]}])
        self.assertNotIn("reasoning_effort", request)
        self.assertNotIn("temperature", request)
        self.assertNotIn("extra_body", request)
        self.assertEqual(request["max_tokens"], 8192)

    def test_configured_sampling_and_reasoning_are_forwarded(self):
        with patch.dict(os.environ, {
            "LLM_REASONING_EFFORT": "high", "LLM_TEMPERATURE": "1", "LLM_MODEL": "k3.1-pro"
        }, clear=False):
            model = make_model("not-a-real-key")
            request = model.format_request([{"role": "user", "content": [{"text": "ping"}]}])
        self.assertEqual(request["reasoning_effort"], "high")
        self.assertEqual(request["temperature"], 1.0)

    def test_invalid_reasoning_effort_fails_before_request(self):
        with patch.dict(os.environ, {"LLM_REASONING_EFFORT": "none"}, clear=False):
            with self.assertRaisesRegex(ValueError, "unset, low, high, or max"):
                make_model("not-a-real-key")

    def test_returned_model_mismatch_is_rejected(self):
        model = make_model("not-a-real-key")
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "model mismatch"):
                model.verify_returned_model("unexpected-model")


if __name__ == "__main__":
    unittest.main()
