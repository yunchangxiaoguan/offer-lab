"""Local student records and teacher releases. Only published card fields are shared."""

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from contextlib import contextmanager


def pack(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value):
    return hashlib.sha256(pack(value).encode()).hexdigest()


def directory():
    path = os.getenv("OFFER_DATA_DIR")
    return (
        Path(path)
        if path
        else Path(os.getenv("LOCALAPPDATA") or Path.home()) / "OfferLab"
    )


@contextmanager
def db(write=False):
    conn = sqlite3.connect(directory() / "workspace.sqlite3", timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    directory().mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, owner TEXT NOT NULL,
            kind TEXT NOT NULL, parent INTEGER, body TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS records_owner ON records(owner,kind,id);
        CREATE TABLE IF NOT EXISTS generation_jobs(owner TEXT NOT NULL, job TEXT NOT NULL,
            record_id INTEGER, PRIMARY KEY(owner, job));
        CREATE TABLE IF NOT EXISTS generation_parts(owner TEXT NOT NULL, job TEXT NOT NULL,
            part TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(owner, job, part));
        CREATE TABLE IF NOT EXISTS resume_files(record_id INTEGER PRIMARY KEY,
            pdf BLOB NOT NULL, docx BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,owner TEXT NOT NULL,
            scope TEXT NOT NULL, qid TEXT NOT NULL, card TEXT NOT NULL, selected INTEGER NOT NULL,
            created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS attempts_owner ON attempts(owner,id);
        CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY,fingerprint TEXT UNIQUE NOT NULL,
            body TEXT NOT NULL,published INTEGER DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP);
        """)


def add(c, owner, kind, body, parent=None):
    return c.execute(
        "INSERT INTO records(owner,kind,parent,body) VALUES(?,?,?,?)",
        (owner, kind, parent, pack(body)),
    ).lastrowid


def get(c, owner, key, kinds):
    row = c.execute(
        "SELECT * FROM records WHERE owner=? AND id=?", (owner, key)
    ).fetchone()
    if not row or row["kind"] not in kinds:
        raise ValueError("找不到所选版本，请刷新后重试。")
    return json.loads(row["body"])


def split_projects(text):
    text = text.replace("\r\n", "\n").strip()
    markers = r"(?:项目\s*[一二三四五六七八九十\d]+(?:\s*名称)?|第[一二三四五六七八九十\d]+个?项目|项目名称|project\s*\d+)"
    heads = list(
        re.finditer(
            r"(?im)^[ \t]*(?:#{1,4}[ \t]*)?(?:"
            + markers
            + r")[ \t]*(?:[：:、.．)）|｜—-][ \t]*|(?=\s|$))",
            text,
        )
    )
    if len(heads) < 2:
        if len(heads) == 1 and heads[0].start() == 0:
            # One labelled multi-line project is a legitimate unfinished profile.
            return [text]
        heads = list(
            re.finditer(
                r"(?m)^[ \t]*(?:#{1,4}[ \t]*|(?:[1-5][.、)）]|[一二三四五]、)[ \t]*)\S",
                text,
            )
        )
    if len(heads) >= 2:
        return [
            text[
                h.start() : heads[i + 1].start() if i + 1 < len(heads) else len(text)
            ].strip()
            for i, h in enumerate(heads)
        ]
    blocks = [
        v.strip()
        for v in re.split(r"\n[ \t]*(?:[-=]{3,}[ \t]*\n|\n+)", text)
        if v.strip()
    ]
    if len(blocks) == 1 and not re.search(
        r"(?m)^\s*(?:本人|职责|背景|用户|难点|技术|结果|交付|验证)[^：:\n]{0,6}[：:]",
        text,
    ):
        blocks = [v.strip() for v in text.splitlines() if v.strip()]
    return blocks


def profile(body):
    basic = body.get("basic", "")
    projects = body.get("projects", [])
    standard = body.get("standard", "auto")
    if standard not in ("auto", "job", "class"):
        raise ValueError("请选择当前资料使用的简历标准。")
    if not isinstance(basic, str) or len(basic) > 20000:
        raise ValueError("基本信息限两万字。")
    if (
        not isinstance(projects, list)
        or len(projects) > 5
        or any(
            not isinstance(x, str) or not x.strip() or len(x) > 30000 for x in projects
        )
    ):
        raise ValueError("最多可保存 5 个非空项目，每个项目限三万字。")
    if not basic.strip() and not projects:
        raise ValueError("请先粘贴基本信息或一段项目资料。")
    name = re.search(r"(?:姓名|称呼|名字)\s*[:：]\s*([^，,、；;\s|｜]{1,30})", basic)
    return {
        "name": name[1] if name else "",
        "basic": basic.strip(),
        "projects": [x.strip() for x in projects],
        "standard": standard,
    }


def backup(c, owner):
    records = [
        {**dict(r), "body": json.loads(r["body"])}
        for r in c.execute(
            "SELECT id,kind,parent,body,created FROM records WHERE owner=? ORDER BY id",
            (owner,),
        )
    ]
    attempts = [
        {**dict(r), "card": json.loads(r["card"])}
        for r in c.execute(
            "SELECT scope,qid,card,selected,created FROM attempts WHERE owner=? ORDER BY id",
            (owner,),
        )
    ]
    return {"format": "offer-lab-student-v1", "records": records, "attempts": attempts}


def restore(c, owner, payload):
    if (
        payload.get("format") != "offer-lab-student-v1"
        or not isinstance(payload.get("records"), list)
        or not isinstance(payload.get("attempts"), list)
    ):
        raise ValueError("无法识别这个学生备份文件。")
    from practice import _valid_card

    ids = {}
    kinds = {}

    def mapped(value, expected):
        if not isinstance(value, (int, str)) or not str(value).isdigit():
            raise ValueError("备份中的版本编号无效。")
        key = int(value)
        if kinds.get(key) != expected:
            raise ValueError("备份中的版本关系不完整。")
        return ids[key]

    def card_ok(q):
        if not _valid_card(q) or not isinstance(q.get("id"), str) or not q["id"]:
            raise ValueError("备份中的题目不完整。")
        tags = q.get("tags", [])
        related = q.get("related", [])
        if (
            not isinstance(tags, list)
            or not all(isinstance(t, str) for t in tags)
            or not isinstance(related, list)
            or not all(
                isinstance(p, dict)
                and all(isinstance(p.get(k), str) for k in ("topic", "subtopic"))
                for p in related
            )
        ):
            raise ValueError("备份中的题目分类无效。")

    def choice_ok(item):
        if (
            not isinstance(item, dict)
            or type(item.get("selected")) is not int
            or not 0 <= item["selected"] <= 3
        ):
            raise ValueError("备份中的作答记录无效。")
        card_ok(item.get("card"))

    for item in payload["records"]:
        if (
            not isinstance(item, dict)
            or type(item.get("id")) is not int
            or item["id"] in ids
        ):
            raise ValueError("备份含无效记录。")
        kind = item.get("kind")
        if kind not in (
            "profile",
            "resume",
            "five",
            "eighteen",
            "set",
            "mock",
        ) or not isinstance(item.get("body"), dict):
            raise ValueError("备份含无效记录。")
        body = item["body"].copy()
        parent = None
        if kind == "profile":
            body = profile(body)
        if kind in ("resume", "five", "eighteen"):
            if not isinstance(body.get("text"), str) or not isinstance(
                body.get("mode"), str
            ):
                raise ValueError("材料正文无效。")
            parent = mapped(item.get("parent"), "profile")
            body["profile_id"] = mapped(body.get("profile_id"), "profile")
            if body["profile_id"] != parent:
                raise ValueError("备份中的资料版本不一致。")
            if body.get("based_on") is not None:
                body["based_on"] = mapped(body["based_on"], "resume")
            if body.get("five_id") is not None:
                body["five_id"] = mapped(body["five_id"], "five")
            if (kind == "resume" and body.get("based_on")) or (
                kind != "eighteen" and body.get("five_id")
            ):
                raise ValueError("备份中的材料依赖类型无效。")
            if body.get("based_on"):
                resume = get(c, owner, body["based_on"], ("resume",))
                if resume["profile_id"] != parent:
                    raise ValueError("备份中的简历与资料不一致。")
            if body.get("five_id"):
                five = get(c, owner, body["five_id"], ("five",))
                if (
                    five.get("based_on") != body.get("based_on")
                    or five["profile_id"] != parent
                ):
                    raise ValueError("备份中的两份面试稿依据不一致。")
            # Restored reviews are supplied by the uploader. Recheck the local copy.
            body = {
                k: body[k]
                for k in ("profile_id", "based_on", "five_id", "text", "mode")
                if k in body
            }
        if kind == "set":
            parent = mapped(item.get("parent"), "resume")
            if not isinstance(body.get("cards"), list):
                raise ValueError("题集格式无效。")
            for q in body["cards"]:
                card_ok(q)
        if kind == "mock":
            if (
                not isinstance(body.get("history"), list)
                or not isinstance(body.get("pool"), list)
                or type(body.get("limit")) is not int
                or not 1 <= body["limit"] <= 6
                or "current" not in body
            ):
                raise ValueError("模拟面试格式无效。")
            for q in body["pool"]:
                card_ok(q)
            for entry in body["history"]:
                choice_ok(entry)
            if body["current"] is not None:
                card_ok(body["current"])
            if body.get("scope") != "public":
                body["scope"] = str(mapped(body.get("scope"), "set"))
        ids[item["id"]] = add(c, owner, kind, body, parent)
        kinds[item["id"]] = kind
        if isinstance(item.get("created"), str):
            c.execute(
                "UPDATE records SET created=? WHERE id=?",
                (item["created"], ids[item["id"]]),
            )
    for a in payload["attempts"]:
        choice_ok(a)
        scope = (
            "public"
            if a.get("scope") == "public"
            else str(mapped(a.get("scope"), "set"))
        )
        if a.get("qid") != a["card"]["id"] or not isinstance(a.get("created"), str):
            raise ValueError("备份中的作答记录无效。")
        c.execute(
            "INSERT INTO attempts(owner,scope,qid,card,selected,created) VALUES(?,?,?,?,?,?)",
            (owner, scope, a["qid"], pack(a["card"]), a["selected"], a["created"]),
        )
    return len(ids)
