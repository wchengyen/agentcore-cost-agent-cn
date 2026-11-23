from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from frontend.history import HistoryStore, deterministic_summary, extract_key_facts, make_title


class SummaryTests(unittest.TestCase):
    def test_title_is_truncated_to_twenty_characters(self):
        title = make_title("請分析上個月所有服務成本並且列出每日平均環比變化")
        self.assertLessEqual(len(title), 20)
        self.assertTrue(title.endswith("…"))

    def test_extracts_currency_and_percentage_verbatim(self):
        answer = """## 結論
總成本 CNY 5,889.38，日均環比 -1.92%。
| 1 | EC2 Compute | 1,715.12 CNY | +2.72% |
原因待確認。
"""
        facts = extract_key_facts(answer)
        self.assertEqual(len(facts), 2)
        self.assertIn("CNY 5,889.38", facts[0])
        self.assertIn("-1.92%", facts[0])
        self.assertIn("EC2 Compute", facts[1])
        self.assertIn("+2.72%", facts[1])

    def test_summary_uses_first_prompt_as_topic(self):
        summary = deterministic_summary("上月 Top 5 服務及環比。", "總額 CNY 5,889.38，日均 -1.92%。")
        self.assertEqual(summary["title"], "上月 Top 5 服務及環比")
        self.assertEqual(len(summary["facts"]), 1)


class HistoryStoreTests(unittest.TestCase):
    def test_round_trip_rename_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.json"
            store = HistoryStore(path)
            session_id = "ui-12345678901234567890123456789012"
            store.ensure_session(session_id, "glm-5.3-flash")
            store.append_turn(
                session_id,
                "上月 Top 5 服務及環比。",
                "總成本 CNY 5,889.38，日均環比 -1.92%。",
                49.319,
                {"CostAgentTools___get_cost": 2, "run_python": 1},
                "glm-5.3-flash",
            )
            loaded = store.load()["sessions"][session_id]
            self.assertEqual(len(loaded["turns"]), 1)
            self.assertEqual(loaded["turns"][0]["tool_counts"]["run_python"], 1)
            self.assertIn("CNY 5,889.38", loaded["summary"]["facts"][0])

            store.rename(session_id, "十月成本摘要")
            self.assertEqual(store.load()["sessions"][session_id]["summary"]["title"], "十月成本摘要")

            store.delete(session_id)
            self.assertNotIn(session_id, store.load()["sessions"])

    def test_invalid_file_falls_back_to_empty_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(HistoryStore(path).load(), {"version": 1, "sessions": {}})


if __name__ == "__main__":
    unittest.main()
