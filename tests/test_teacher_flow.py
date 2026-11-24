"""Exercise the teacher release cycle using the real CLI and isolated local data."""

import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import unittest
from contextlib import contextmanager
from http.cookiejar import CookieJar
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request


ROOT = Path(__file__).resolve().parents[1]
SOURCE = """面试官：两个源文件同名，如何设计导出的文件目录以免覆盖？
候选人：这是 PRIVATE-TRANSCRIPT-ONLY，演示邮箱 user42@example.org。
面试官：跨页表格表头丢失的情况，入库之前该怎么处理？
"""
TITLE = "同名源文件的导出目录"
CARD = {
    "title": TITLE,
    "prompt": "两个来源都提交了同名文件，导出时要同时保留原文件名并避免覆盖，优先怎么组织？",
    "stage": "技术基础与实现",
    "topic": "后端与数据工程",
    "subtopic": "API 与任务队列",
    "options": [
        "按不可重复的来源标识分目录",
        "只写最后一个文件",
        "固定改成小写",
        "只调整列表的排序",
    ],
    "correct": 0,
    "reasons": [
        "不同来源具有独立目录。",
        "会覆盖在前的文件。",
        "小写也可能重名。",
        "排序不改变保存位置。",
    ],
    "spoken": "我会给每个来源分配稳定且唯一的标识，保留原文件名导出到各自的目录。再用两个同名样本检查能否分别取回，还要核对取回的内容。",
    "followup": "同一来源重复提交怎么处理？",
    "followup_answer": "先约定是覆盖还是保留版本。要保留版本时，再用版本号区分每次提交。",
}


