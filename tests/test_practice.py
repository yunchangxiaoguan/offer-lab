import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import practice


PROFILE = {
    "id": "虚构学员甲",
    "projects": [
        "制度检索站\n我负责召回。",
        "采购流转台\n旧版本提到订单支付。",
        "报表整理",
    ],
}
RESUME = """# 虚构学员甲
## 项目经历
### 制度检索站
本人职责：实现检索和证据回显，便于业务专员核对原件。
### 采购流转台
负责工具调用，使用业务标识解决重复下单和接口超时。
### 报表整理
参与汇总导出并交付样例报表。
## 教育经历
### 某学院
这是教育资料，不是项目。
"""
TRANSCRIPT = """# 练习资料
**[00:03:12] 面试官：** 接口超时后重复下单怎么处理？
**候选人：** 如果是我会用另一个手机号 13800138000 发一遍。
HR：你的邮箱是什么？ 候选人：sample@example.com。
**面试官（追问）：** 只允许本地记录且外部接口不支持幂等，超时后重复下单怎么办？
面试官：[听不清] 什么？
说话人1：这个功能怎么跑？
"""


class PracticeTests(unittest.TestCase):
    def test_personal_evidence_comes_only_from_this_resume(self):
        cards = practice.personal_cards(PROFILE, RESUME)
        self.assertEqual(
            {c["project"] for c in cards}, {"制度检索站", "采购流转台", "报表整理"}
        )
        self.assertTrue(
            all(practice._valid_card(c) and c["evidence"] in RESUME for c in cards)
        )
        self.assertNotIn("订单支付", json.dumps(cards, ensure_ascii=False))
        self.assertIn("tool-timeout", {c.get("concept") for c in cards})
        edited = RESUME.replace("采购流转台", "库存核对").replace(
            "负责工具调用，使用业务标识解决重复下单和接口超时。",
            "实现入库单据的字段映射。",
        )
        new = practice.personal_cards(PROFILE, edited)
        self.assertNotIn("采购流转台", json.dumps(new, ensure_ascii=False))
        self.assertFalse({x["id"] for x in cards} & {x["id"] for x in new})
        self.assertEqual(practice.personal_cards(PROFILE, ""), [])

    def test_correct_and_wrong_lead_to_distinct_project_branches(self):
        pool = practice.personal_cards(PROFILE, RESUME)
        first = practice.mock_next(pool, [])
        right = {"card": first, "selected": first["correct"]}
        wrong = {"card": first, "selected": (first["correct"] + 1) % 4}
        deeper = practice.mock_next(pool, [right])
        remedial = practice.mock_next(pool, [wrong])
        self.assertEqual(first["project"], deeper["project"])
        self.assertEqual(remedial["project"], first["project"])
        self.assertEqual(
            (deeper["practice_step"], remedial["practice_step"]),
            ("深入追问", "纠错复练"),
        )
        self.assertNotEqual(deeper["id"], remedial["id"])
        history = []
        while next_card := practice.mock_next(pool, history, limit=6):
            history.append({"card": next_card, "selected": next_card["correct"]})
        self.assertEqual(len({h["card"]["id"] for h in history}), 6)
        self.assertGreaterEqual(len({h["card"]["project"] for h in history}), 2)
        self.assertNotIn("practice_step", pool[0])

    def test_transcript_separates_conditions_and_private_candidate_answers(self):
        first = practice.import_transcript(TRANSCRIPT, [])
        self.assertEqual(len(first["cards"]), 1)
        card = first["cards"][0]
        self.assertTrue(practice._valid_card(card))
        self.assertEqual(card["concept"], "tool-timeout")
        text = json.dumps(first, ensure_ascii=False)
        self.assertNotIn("13800138000", text)
        self.assertNotIn("sample@example.com", text)
        self.assertTrue(any("不支持幂等" in x["question"] for x in first["pending"]))
        self.assertTrue(any("说话人" in x["reason"] for x in first["pending"]))
        self.assertTrue(any("转写不清" in x["reason"] for x in first["pending"]))
        public = {
            k: v
            for k, v in card.items()
            if k not in ("review_question", "source_ref", "concept")
        }
        rerun = practice.import_transcript(TRANSCRIPT, [public])
        self.assertFalse(rerun["cards"])
        self.assertEqual(rerun["merged"][0]["id"], card["id"])

    def test_recent_wording_resolves_from_published_alias(self):
        source = "问：大模型评分如何校准？\n答：我不清楚。"
        c = practice.import_transcript(source, [])["cards"][0]
        pub = {**c, "id": "old-id", "also_asked": ["两位人工评审的分歧怎么核对？"]}
        out = practice.import_transcript("面试官：两位人工评审的分歧怎么核对？", [pub])
        self.assertEqual(out["merged"][0]["id"], "old-id")
        self.assertFalse(out["cards"])

    def test_multiline_and_same_line_speaker_boundaries(self):
        source = "Q: 跨页表格怎么保留表头？ A: RAG 召回正确但答错怎么处理？\nQ2: 大模型\n裁判给结果打分是否公正？"
        cards = practice.import_transcript(source, [])["cards"]
        self.assertEqual(
            {c["concept"] for c in cards}, {"cross-page", "judge-calibration"}
        )

    def test_model_retains_only_grounded_personal_evidence(self):
        valid = practice.personal_cards(PROFILE, RESUME)[0]
        invented = {**valid, "title": "虚构", "evidence": "并不存在的本人事实"}
        with patch.object(
            practice,
            "_json_model",
            return_value=[{**valid, "title": "模型追问"}, invented],
        ):
            cards = practice.personal_cards(PROFILE, RESUME, True)
        generated = [c for c in cards if c["generation_mode"] == "model"]
        self.assertEqual([c["title"] for c in generated], ["模型追问"])

    def test_unknown_model_import_persists_stable_source_id(self):
        source = (
            "面试官：有序列表中查询某个区间边界用什么方法？\n候选人：我的私有回答。"
        )
        valid = practice._question(
            "有序数组的查询边界",
            "在升序数组查某一取值范围的左右边界，哪种做法适合反复查询？",
            [
                ("二分分别求左右边界", "有序性支持两次二分确定区间。"),
                ("每次随机选一项", "不能确定边界。"),
                ("只取最大值", "没有下界和上界的位置。"),
                ("交换首尾元素", "打乱有序条件。"),
            ],
            "我会分别用二分找第一个满足下界的位置和第一个超过上界的位置，用两个下标得到区间。",
            "没有匹配值呢？",
            "两个边界重合，返回空区间。",
            practice.TECH,
            "后端与数据工程",
            "算法与白板推演",
        )
        with patch.object(
            practice, "_json_model", return_value=[{**valid, "index": 1}]
        ) as model:
            result = practice.import_transcript(source, [], True)
            self.assertNotIn("私有回答", str(model.call_args))
        self.assertEqual(len(result["cards"]), 1)
        again = practice.import_transcript(source, result["cards"])
        self.assertEqual(again["merged"][0]["id"], result["cards"][0]["id"])
        self.assertFalse(again["cards"])

    def test_manual_card_checks_answer_menu_and_pii(self):
        pending = {"question": "未知问题如何复查？", "source_ref": "第 8 行"}
        template = practice._case_card(practice.CASES[0])
        card = practice.manual_card(
            pending, {**template, "title": "联系test42@example.com核对缓存"}
        )
        self.assertNotIn("@", card["title"])
        self.assertEqual(card["source_type"], "教师补编")
        self.assertIn("id", card)
        with self.assertRaises(ValueError):
            practice.manual_card(pending, {**template, "subtopic": "不在目录"})
        with self.assertRaises(ValueError):
            practice.manual_card(pending, {**template, "options": ["重复"] * 4})
        rerun = practice.import_transcript("面试官：未知问题如何复查？", [card])
        self.assertEqual(rerun["merged"][0]["id"], card["id"])

    def test_model_canonical_menu_and_rejects_unrelated_topic(self):
        source = "面试官：当多个文档分块都很相似时怎样定位原始段落？"
        good = {
            **practice._case_card(practice.CASES[2]),
            "title": "文档分块保留原始位置",
            "topic": "RAG",
            "subtopic": "chunking",
            "index": 1,
        }
        wrong = {**practice._case_card(practice.CASES[1]), "index": 1}
        with patch.object(practice, "_json_model", return_value=[wrong, good]):
            result = practice.import_transcript(source, [], True)
        self.assertEqual(result["cards"][0]["subtopic"], "文本切块与父子分块")
        self.assertEqual(result["cards"][0]["topic"], "RAG 知识库")

    def test_second_model_batch_failure_and_retry_only_incomplete_questions(self):
        questions = [
            f"给定 {n} 个已排好序的数组，怎样定位重复值的右边界？" for n in range(1, 8)
        ]
        text = "\n".join("面试官：" + q + "\n候选人：私有原答。" for q in questions)
        text += "\n说话人2：有序数组怎么批量核对？\n面试官：那这个你们怎么做呢？"
        offline = practice.import_transcript(text, [])
        self.assertEqual(
            [i["question"] for i in offline["pending"] if i.get("retryable")], questions
        )
        manual_only = [i for i in offline["pending"] if not i.get("retryable")]
        self.assertEqual(len(manual_only), 2)
        legacy = {
            "question": questions[0],
            "reason": "需补充题面条件与可靠参考答案",
            "source_ref": "第 1 行",
        }
        self.assertTrue(practice.can_retry(legacy))
        self.assertFalse(practice.can_retry({**legacy, "reason": "说话人待确认"}))
        self.assertFalse(
            practice.can_retry({**legacy, "question": "那这个你们怎么做呢？"})
        )
        template = practice._case_card(practice.CASES[0])
        received = []

        def answer(system, records):
            received.append([item["question"] for item in records])
            self.assertTrue(all(set(item) == {"index", "question"} for item in records))
            if len(received) == 2:
                raise ValueError("模型输出达到长度上限")
            return [
                {
                    **template,
                    "index": item["index"],
                    "title": item["question"],
                    "prompt": item["question"],
                    "topic": "后端与数据工程",
                    "subtopic": "算法与白板推演",
                }
                for item in records
            ]

        with patch.object(practice, "_json_model", side_effect=answer):
            partial = practice.import_transcript(text, [], True)
            self.assertEqual(list(map(len, received)), [3, 3, 1])
            self.assertEqual(
                [c["review_question"] for c in partial["cards"]],
                questions[:3] + questions[6:],
            )
            missing = [i for i in partial["pending"] if i.get("retryable")]
            self.assertEqual([i["question"] for i in missing], questions[3:6])
            self.assertTrue(
                all(
                    "可重试" in i["reason"] and "行" in i["source_ref"] for i in missing
                )
            )
            previous = json.dumps(partial, ensure_ascii=False)
            recovered = practice.retry_pending(partial, [])
            self.assertEqual(received[3:], [[q] for q in questions[3:6]])
            self.assertEqual(json.dumps(partial, ensure_ascii=False), previous)
            self.assertEqual(recovered["cards"][:4], partial["cards"])
            self.assertEqual(
                {c["review_question"] for c in recovered["cards"]}, set(questions)
            )
            self.assertEqual(recovered["pending"], manual_only)
            self.assertEqual(practice.retry_pending(recovered, []), recovered)
            self.assertEqual(len(received), 6)


if __name__ == "__main__":
    unittest.main()
