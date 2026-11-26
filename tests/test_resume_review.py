"""Regression cases for provenance, supplementary facts and final exported copies."""

import copy
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import materials
import resume_review as rr


def complete():
    return {
        "name": "练习生林帆",
        "standard": "auto",
        "basic": "姓名：练习生林帆\n目标岗位：大模型应用开发工程师\n教育经历：虚构理工学院 软件工程本科\n工作经历：应届生，以下均为课程实践。",
        "projects": [
            "项目一：设备核查 Agent\n时间：2025.01–2025.03\n背景：库管需要核对设备编号和领用人。\n本人职责：我用 LangGraph 编写查询工具，保留人工确认节点。我负责在教学测试机部署查询服务。\n团队分工：其他组员负责维护登录页面。\n交付：交付领用核对单。\n验证：在本地回放重复请求，核对业务标识。",
            "项目二：维护手册 RAG\n时间：2025.04–2025.06\n业务：维修人员需要按设备版本核实维护方法。\n本人职责：我负责按标题切块并保留原文引用。\n交付：提供可打开原页的维护说明。\n验证：离线检查 20 条问题，命中 18 条，命中率 90%。",
            "项目三：发票核对\n时间：2025.07–2025.09\n背景：财务逐张核对金额与票据类别。\n本人职责：我用 LoRA 微调分类模型，将存疑字段送人工复核。\n交付：交付带原页定位的复核清单。\n验证：人工逐张核查类别和页码。",
        ],
    }


