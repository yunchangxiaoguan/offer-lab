import os
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import service
import store


class SavedVersionsTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {"OFFER_DATA_DIR": temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        store.init()

    def test_invalid_backup_rolls_back_and_leaves_student_untouched(self):
        with store.db(True) as c:
            key = store.add(
                c,
                "original",
                "profile",
                store.profile(
                    {
                        "basic": "姓名：虚构学生",
                        "projects": ["图书检索", "订单核对", "售后记录"],
                    }
                ),
            )
            store.add(
                c,
                "original",
                "resume",
                {
                    "profile_id": key,
                    "based_on": None,
                    "mode": "手工修订",
                    "text": "样例正文",
                },
                key,
            )
            source = store.backup(c, "original")
        broken = deepcopy(source)
        broken["records"][-1]["body"]["profile_id"] = 9000
        with self.assertRaises(ValueError), store.db(True) as c:
            store.restore(c, "restored", broken)
        with store.db(True) as c:
            self.assertEqual([], store.backup(c, "restored")["records"])
            self.assertEqual(2, store.restore(c, "restored", source))
            result = store.backup(c, "restored")["records"]
            self.assertEqual(result[0]["id"], result[1]["body"]["profile_id"])
            self.assertEqual(source, store.backup(c, "original"))

    def test_retry_saves_only_if_teacher_draft_is_still_current(self):
        pending = {
            "question": "虚构项目中的图书排序如何验证？",
            "reason": "待处理",
            "retryable": True,
        }
        original = {"cards": [], "merged": [], "pending": [pending]}
        with store.db(True) as c:
            key = c.execute(
                "INSERT INTO batches(fingerprint, body) VALUES(?,?)",
                ("demo", store.pack({"preview": original})),
            ).lastrowid
        job = {"batch": key, "revision": store.digest(original), "use_model": True}

        def concurrent_edit(preview, known):
            with store.db(True) as c:
                preview["pending"][0]["reason"] = "老师已更新这条备注"
                service.save_preview(c, preview)
            return {"cards": [], "merged": [], "pending": []}

        with patch("llm.available", return_value=True):
            with patch("practice.retry_pending", side_effect=concurrent_edit):
                with self.assertRaisesRegex(ValueError, "其他窗口"):
                    service.retry_batch(job)
            with store.db() as c:
                draft = service.checked_draft(c, {"batch": key})
                self.assertEqual("老师已更新这条备注", draft["pending"][0]["reason"])
            with patch(
                "practice.retry_pending",
                return_value={"cards": [], "merged": [], "pending": []},
            ):
                result = service.retry_batch({**job, "revision": draft["revision"]})
            self.assertEqual([], result["pending"])
            with store.db() as c:
                self.assertEqual(result, service.checked_draft(c, {"batch": key}))
