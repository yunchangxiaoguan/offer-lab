import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import service
import store
import workflow


class MaterialWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.env = patch.dict(os.environ, {"OFFER_DATA_DIR": temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        store.init()

    def save(self, basic="姓名：虚构学生", projects=(), owner="me"):
        with store.db(True) as c:
            return workflow.save_profile(
                c, owner, {"basic": basic, "projects": list(projects)}
            )

    def test_partial_profile_and_actual_draft_cannot_unlock_script_or_questions(self):
        projects = ["图书检索", "仓库记录", "售后录入"]
        incomplete = self.save(projects=projects)
        self.assertTrue(incomplete["issues"])
        self.assertEqual(incomplete, self.save(projects=projects))
        key = incomplete["id"]
        with self.assertRaisesRegex(ValueError, "简历"):
            service.generate("me", {"kind": "five", "profile_id": key})
        draft = service.generate("me", {"kind": "resume", "profile_id": key})
        self.assertEqual("draft", draft["status"])
        for kind in ("five", "eighteen"):
            with self.assertRaises(workflow.MaterialBlocked) as raised:
                service.generate(
                    "me", {"kind": kind, "profile_id": key, "resume_id": draft["id"]}
                )
            self.assertTrue(raised.exception.issues)
        with self.assertRaises(workflow.MaterialBlocked):
            service.make_set("me", {"resume_id": draft["id"]})
        single = "项目一：图书检索\n背景：读者找不到旧书。\n职责：维护馆藏索引。"
        self.assertEqual([single], store.split_projects(single))
        self.assertTrue(self.save("", [single])["issues"])
        self.assertTrue(self.save()["issues"])

    def approved_resume(self, key, owner="me"):
        record = {
            "text": "虚构的已核对简历",
            "mode": "本机生成",
            "profile_id": key,
            "based_on": None,
        }
        workflow.attach_review(record, {"status": "ready", "issues": []})
        with store.db(True) as c:
            return store.add(c, owner, "resume", record, key)

    def test_script_sources_and_retry_checkpoint_after_disconnected_call(self):
        key = self.save()["id"]
        source = self.approved_resume(key)
        body = {"kind": "five", "profile_id": key, "resume_id": source}

        def interrupted(*args, checkpoint, **kwargs):
            checkpoint["part-1"] = {"text": "虚构的已核对段落"}
            raise ValueError("临时中断")

        def continued(*args, checkpoint, **kwargs):
            self.assertIn("part-1", checkpoint)
            return "完成稿", {"status": "ready", "issues": []}

        with patch("interview_scripts.build_script", side_effect=interrupted):
            with self.assertRaisesRegex(ValueError, "中断"):
                service.generate("me", body)
        with patch("interview_scripts.build_script", side_effect=continued):
            result = service.generate("me", body)
        self.assertEqual(result["id"], service.generate("me", body)["id"])
        alien_key = self.save("姓名：另一个虚构学生", owner="student2")["id"]
        foreign = self.approved_resume(alien_key, "student2")
        for bad_body in (
            {**body, "resume_id": foreign},
            {**body, "profile_id": self.save("姓名：修改过的资料")["id"]},
            {
                **body,
                "kind": "eighteen",
                "resume_id": self.approved_resume(key),
                "five_id": result["id"],
            },
        ):
            with self.assertRaises(ValueError):
                service.generate("me", bad_body)
        with patch(
            "interview_scripts.build_script",
            return_value=("另一版", {"status": "ready", "issues": []}),
        ):
            self.assertNotEqual(
                result["id"],
                service.generate("me", {**body, "request_id": "new-version"})["id"],
            )

    def test_concurrent_same_request_publishes_once(self):
        key = self.save()["id"]
        request = {
            "kind": "five",
            "profile_id": key,
            "resume_id": self.approved_resume(key),
            "request_id": "same",
        }
        barrier = Barrier(2)

        def build(*args, **kwargs):
            barrier.wait(timeout=10)
            return "同一虚构稿件", {"status": "ready", "issues": []}

        with (
            patch("interview_scripts.build_script", side_effect=build),
            ThreadPoolExecutor(max_workers=2) as workers,
        ):
            result = list(
                workers.map(lambda _: service.generate("me", request), range(2))
            )
        self.assertEqual(result[0]["id"], result[1]["id"])
        with store.db() as c:
            self.assertEqual(
                1,
                c.execute("SELECT count(*) FROM records WHERE kind='five'").fetchone()[
                    0
                ],
            )

    def test_edited_and_imported_claims_cannot_inherit_approval(self):
        key = self.save()["id"]
        source = self.approved_resume(key)
        changed = workflow.revise(
            "me",
            {"id": source, "text": "# 某人\n我独立上线，线上准确率提高90%。"},
            edit=True,
        )
        self.assertNotEqual(source, changed["id"])
        self.assertEqual("draft", changed["status"])
        with store.db(True) as c:
            self.assertEqual(
                "ready",
                workflow.material_info(store.get(c, "me", source, ("resume",)))[
                    "status"
                ],
            )
            data = deepcopy(store.backup(c, "me"))
            data["records"][-1]["body"]["review"]["status"] = "ready"
            store.restore(c, "new", data)
            restored = store.backup(c, "new")["records"][-1]
            self.assertEqual(
                "legacy", workflow.material_info(restored["body"])["status"]
            )
        with self.assertRaises(workflow.MaterialBlocked):
            service.make_set("new", {"resume_id": restored["id"]})
        self.assertEqual(
            "draft",
            workflow.revise("new", {"id": restored["id"]}, edit=False)["status"],
        )
