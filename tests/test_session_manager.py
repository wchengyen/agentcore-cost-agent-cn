from __future__ import annotations

import unittest

from strands.types.session import SessionMessage

from agent.session_manager import _without_reasoning


class ReasoningSanitizerTests(unittest.TestCase):
    def test_reasoning_fields_and_think_tags_are_removed(self):
        original = SessionMessage(
            message={
                "role": "assistant",
                "content": [
                    {"reasoningContent": {"reasoningText": {"text": "private reasoning"}}},
                    {"reasoning_content": "provider trace"},
                    {"text": "<think>hidden</think>answer"},
                    {"toolUse": {"toolUseId": "1", "name": "x", "input": {}}},
                ],
            },
            message_id=1,
        )
        clean = _without_reasoning(original)
        self.assertEqual(len(original.message["content"]), 4)
        self.assertEqual(clean.message["content"], [
            {"text": "answer"},
            {"toolUse": {"toolUseId": "1", "name": "x", "input": {}}},
        ])


if __name__ == "__main__":
    unittest.main()