class ReviewTests(unittest.TestCase):
    def test_rendered_release_uses_same_text(self):
        p = complete()
        output = {}
        text, r = rr.build_resume(p, artifacts=output)
        self.assertEqual((r["status"], r["issues"]), ("ready", []))
        self.assertEqual(set(output), {"pdf", "docx"})
        self.assertEqual(r["body_sha256"], rr.digest(text))
        for fmt, blob in output.items():
            self.assertEqual(r["artifacts"][fmt]["sha256"], rr.digest(blob))
            self.assertEqual(blob, materials.export_material("resume", fmt, text))
        self.assertTrue(r["artifacts"]["docx"]["body_matches"])
        self.assertTrue(r["artifacts"]["pdf"]["body_matches"])
        self.assertIn(r["artifacts"]["pdf"]["pages"], [2, 3])
        self.assertTrue(
            all(
                p["ink_pixels"] and len(p["image_sha256"]) == 64
                for p in r["artifacts"]["pdf"]["page_checks"]
            )
        )
        self.assertGreater(len(r["evidence"]), 10)
        self.assertTrue(r["polish"]["changes"])
        self.assertNotRegex(text, r"技术栈：|专业技能\n\n- [^\n]+：我负责")
        with fitz.open(stream=output["pdf"], filetype="pdf") as pdf:
            self.assertIn("设备核查", pdf[0].get_text())
        self.assertIn(
            "练习生林帆", Document(io.BytesIO(output["docx"])).paragraphs[0].text
        )
        json.dumps(r, ensure_ascii=False)

    def test_zero_titles_and_optional_metrics(self):
        p = complete()
        for count in range(3):
            with self.subTest(count=count):
                q = {**p, "projects": ["设备核查", "政策问答"][:count]}
                with patch(
                    "llm.complete", side_effect=AssertionError("缺资料不调用模型")
                ):
                    _, r = rr.build_resume(q, True)
                self.assertEqual(r["status"], "draft")
                self.assertIn("project_count", [i["code"] for i in r["issues"]])
        q = {
            **p,
            "projects": ["项目一：设备核查", "项目二：政策问答", "项目三：图像复核"],
        }
        issues = rr.review_profile(q)
        self.assertCountEqual(
            [s["field"] for s in issues if s["code"] == "project_facts"],
            ["projects.0", "projects.1", "projects.2"],
        )
        q = copy.deepcopy(p)
        q["projects"][1] = (
            q["projects"][1].split("验证：")[0] + "指标：准确率提升 20%。"
        )
        text, r = rr.build_resume(q)
        self.assertEqual(r["status"], "ready", r["issues"])
        self.assertNotIn("20%", text)
        self.assertTrue(any(i["code"] == "optional_metric" for i in r["suggestions"]))

    def test_same_number_different_meaning_and_peer_ownership(self):
        p = complete()
        text, r = rr.build_resume(p)
        original = "离线检查 20 条问题，命中 18 条，命中率 90%"
        self.assertIn(original, text)
        bad = text.replace(original, "已生产上线，线上回答准确率提升 90%")
        self.assertEqual(rr.check_resume(p, bad)["status"], "draft")
        edited = text.replace(
            "分工：其他组员负责维护登录页面", "本人职责：负责维护登录页面"
        )
        self.assertIn(
            "role_drift", [x["code"] for x in rr.check_resume(p, edited)["issues"]]
        )
        q = text.replace("### 发票核对", "### 进口贸易监控")
        self.assertIn(
            "foreign_project", [x["code"] for x in rr.check_resume(p, q)["issues"]]
        )

    def test_different_position_and_missing_project_dates(self):
        p = complete()
        p["projects"][0] = p["projects"][0].replace(
            "我用 LangGraph 编写查询工具，保留人工确认节点。", "我只维护登录页面。"
        )
        self.assertIn("skill_Agent", [s["code"] for s in rr.review_profile(p)])
        p["projects"][1] = p["projects"][1].replace(
            "我负责按标题切块并保留原文引用", "我只负责前端页面校验"
        )
        self.assertIn("skill_RAG", [s["code"] for s in rr.review_profile(p)])
        p["standard"] = "job"
        self.assertFalse(
            any(s["code"].startswith("skill_") for s in rr.review_profile(p))
        )
        p = complete()
        p["projects"][0] = p["projects"][0].replace("时间：2025.01–2025.03", "")
        self.assertIn("project_period", [s["code"] for s in rr.review_profile(p)])

    def test_time_stage_conflicts_and_valid_parallel(self):
        p = complete()
        p["projects"][0] = p["projects"][0].replace(
            "2025.01–2025.03", "2023.01–2023.03"
        )
        self.assertIn("tech_date", [s["code"] for s in rr.review_profile(p)])
        p = complete()
        p["projects"][0] = p["projects"][0].replace(
            "2025.01–2025.03", "2025.01–2025.04"
        )
        self.assertIn("timeline_overlap", [s["code"] for s in rr.review_profile(p)])
        p["projects"][0] += "\n项目同期并行协作，前一项在测试机发布，另一项只整理文档。"
        self.assertNotIn("timeline_overlap", [s["code"] for s in rr.review_profile(p)])
        p["projects"][0] += "\n部署：只在本机演示。部署：已正式上线。"
        self.assertIn("deployment_conflict", [s["code"] for s in rr.review_profile(p)])

    def test_model_repair_and_refuse_role_upgrade(self):
        p = complete()
        local = rr.conservative_text(p)
        bad = local.replace("交付领用核对单", "独立完成生产上线，节省七十万元")

        def polish(system, user):
            sample = json.loads(user)
            key = next((k for k, v in sample.items() if "人工复核" in v), None)
            return json.dumps({key: "本人独立上线了生产系统。"} if key else {})

        with (
            patch("materials.generate_material", return_value=bad),
            patch("llm.complete", side_effect=polish),
        ):
            out, r = rr.build_resume(p, True)
        self.assertEqual(r["status"], "ready", r["issues"])
        self.assertNotIn("独立完成生产上线", out)
        self.assertNotIn("本人独立上线", out)
        self.assertTrue(any(c.get("applied") is False for c in r["polish"]["changes"]))
        self.assertLessEqual(len(r["revisions"]), 2)

    def test_employment_scope_and_education_drift(self):
        p = complete()
        p["basic"] += "\n工作经历：虚构甲公司 2024.01–2024.06"
        p["projects"][0] += "\n所属公司：虚构甲公司"
        self.assertIn("employer_period", [i["code"] for i in rr.review_profile(p)])
        p = complete()
        text, _ = rr.build_resume(p)
        review = rr.check_resume(p, text.replace("软件工程本科", "软件工程博士"))
        self.assertIn("basic_identity", [i["code"] for i in review["issues"]])

    def test_four_actual_pages_block_an_edited_resume(self):
        p = complete()
        text, r = rr.build_resume(p)
        large = text.replace("交付领用核对单。", "交付领用核对单。\n" * 150)
        review = rr.check_resume(p, large)
        self.assertGreater(review["artifacts"]["pdf"]["pages"], 3)
        self.assertIn("layout", [i["code"] for i in review["issues"]])


if __name__ == "__main__":
    unittest.main()
