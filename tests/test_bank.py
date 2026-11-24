import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bank import list_cards, lookup_legacy, migration_ledger, search_cards, taxonomy


class BankTests(unittest.TestCase):
    def test_every_published_card_has_one_choice_and_a_spoken_followup(self):
        catalog = taxonomy()
        cards = list_cards()
        self.assertEqual(len(cards), len({q["id"] for q in cards}))
        self.assertEqual(set(catalog["stages"]), {q["stage"] for q in cards})
        paths = set()
        for q in cards:
            with self.subTest(q["id"]):
                self.assertEqual(4, len(q["options"]))
                self.assertEqual(4, len(set(q["options"])))
                self.assertEqual(4, len(q["reasons"]))
                self.assertIn(q["correct"], range(4))
                self.assertTrue(all(s.strip() for s in q["options"] + q["reasons"]))
                self.assertTrue(
                    all(
                        q[k].strip()
                        for k in (
                            "prompt",
                            "title",
                            "spoken",
                            "followup",
                            "followup_answer",
                        )
                    )
                )
                for topic, sub in [
                    (q["topic"], q["subtopic"]),
                    *((p["topic"], p["subtopic"]) for p in q["related"]),
                ]:
                    if topic or sub:
                        self.assertIn(sub, catalog["topics"][topic])
                        paths.add((topic, sub))
        self.assertEqual(
            paths,
            {(topic, sub) for topic, subs in catalog["topics"].items() for sub in subs},
        )

    def test_all_source_numbers_survive_duplicate_grouping(self):
        rows = migration_ledger()
        self.assertEqual(set(range(1, 551)), {r["number"] for r in rows})
        self.assertEqual(550, len({r["legacy_id"] for r in rows}))
        self.assertEqual(457, len({r["canonical_number"] for r in rows}))
        ids = {q["id"] for q in list_cards()}
        for row in rows:
            self.assertEqual("已专项改编", row["status"])
            self.assertIn(row["card_id"], ids)
        for query in ("旧题 492", "#492", rows[491]["legacy_id"]):
            self.assertEqual(
                [rows[491]["card_id"]], [q["id"] for q in search_cards(query)]
            )

    def test_legacy_lookup_distinguishes_adapted_reference_and_no_match(self):
        specific = {
            "rawstyle_fc_retry": "L135",
            "exp_mcp_02_tool_desc": "L136",
            "prac90_q010": "L470",
            "hf110_q053": "L403",
        }
        for old_id, card in specific.items():
            with self.subTest(old_id):
                self.assertEqual(card, lookup_legacy(old_id)["card_id"])
                self.assertEqual("已专项改编", search_cards(old_id)[0]["legacy_status"])
        with patch(
            "bank._old_ids",
            return_value={
                "旧题601": {"status": "同主题参考，待专项改编", "card_id": "I05"},
                "旧题602": {"status": "待专项改编，暂无对应题", "card_id": None},
            },
        ):
            self.assertEqual(
                "同主题参考，待专项改编", search_cards("旧题 601")[0]["legacy_status"]
            )
            self.assertEqual([], search_cards("旧题 602"))
            self.assertEqual(
                "待专项改编，暂无对应题", lookup_legacy("旧题 602")["status"]
            )
        self.assertIsNone(lookup_legacy("不存在的编号"))
        self.assertNotIn("legacy_status", search_cards("LangGraph")[0])

    def test_aliases_and_stage_topic_intersection(self):
        def ids(*args, **kwargs):
            return {q["id"] for q in search_cards(*args, **kwargs)}

        self.assertTrue(
            {"B001"}
            <= ids(
                stage="系统架构与技术选型", topic="Agent 智能体", subtopic="LangGraph"
            )
        )
        self.assertTrue(
            {"L490"}
            <= ids(
                stage="现场编码与白板推演", topic="Agent 智能体", subtopic="LangGraph"
            )
        )
        self.assertEqual(ids("切块"), ids("chunking"))
        self.assertIn("B012", ids("父子分块", topic="RAG 知识库"))
        self.assertIn("L518", ids("RAG 切块"))
        self.assertFalse(ids(topic="RAG 知识库", subtopic="LangGraph"))
        for query, topic, sub, card in [
            ("缓存", "RAG 知识库", "缓存与失效", "B016"),
            ("cache", "后端与数据工程", "Redis 应用缓存", "B040"),
            ("KV Cache", "模型部署与运行", "显存、量化与 KV Cache", "B032"),
            ("Harness", "Agent 智能体", "Agent Harness（运行与控制）", "L487"),
        ]:
            self.assertIn(card, ids(query, topic=topic, subtopic=sub))

    def test_new_phrasings_are_searchable_with_same_id(self):
        q = list_cards()[0]
        q["also_asked"] = ["开场怎样快速讲设备手册"]
        self.assertEqual([q], search_cards("开场怎样快速", cards=[q]))


if __name__ == "__main__":
    unittest.main()
