from __future__ import annotations

import unittest

from strands.types.session import SessionMessage

from agent.session_manager import _without_reasoning


class SessionSanitizerTests(unittest.TestCase):
    def test_reasoning_blocks_are_removed_without_mutating_original(self):
        original = SessionMessage(
            message={
                "role": "assistant",
                "content": [
                    {"reasoningContent": {"reasoningText": {"text": "private reasoning"}}},
                    {"text": "answer"},
                    {"toolUse": {"toolUseId": "1", "name": "x", "input": {}}},
                ],
            },
            message_id=1,
        )
        clean = _without_reasoning(original)
        self.assertEqual(len(original.message["content"]), 3)
        self.assertEqual(len(clean.message["content"]), 2)
        self.assertNotIn("reasoningContent", clean.message["content"][0])


if __name__ == "__main__":
    unittest.main()
