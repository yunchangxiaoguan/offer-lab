import io
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import materials


def sample(count=3):
    projects = [
        "项目一：设备手册 RAG 问答\n背景：车间工程师需要按设备型号与生产日期核对维护说明。\n本人职责：我负责按标题切分手册、保留页码和生效日期，再按设备编号过滤检索结果。\n难点：旧版条款与新版条款描述接近，检索结果偶尔混用。\n解决方案：在召回前筛选适用版本，重排后检查最终引用页。\n交付：提供能够回看原文的维护说明。\n验证：抽取同一设备的跨版本问题，逐条核对返回的生效日期。",
        "项目二：仓储售后 Agent\n背景：仓库人员需要查验补货请求，物流异常时会重复提交。\n架构：订单进入后先查询状态，再生成待确认的处理建议。\n本人职责：我负责工具调用、提交前人工确认和回执查询；其他组员负责工单入口。\n技术栈：Python、LangGraph。\n难点：接口超时但下游可能已经受理。\n解决方案：保存业务标识并优先查询回执。\n交付：交付审批与发货回执页面。\n验证：在本地用重复请求检查同一工单只产生一次受理记录。\n模拟指标：效率提高 87%。",
        "项目三：发票 OCR 复核\n项目背景：财务逐张核对纸质发票的币种、金额与税率，容易遗漏跨页表头。\n技术方案：从扫描件中提取关键字段并保留原页定位。\n本人职责：我负责把低置信字段交给财务人员复核。\n结果：交付能回查原图的复核清单。",
        "项目四：排班协作\n背景：现场班次变更后需要重新对齐人员和岗位。\n本人职责：我参与排班接口联调并校验时间冲突。\n交付：形成待确认班次清单。",
        "项目五：业务数据服务\n用户：运营按业务日期汇总订单。\n职责：我负责只读汇总接口和数据范围过滤。\n交付：支持从日报汇总回查订单明细。",
    ]
    return {
        "name": "练习同学",
        "basic": "姓名：练习同学\n求职意向：大模型应用开发工程师\n开发经验：4年\n教育经历：示例学院 本科 计算机科学\n邮箱：learner@example.test\n工作经历：示例制造 软件开发\n手机：13000000000",
        "projects": projects[:count],
    }


