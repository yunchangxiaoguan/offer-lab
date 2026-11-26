import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import interview_scripts as scripts  # noqa: E402
import resume_review  # noqa: E402
from test_materials import sample  # noqa: E402


def official_script(mode):
    folder = (
        "write-five-point-interview"
        if mode == "five"
        else "write-eighteen-point-interview"
    )
    found = list(
        (ROOT.parent / "skill").glob(
            f"面试稿Skills_v1.2*/skills/{folder}/scripts/validate_interview.py"
        )
    )
    return found[0] if found else None


class ScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.person = {**sample(), "standard": "job"}
        cls.resume, cls.resume_review = resume_review.build_resume(cls.person)
        cls.five, cls.freview = scripts.build_script("five", cls.person, cls.resume)
        cls.eighteen, cls.ereview = scripts.build_script(
            "eighteen", cls.person, cls.resume, cls.five
        )

    def test_selected_resume_end_to_end_role_and_checks(self):
        self.assertEqual(self.resume_review["status"], "ready")
        for report in (self.freview, self.ereview):
            self.assertEqual(report["status"], "ready", report["issues"])
            self.assertIn("仓储售后", report["main_project"])
        intro = scripts._intro_text(self.five)
        self.assertEqual(intro, scripts._intro_text(self.eighteen))
        for area in (intro, scripts._portion(self.five, "## 三、主项目", "## 四、")):
            for term in (
                "工具调用",
                "提交前人工确认",
                "回执查询",
                "业务标识",
                "优先查询回执",
                "重复请求",
                "工单入口",
            ):
                self.assertIn(term, area)
        self.assertNotIn("本人工作：其他组员", self.five)
        self.assertNotIn("87%", self.eighteen)
        damaged = self.five.replace(
            "本人工作：我负责工具调用、提交前人工确认和回执查询",
            "本人工作：其他组员负责工单入口",
        )
        self.assertIn(
            "role_evidence",
            {
                i["code"]
                for i in scripts.check_script(
                    "five", self.person, self.resume, damaged
                )["issues"]
            },
        )

    def test_original_teacher_validator_on_two_generated_files(self):
        if not official_script("five") or not official_script("eighteen"):
            self.skipTest("老师提供的本地参考包不随公开仓分发")
        with TemporaryDirectory() as tmp:
            for mode, doc in (("five", self.five), ("eighteen", self.eighteen)):
                file = Path(tmp) / f"虚构样例-{mode}.md"
                file.write_text(doc, encoding="utf8")
                run = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        str(official_script(mode)),
                        str(file),
                        "--mode",
                        mode,
                    ],
                    capture_output=True,
                    encoding="utf8",
                    timeout=20,
                )
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                result = json.loads(run.stdout)
                self.assertTrue(result["passed"])
                if mode == "eighteen":
                    self.assertEqual(result["oral_points_complete"], 18)
                    self.assertEqual(
                        sum(map(len, result["estimated_spoken_seconds"].values())), 21
                    )

    def test_removed_project_or_fact_is_not_rehydrated(self):
        selected = re.sub(r"(?ms)^### 发票 OCR 复核\n.*?(?=^## |\Z)", "", self.resume)
        selected = selected.replace("保存业务标识并优先查询回执。", "")
        five, review = scripts.build_script("five", self.person, selected)
        self.assertNotIn("保存业务标识并优先查询回执", five)
        self.assertNotIn("发票 OCR 复核", five)
        self.assertEqual(review["status"], "ready", review["issues"])
        self.assertEqual(
            scripts.build_script("five", self.person, "")[1]["status"], "draft"
        )

    def test_selected_online_resume_with_combined_unlabelled_clauses(self):
        src = """# 练习同学

## 项目经历

### 仓储售后 Agent
仓库人员需要查验补货请求，物流异常时会重复提交。
在采用 Python、LangGraph 的项目中，负责工具调用、提交前人工确认和回执查询。
订单进入后，先查询状态，再生成待确认的处理建议。
接口超时时，下游可能已经受理。
保存业务标识，并优先查询回执。
交付审批与发货回执页面。
验证：在本地用重复请求检查同一工单是否只产生一次受理记录。
分工：其他组员负责工单入口。

### 设备手册 RAG 问答
车间工程师需要按设备型号与生产日期核对维护说明，难点在于旧版与新版条款描述接近，检索结果偶尔混用。我负责按标题切分手册，保留页码和生效日期，再按设备编号过滤检索结果；在召回前筛选适用版本，重排后检查最终引用页。
交付的问答结果能够回看原文。验证时抽取同一设备的跨版本问题，逐条核对返回的生效日期。

### 发票 OCR 复核
财务逐张核对纸质发票的币种、金额与税率，跨页表头容易遗漏。
负责把低置信字段交给财务人员复核。
交付能回查原图的复核清单。"""
        profile = {"name": "练习同学", "projects": []}
        _, _, ordered = scripts._setup(profile, src)
        self.assertEqual(ordered[0][0].title, "仓储售后 Agent")
        actual = {p.title: c["actual"] for p, c in ordered}
        self.assertEqual(
            actual["仓储售后 Agent"]["role"], "我负责工具调用、提交前人工确认和回执查询"
        )
        self.assertEqual(actual["仓储售后 Agent"]["tech"], "Python、LangGraph")
        self.assertEqual(actual["仓储售后 Agent"]["scope"], "其他组员负责工单入口")
        self.assertTrue(
            actual["设备手册 RAG 问答"]["background"].startswith("车间工程师需要")
        )
        self.assertTrue(actual["设备手册 RAG 问答"]["issue"].startswith("旧版与新版"))
        for kind in ("five", "eighteen"):
            _, report = scripts.build_script(kind, profile, src)
            self.assertEqual(report["status"], "ready", report["issues"])
            self.assertEqual(report["main_project"], "仓储售后 Agent")
        amended = src.replace("负责工具调用", "同事负责工具调用")
        agent = next(
            c
            for p, c in scripts._setup(profile, amended)[2]
            if p.title == "仓储售后 Agent"
        )
        self.assertFalse(agent["fact_quality"]["role"])

    def test_section_repair_preserves_independent_edits(self):
        name, target, ordered = scripts._setup(self.person, self.resume)
        p, c = ordered[0]
        rows = scripts._rows(c)
        rows[1]["answer"] = rows[0]["answer"]
        rows[2]["answer"] += "我会请使用者用自己的话重述一下这个条件，再一起确认。"
        kept = rows[2]["answer"]
        text, review, repairs = scripts._finish(
            "eighteen",
            self.person,
            self.resume,
            self.five,
            name,
            p,
            c,
            [x for _, x in ordered[1:]],
            scripts._intro(name, target, c),
            rows,
        )
        self.assertEqual(review["status"], "ready", review["issues"])
        self.assertIn(kept, text)
        self.assertEqual(len(repairs), 1)
        self.assertTrue(repairs[0]["applied"])
        self.assertEqual(
            [(v["section"], v["field"]) for v in repairs[0]["changes"]],
            [(rows[1]["title"], "主答")],
        )
        self.assertNotEqual(
            repairs[0]["changes"][0]["before"], repairs[0]["changes"][0]["after"]
        )

    def test_model_pair_replies_have_independent_fact_checks(self):
        _, _, ordered = scripts._setup(self.person, self.resume)
        p, c = ordered[0]
        row = scripts._rows(c)[0]
        source = "\n".join(v for _, v in p.facts)
        replies = [
            [q, a + "具体口径可以和这条记录再核一次。"] for q, a in row["followups"]
        ]
        revised, changes, rejections = scripts._rewrite_row(
            {"answer": row["answer"] + "我负责全部模型开发。", "replies": replies},
            row,
            source,
        )
        self.assertEqual(revised["answer"], row["answer"])
        self.assertEqual(revised["followups"], replies)
        self.assertEqual([v["field"] for v in changes], ["第一层追答", "第二层追答"])
        self.assertEqual([v["field"] for v in rejections], ["主答"])
        self.assertIn("具体工作", rejections[0]["reason"])
        self.assertTrue(scripts._fact_error("我负责全部模型开发。", "我配合验收测试。"))
        self.assertTrue(
            scripts._fact_error(
                "线上准确率提升90%。", "本地核对20条，18条命中，命中率90%。"
            )
        )

    def test_missing_role_foreign_identity_and_unsupported_metrics(self):
        src = "# 练习同学\n\n## 项目经历\n\n### 虚构资料查询\n业务：员工需要查公示信息。\n分工：其他组员负责入口。\n交付：一份查询记录。"
        _, review = scripts.build_script("five", self.person, src)
        self.assertIn("role", {i["code"] for i in review["issues"]})
        with_ratio = self.five.replace(
            "## 九、综合面试稿与面试前核对",
            "## 九、综合面试稿与面试前核对\n\n我独立上线了服务，线上准确率提升90%。",
        )
        self.assertIn(
            "fact_drift",
            {
                i["code"]
                for i in scripts.check_script(
                    "five", self.person, self.resume, with_ratio
                )["issues"]
            },
        )
        self.assertEqual(
            scripts.check_script(
                "five", {**self.person, "name": "虚构乙"}, self.resume, self.five
            )["status"],
            "draft",
        )
        absent = self.eighteen.replace("## 12｜数据格式与样例", "## 12｜别的考点")
        self.assertEqual(
            scripts.check_script(
                "eighteen", self.person, self.resume, absent, self.five
            )["status"],
            "draft",
        )
        rows = re.findall(
            r"(?ms)^\*\*\d+\. [^\n]+?\*\*\s*\n(.*?)(?=^\*\*\d+\.|^## 九)", self.five
        )
        damaged = self.five.replace(rows[1], rows[0])
        self.assertIn(
            "repeated_answers",
            {
                i["code"]
                for i in scripts.check_script(
                    "five", self.person, self.resume, damaged
                )["issues"]
            },
        )

    def test_online_partial_resume_reuses_safe_rows_and_reverts_drift(self):
        calls = []
        saved = {}

        def provider(_system, user):
            self.assertNotIn("learner@example.test", user)
            self.assertNotIn("13000000000", user)
            self.assertNotIn("练习同学", user)
            rows = json.loads(user)["需口语化段落"]
            ids = [r["id"] for r in rows]
            calls.append(ids)
            if len(calls) == 2:
                raise ValueError("本组中断")
            answer = [
                {
                    "id": r["id"],
                    "answer": r["answer"],
                    "replies": [a for _, a in r["followups"]],
                }
                for r in rows
            ]
            if len(calls) == 1:
                answer[0]["answer"] += "我独立上线所有模块，线上准确率提升90%。"
            return json.dumps(answer, ensure_ascii=False)

        with patch.object(scripts.llm, "complete", side_effect=provider):
            doc, first = scripts.build_script(
                "five", self.person, self.resume, use_model=True, checkpoint=saved
            )
            self.assertEqual(first["status"], "draft")
            self.assertTrue(first["retryable"])
            self.assertNotIn("90%", doc)
            self.assertTrue(first["polishing"]["reverted_sections"])
            count = len(calls)
            again, last = scripts.build_script(
                "five", self.person, self.resume, use_model=True, checkpoint=saved
            )
            self.assertEqual(calls[count:], [calls[1]])
            self.assertEqual(last["status"], "ready", last["issues"])
            self.assertEqual(
                last["checkpoint"]["total"], last["checkpoint"]["completed"]
            )
            self.assertEqual(scripts._intro_text(again), scripts._intro_text(self.five))


if __name__ == "__main__":
    unittest.main()
