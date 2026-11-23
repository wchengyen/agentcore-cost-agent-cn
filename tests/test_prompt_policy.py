from __future__ import annotations

import unittest
from pathlib import Path

from agent.system_prompt import SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]


class PromptPolicyTests(unittest.TestCase):
    def test_memory_is_background_and_current_turn_tools_are_required(self):
        self.assertIn("recall_context 只提供背景参考，不是当前数据", SYSTEM_PROMPT)
        self.assertIn("每个成本数字都必须来自本轮调用", SYSTEM_PROMPT)
        self.assertIn("歷史結論", SYSTEM_PROMPT)
        self.assertIn("saved_at", SYSTEM_PROMPT)
        self.assertIn("不要重新查询", SYSTEM_PROMPT)

    def test_composition_and_hypotheses_are_constrained(self):
        self.assertIn("必须本轮调用 get_cost(group_by=USAGE_TYPE)", SYSTEM_PROMPT)
        self.assertIn("不得自行添加 NAT、EBS、快照等标签", SYSTEM_PROMPT)
        self.assertIn("独立“待確認”部分", SYSTEM_PROMPT)
        self.assertIn("最近 N 天", SYSTEM_PROMPT)
        self.assertIn("必须用 run_python 验证", SYSTEM_PROMPT)

    def test_gateway_descriptions_repeat_freshness_policy(self):
        setup_text = (ROOT / "setup_p1.py").read_text(encoding="utf-8")
        self.assertIn("结果仅为带 saved_at 的背景参考，不是当前数据", setup_text)
        self.assertIn("回答当前数字前必须调用", setup_text)
        self.assertNotIn('"enum":', setup_text)
        self.assertNotIn('"default":', setup_text)
        self.assertNotIn('"minimum":', setup_text)
        self.assertNotIn('"maximum":', setup_text)


if __name__ == "__main__":
    unittest.main()