class MaterialTests(unittest.TestCase):
    def test_home_example_and_single_line_aliases(self):
        for basic in (
            "姓名：林禾（虚构示例）\n求职方向：大模型应用开发\n教育：软件工程本科\n经历：后端应用开发，负责知识库检索、工单接口和验证。",
            "学生姓名：林禾（虚构示例） 意向岗位：大模型应用开发 最高学历：软件工程本科 任职经历：后端应用开发，负责知识库检索、工单接口和验证。",
            "名字：林禾（虚构示例）\n目标职位：大模型应用开发\n教育背景\n软件工程本科\n工作经历\n后端应用开发，负责知识库检索、工单接口和验证。",
        ):
            with self.subTest(basic=basic):
                profile = {**sample(), "basic": basic, "name": ""}
                text = materials.generate_material("resume", profile)
                sections = re.split(r"(?m)^## (.+)\n", text)
                parts = dict(zip(sections[1::2], sections[2::2]))
                self.assertIn("# 林禾（虚构示例）", sections[0])
                self.assertIn("大模型应用开发", parts["求职信息"])
                self.assertIn("软件工程本科", parts["教育经历"])
                self.assertIn("后端应用开发", parts["工作经历"])
                self.assertNotIn("软件工程本科", parts["求职信息"])
                self.assertNotIn("后端应用开发", parts["求职信息"])

    def test_resume_layout_and_fact_scope(self):
        for count in (3, 5):
            with self.subTest(count=count):
                text = materials.generate_material("resume", sample(count))
                self.assertIn("本机离线事实整理", text)
                self.assertNotIn("87%", text)
                self.assertEqual(len(re.findall(r"^### ", text, re.M)), count)
                self.assertLess(
                    text.index("仓储售后 Agent"), text.index("设备手册 RAG")
                )
                word = Document(
                    io.BytesIO(materials.export_material("resume", "docx", text))
                )
                self.assertIn(
                    "邮箱：learner@example.test", [p.text for p in word.paragraphs]
                )
                with fitz.open(
                    stream=materials.export_material("resume", "pdf", text),
                    filetype="pdf",
                ) as pdf:
                    self.assertIn(len(pdf), (2, 3))
                    pages = [p.get_text() for p in pdf]
                    self.assertIn("仓储售后", pages[0])
                    self.assertIn("回查", pages[-1])
                    self.assertNotIn("生成方式", "".join(pages))
                    for p in pdf:
                        self.assertTrue(
                            all(b[0] >= 45 and b[2] < 558 for b in p.get_text("blocks"))
                        )
                self.assertFalse(
                    materials.export_material("resume", "md", text).startswith(b"<!--")
                )

    def test_interview_shapes_and_current_version(self):
        profile = sample(5)
        five = materials.generate_material("five", profile)
        self.assertEqual(five.count("### "), 25)
        deep = materials.generate_material("eighteen", profile)
        self.assertEqual(
            [int(s) for s in re.findall(r"(?m)^## (\d\d) ", deep)], list(range(1, 19))
        )
        self.assertEqual(deep.count("继续追问："), 18)
        for body in (five, deep):
            self.assertIn("仓储售后", body)
            self.assertIn("设备手册", body)
            self.assertNotIn("87%", body)
            self.assertNotIn("13000000000", body)
        profile["resume"] = (
            "# 练习同学\n\n## 项目经历\n\n### 客服坐席工具\n本人职责：我只维护人工复核队列。"
        )
        edited = materials.generate_material("eighteen", profile)
        self.assertIn("人工复核队列", edited)
        self.assertNotIn("仓储售后", edited)
        self.assertNotIn("设备手册", edited)

    def test_real_results_and_draft_business_states_survive(self):
        profile = sample()
        profile["projects"][1] += (
            "\n验证：离线复核 100 件样本，96% 的回执与人工复核结果一致。"
        )
        text = materials.generate_material("resume", profile)
        self.assertIn("待确认的处理建议", text)
        self.assertIn("96%", text)
        self.assertNotIn("87%", text)

    def test_model_followup_only_requests_missing_answers(self):
        for kind, expect in (("five", 15), ("eighteen", 18)):
            batches = []

            def complete(system, user):
                topics = json.loads(user.split("本批题目：")[-1])
                batches.append([topic["id"] for topic in topics])
                if len(batches) == 1:
                    topics = topics[:-1]
                return json.dumps(
                    [
                        {
                            "id": topic["id"],
                            "a": "我负责维护回执查询。",
                            "q": "怎么复测？",
                            "b": "重放同一工单并核对回执。",
                        }
                        for topic in topics
                    ],
                    ensure_ascii=False,
                )

            with (
                patch("llm.available", return_value=True),
                patch("llm.complete", side_effect=complete),
            ):
                text = materials.generate_material(kind, sample(), True)
            self.assertEqual([len(b) for b in batches], [expect, 1])
            self.assertEqual(batches[1][0], batches[0][-1])
            self.assertEqual(text.count("继续追问："), expect)

    def test_model_contact_handling_and_incomplete_reply(self):
        def model_reply(system, data):
            self.assertNotIn("learner@example.test", data)
            self.assertNotIn("13000000000", data)
            self.assertNotIn("效率提高 87%", data)
            self.assertIn("三至五", system)
            return "## 项目经历\n### 仓储售后 Agent\n我负责工具调用。\n### 设备手册 RAG 问答\n维护检索。\n### 发票 OCR 复核\n核对字段。"

        with (
            patch("llm.available", return_value=True),
            patch("llm.complete", side_effect=model_reply),
        ):
            text = materials.generate_material("resume", sample(), True)
            self.assertIn("模型生成", text)
            self.assertIn("learner@example.test", text)
        with (
            patch("llm.available", return_value=True),
            patch("llm.complete", return_value="## 01 起因\n测试"),
        ):
            with self.assertRaisesRegex(ValueError, "十八"):
                materials.generate_material("eighteen", sample(), True)


if __name__ == "__main__":
    unittest.main()