@contextmanager
def application(data_dir, teacher):
    args = [sys.executable, "-X", "utf8", "-u", str(ROOT / "app.py"), "--port", "0"]
    if teacher:
        args.append("--teacher")
    env = {**os.environ, "OFFER_DATA_DIR": str(data_dir), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
    try:
        lines = queue.Queue()
        threading.Thread(
            target=lambda: lines.put(proc.stdout.readline()), daemon=True
        ).start()
        line = lines.get(timeout=15)
        address = re.search(r"http://127\.0\.0\.1:\d+/\S*", line)
        if not address:
            raise AssertionError(f"服务未启动。{line.strip()}")
        url = urlsplit(address[0])
        yield f"{url.scheme}://{url.netloc}", url.fragment.removeprefix("teacher=")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        proc.stdout.close()


class Client:
    def __init__(self, origin):
        self.origin = origin
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def api(self, route, data=None, **query):
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        params = "?" + urlencode(query) if query else ""
        request = Request(
            self.origin + "/api/" + route + params,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with self.opener.open(request, timeout=10) as response:
            return json.load(response)


class TeacherFlowTests(unittest.TestCase):
    def test_late_publication_aliases_and_persistent_edits(self):
        with (
            TemporaryDirectory() as tmp,
            application(tmp, teacher=True) as (origin, key),
        ):
            teacher, student = Client(origin), Client(origin)
            teacher.api("teacher/open", {"key": key})
            key = "teacher-test-source-file"
            phrasing = "用同名验收样本怎样检查来源目录？"
            ignored = "另一份样本的目录怎么检验？"

            def package(cards, merged):
                return {"format": "offer-lab-bank-v1", "cards": cards, "merged": merged}

            def rejected(route, data):
                with self.assertRaises(HTTPError) as failure:
                    teacher.api(route, data)
                self.assertEqual(failure.exception.code, 400)

            early = teacher.api(
                "teacher/package",
                package(
                    [],
                    [
                        {"id": key, "question": phrasing},
                        {"id": key, "question": ignored},
                    ],
                ),
            )
            raw = {**CARD, "id": key}
            for changes in (
                {"stage": "临时环节"},
                {"subtopic": "LangGraph"},
                {"topic": "", "subtopic": ""},
                {"related": [{"topic": "Agent 智能体", "subtopic": "缓存与失效"}]},
            ):
                rejected("teacher/package", package([{**raw, **changes}], []))
            later = teacher.api("teacher/package", package([raw], []))
            edit = {
                "batch": later["id"],
                "revision": later["revision"],
                "kind": "cards",
                "id": key,
                "index": 0,
            }
            changed = teacher.api(
                "teacher/draft", {**edit, "card": {**raw, "title": TITLE + "（复核）"}}
            )
            rejected("teacher/draft", {**edit, "card": raw})
            self.assertEqual(
                teacher.api("teacher/batch", id=later["id"])["cards"], changed["cards"]
            )
            rejected("teacher/publish", {"batch": later["id"], "cards": [raw]})
            teacher.api(
                "teacher/publish", {"batch": later["id"], "cards": changed["cards"]}
            )
            alias = phrasing.replace("验收样本", "验收案例")
            early = teacher.api(
                "teacher/draft",
                {
                    "batch": early["id"],
                    "revision": early["revision"],
                    "kind": "merged",
                    "id": key,
                    "index": 0,
                    "question": alias,
                },
            )
            teacher.api(
                "teacher/publish",
                {"batch": early["id"], "merged": [early["merged"][0]]},
            )
            snapshot = teacher.api("teacher/batch", id=early["id"])
            self.assertEqual(snapshot["merged"], [{"id": key, "question": alias}])
            self.assertEqual(snapshot["omitted"]["merged"], 1)
            self.assertEqual(
                teacher.api("teacher/export", id=early["id"])["merged"],
                snapshot["merged"],
            )
            self.assertEqual(
                [q["id"] for q in student.api("questions", query=alias)], [key]
            )
            self.assertFalse(student.api("questions", query=ignored))
            batches = teacher.api("teacher/batches")
            self.assertEqual([r["id"] for r in batches], [early["id"], later["id"]])
            self.assertEqual([r["can_undo"] for r in batches], [True, False])
            rejected("teacher/undo", {"batch": later["id"]})
            teacher.api("teacher/undo", {"batch": early["id"]})
            self.assertFalse(student.api("questions", query=alias))
            self.assertEqual(
                student.api("questions", query=TITLE)[0]["title"], TITLE + "（复核）"
            )
            self.assertEqual(
                len(teacher.api("teacher/batch", id=early["id"])["merged"]), 2
            )
            teacher.api("teacher/undo", {"batch": later["id"]})
            self.assertFalse(student.api("questions", query=TITLE))

    def test_review_publish_transfer_and_undo(self):
        with TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            with application(source_dir, teacher=True) as (origin, key):
                teacher, student = Client(origin), Client(origin)
                teacher.api("teacher/open", {"key": key})
                baseline = student.api("state")["public_count"]
                with self.assertRaises(HTTPError) as rejected:
                    student.api("teacher/batches")
                self.assertEqual(rejected.exception.code, 403)

                data = {"text": SOURCE, "use_model": False}
                draft = teacher.api("teacher/preview", data)
                self.assertEqual(len(draft["pending"]), 1)
                self.assertEqual(len(draft["merged"]), 1)
                self.assertEqual(
                    teacher.api("teacher/preview", data)["id"], draft["id"]
                )
                original = draft["pending"][0]["question"]
                manual = {
                    "batch": draft["id"],
                    "question": original,
                    "index": 0,
                    "card": CARD,
                }
                with self.assertRaises(HTTPError) as incomplete:
                    teacher.api(
                        "teacher/manual", {**manual, "card": {**CARD, "reasons": []}}
                    )
                self.assertEqual(incomplete.exception.code, 400)
                reviewed = teacher.api("teacher/manual", manual)
                self.assertFalse(reviewed["pending"])
                self.assertEqual(len(reviewed["cards"]), 1)
                self.assertEqual(student.api("questions", query=TITLE), [])
                qid = reviewed["cards"][0]["id"]
                alias = reviewed["merged"][0]
                release = {
                    "batch": draft["id"],
                    "cards": reviewed["cards"],
                    "merged": [alias],
                }
                self.assertEqual(teacher.api("teacher/publish", release)["cards"], 1)
                self.assertEqual(
                    teacher.api("teacher/publish", release)["id"], draft["id"]
                )
                self.assertTrue(teacher.api("teacher/preview", data)["published"])
                self.assertEqual(len(teacher.api("teacher/batches")), 1)
                self.assertEqual(student.api("state")["public_count"], baseline + 1)
                result = student.api(
                    "questions",
                    topic=CARD["topic"],
                    subtopic=CARD["subtopic"],
                    query=TITLE,
                )
                self.assertEqual([q["id"] for q in result], [qid])
                self.assertIn(
                    alias["id"],
                    [
                        q["id"]
                        for q in student.api("questions", query=alias["question"])
                    ],
                )
                visible = student.api("question", id=qid)
                self.assertEqual(visible["options"], CARD["options"])
                self.assertFalse({"correct", "spoken", "reasons"} & visible.keys())
                graded = student.api(
                    "answer",
                    {"id": qid, "revision": visible["revision"], "selected": 1},
                )
                self.assertEqual(
                    (graded["correct"], graded["spoken"]),
                    (CARD["correct"], CARD["spoken"]),
                )
                package = teacher.api("teacher/export", id=draft["id"])
                self.assertEqual(package["format"], "offer-lab-bank-v1")
                public_json = json.dumps(package, ensure_ascii=False)
                for private in (
                    "PRIVATE-TRANSCRIPT-ONLY",
                    "user42@",
                    "source_ref",
                    "review_question",
                    "pending",
                ):
                    self.assertNotIn(private, public_json)
                teacher.api("teacher/undo", {"batch": draft["id"]})
                self.assertEqual(student.api("questions", query=TITLE), [])
                self.assertEqual(student.api("state")["public_count"], baseline)

            receiver_dir = Path(tmp) / "receiver"
            with application(receiver_dir, teacher=True) as (origin, key):
                receiver = Client(origin)
                receiver.api("teacher/open", {"key": key})
                imported = receiver.api("teacher/package", package)
                self.assertFalse(imported["published"])
                self.assertFalse(receiver.api("questions", query=TITLE))
                self.assertEqual(
                    receiver.api("teacher/package", package)["id"], imported["id"]
                )
                receiver.api(
                    "teacher/publish",
                    {
                        "batch": imported["id"],
                        "cards": imported["cards"],
                        "merged": imported["merged"],
                    },
                )
                self.assertEqual(
                    receiver.api("teacher/export", id=imported["id"]), package
                )
                self.assertEqual(receiver.api("state")["public_count"], baseline + 1)
                self.assertEqual(receiver.api("questions", query=TITLE)[0]["id"], qid)

            with application(receiver_dir, teacher=False) as (origin, _):
                student = Client(origin)
                self.assertEqual(student.api("questions", query=TITLE)[0]["id"], qid)
                for route, data in [
                    ("teacher/batches", None),
                    ("teacher/open", {"key": "test"}),
                    ("teacher/package", package),
                    ("teacher/undo", {"batch": imported["id"]}),
                ]:
                    with (
                        self.subTest(route=route),
                        self.assertRaises(HTTPError) as rejected,
                    ):
                        student.api(route, data)
                    self.assertEqual(rejected.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
