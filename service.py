"""Application operations shared by the local web entry points."""

import hashlib
import json
import random
import re
from functools import lru_cache

import llm
import store
import workflow

KINDS = workflow.KINDS
STUDENT_CARD = (
    "id",
    "title",
    "stage",
    "topic",
    "subtopic",
    "tags",
    "prompt",
    "options",
    "evidence",
    "project",
    "practice_step",
)
RELEASE_CARD = (
    "id",
    "title",
    "stage",
    "topic",
    "subtopic",
    "related",
    "tags",
    "prompt",
    "options",
    "correct",
    "reasons",
    "spoken",
    "followup",
    "followup_answer",
    "also_asked",
)


@lru_cache(maxsize=1)
def shipped():
    from bank import list_cards

    return {x["id"]: x for x in list_cards()}


def public_bank(c):
    cards = shipped().copy()
    for row in c.execute(
        "SELECT body FROM batches WHERE published>0 ORDER BY published,id"
    ):
        change = json.loads(row[0])["release"]
        for q in change["cards"]:
            cards[q["id"]] = q
        for item in change.get("merged", []):
            key = item["id"]
            if key in cards:
                old = cards[key]
                cards[key] = {
                    **old,
                    "also_asked": list(
                        dict.fromkeys(old.get("also_asked", []) + [item["question"]])
                    ),
                }
    return cards


def student_card(q):
    return {**{k: q[k] for k in STUDENT_CARD if k in q}, "revision": store.digest(q)}


def grade(q, choice):
    if type(choice) is not int or not 0 <= choice < 4:
        raise ValueError("请选择一个选项。")
    return {
        "card": student_card(q),
        "selected": choice,
        "correct": q["correct"],
        "reasons": q["reasons"],
        "spoken": q["spoken"],
        "followup": q.get("followup", ""),
        "followup_answer": q.get("followup_answer", ""),
    }


def saved_choice(c, owner, scope, q, choice):
    result = grade(q, choice)
    c.execute(
        "INSERT INTO attempts(owner,scope,qid,card,selected) VALUES(?,?,?,?,?)",
        (owner, str(scope), q["id"], store.pack(q), choice),
    )
    return result


def pool(c, owner, scope):
    if scope in ("", "public", None):
        return public_bank(c)
    cards = store.get(c, owner, scope, ("set",))["cards"]
    return {x["id"]: x for x in cards}


def get_question(c, owner, data):
    q = pool(c, owner, data.get("scope")).get(data.get("id"))
    if not q:
        raise ValueError("题目已更新，请重新选题。")
    if data.get("revision") and store.digest(q) != data["revision"]:
        raise ValueError("题目已改版，请重新打开题目。")
    return q


def state(c, owner, teacher):
    out = {k: [] for k in ("profiles", "materials", "sets", "sessions")}
    for row in c.execute(
        "SELECT id,kind,parent,created,body FROM records WHERE owner=? ORDER BY id DESC",
        (owner,),
    ):
        item = {k: row[k] for k in ("id", "kind", "parent", "created")}
        data = json.loads(row["body"])
        if row["kind"] == "profile":
            out["profiles"].append({**item, "name": data["name"]})
        elif row["kind"] in KINDS:
            info = workflow.material_info(data)
            out["materials"].append(
                {
                    **item,
                    "mode": data["mode"],
                    "based_on": data.get("based_on"),
                    "five_id": data.get("five_id"),
                    "status": info["status"],
                    "issues": info["issues"][:3],
                    "review": {
                        "status": info["status"],
                        "retryable": bool(info["review"].get("retryable")),
                    },
                }
            )
        elif row["kind"] == "set":
            out["sets"].append({**item, "count": len(data["cards"])})
        elif row["kind"] == "mock":
            out["sessions"].append(
                {
                    **item,
                    "done": data["current"] is None,
                    "count": len(data["history"]),
                    "scope": data["scope"],
                }
            )
    if out["profiles"]:
        out["profile"] = {
            "id": out["profiles"][0]["id"],
            **workflow.profile_info(
                store.get(c, owner, out["profiles"][0]["id"], ("profile",))
            ),
        }
    out.update(
        {
            "teacher": teacher,
            "model": llm.available(),
            "public_count": len(public_bank(c)),
        }
    )
    return out


def taxonomy():
    from bank import taxonomy as bank_taxonomy

    return bank_taxonomy()


def require_model(data):
    use = data.get("use_model", False)
    if not isinstance(use, bool):
        raise ValueError("生成方式无效。")
    if use and not llm.available():
        raise ValueError("请配置模型密钥或选择本机生成。")
    return use


def generate(owner, data):
    return workflow.generate(owner, data, require_model(data))


def make_set(owner, data):
    from practice import personal_cards

    key = data.get("resume_id")
    with store.db() as c:
        doc = workflow.approved(c, owner, key, "resume")
        profile = store.get(c, owner, doc["profile_id"], ("profile",))
    cards = personal_cards(profile, doc["text"], use_model=require_model(data))
    if not cards:
        raise ValueError("这版简历缺少可用于出题的项目事实，请补充本人职责后再生成。")
    with store.db(True) as c:
        return {
            "id": store.add(c, owner, "set", {"cards": cards}, key),
            "count": len(cards),
        }


def safe_mock(key, data):
    return {
        "id": key,
        "current": student_card(data["current"]) if data["current"] else None,
        "history": [grade(x["card"], x["selected"]) for x in data["history"]],
        "limit": data["limit"],
        "scope": data["scope"],
    }


def begin_mock(c, owner, data):
    from practice import mock_next

    scope = str(data.get("scope", "public"))
    items = list(pool(c, owner, scope).values())
    if scope == "public":
        topic = data.get("topic")
        if topic:
            items = [
                q
                for q in items
                if q.get("topic") == topic
                or any(
                    isinstance(r, dict) and r.get("topic") == topic
                    for r in q.get("related", [])
                )
            ]
    if not items:
        raise ValueError("当前范围没有可练的题。")
    random.SystemRandom().shuffle(items)
    limit = min(6, len(items))
    # Freeze a balanced pool for retries and later review, including personal evidence.
    if len(items) > 54:
        groups = {}
        for q in items:
            groups.setdefault(q.get("stage", ""), []).append(q)
        items = [
            q
            for i in range(54)
            for group in groups.values()
            if i < len(group)
            for q in [group[i]]
        ][:54]
    current = mock_next(items, [], limit=limit)
    if not current:
        raise ValueError("当前题目不足以组卷。")
    data = {
        "scope": scope,
        "limit": limit,
        "pool": items,
        "history": [],
        "current": current,
    }
    key = store.add(c, owner, "mock", data)
    return safe_mock(key, data)


def advance_mock(c, owner, data):
    from practice import mock_next

    key = data.get("session")
    exam = store.get(c, owner, key, ("mock",))
    q = exam["current"]
    if (
        q is None
        or q["id"] != data.get("id")
        or data.get("revision") != store.digest(q)
    ):
        raise ValueError("本题已提交或场次已更新，请重新打开本场。")
    saved_choice(c, owner, exam["scope"], q, data.get("selected"))
    exam["history"].append({"card": q, "selected": data["selected"]})
    exam["current"] = (
        mock_next(exam["pool"], exam["history"], limit=exam["limit"])
        if len(exam["history"]) < exam["limit"]
        else None
    )
    c.execute(
        "UPDATE records SET body=? WHERE owner=? AND id=?",
        (store.pack(exam), owner, key),
    )
    return safe_mock(key, exam)


def mistakes(c, owner):
    rows = c.execute(
        "SELECT a.* FROM attempts a JOIN (SELECT max(id) last FROM attempts WHERE owner=? GROUP BY scope,qid) g ON a.id=g.last ORDER BY a.id DESC",
        (owner,),
    )
    out = []
    for r in rows:
        q = json.loads(r["card"])
        if r["selected"] != q["correct"]:
            out.append({"attempt": r["id"], "scope": r["scope"], **student_card(q)})
    return out


def valid_card(q):
    if not isinstance(q, dict):
        raise ValueError("题卡格式无效。")
    for k in (
        "id",
        "title",
        "stage",
        "prompt",
        "spoken",
        "followup",
        "followup_answer",
    ):
        if not isinstance(q.get(k), str) or not q[k].strip():
            raise ValueError("题卡缺少必填项：" + k)
    for k in ("options", "reasons"):
        if (
            not isinstance(q.get(k), list)
            or len(q[k]) != 4
            or not all(isinstance(v, str) and v.strip() for v in q[k])
        ):
            raise ValueError("每道题需要四个选项和对应解释。")
    if (
        len(set(q["options"])) != 4
        or type(q.get("correct")) is not int
        or q["correct"] not in range(4)
    ):
        raise ValueError("选项或正确答案无效。")
    if not isinstance(q.get("tags", []), list) or not all(
        isinstance(v, str) for v in q.get("tags", [])
    ):
        raise ValueError("标签格式无效。")
    if not isinstance(q.get("also_asked", []), list) or not all(
        isinstance(v, str) for v in q.get("also_asked", [])
    ):
        raise ValueError("补充问法格式无效。")
    related = q.get("related", [])
    if not isinstance(related, list) or not all(
        isinstance(v, dict)
        and isinstance(v.get("topic"), str)
        and isinstance(v.get("subtopic"), str)
        for v in related
    ):
        raise ValueError("关联专题格式无效。")
    menu = taxonomy()
    stage, topic, subtopic = q["stage"], q.get("topic", ""), q.get("subtopic", "")
    if stage not in menu["stages"]:
        raise ValueError("请选择题库已有的面试环节。")
    optional = stage in ("自我介绍与履历", "项目业务与本人职责", "协作、行为与 HR")
    if not (optional and topic == subtopic == "") and (
        not isinstance(topic, str) or subtopic not in menu["topics"].get(topic, [])
    ):
        raise ValueError("请选择对应的技术专题和子类。")
    if any(v["subtopic"] not in menu["topics"].get(v["topic"], []) for v in related):
        raise ValueError("关联专题及子类不在题库目录中。")
    if q.get("scope") == "personal":
        raise ValueError("个人专属题不可发布到公共库。")
    result = {k: q[k] for k in RELEASE_CARD if k in q}
    if related:
        result["related"] = [
            {"topic": v["topic"], "subtopic": v["subtopic"]} for v in related
        ]
    return result


def checked_draft(c, data):
    row = c.execute("SELECT * FROM batches WHERE id=?", (data.get("batch"),)).fetchone()
    batch = batch_result(row)
    if batch["published"]:
        raise ValueError("此批已发布。")
    if data.get("revision") is not None and data["revision"] != batch["revision"]:
        raise ValueError("其他窗口已修改这批题，请重新查看后保存。")
    return batch


def save_preview(c, batch):
    preview = {k: batch[k] for k in ("cards", "merged", "pending")}
    c.execute(
        "UPDATE batches SET body=? WHERE id=?",
        (store.pack({"preview": preview}), batch["id"]),
    )
    return {**batch, "revision": store.digest(preview)}


def edit_draft(c, data):
    batch = checked_draft(c, data)
    kind = data.get("kind")
    index = data.get("index")
    if (
        kind not in ("cards", "merged")
        or type(index) is not int
        or not 0 <= index < len(batch[kind])
    ):
        raise ValueError("该候选项已经变更，请重新打开此批。")
    original = batch[kind][index]
    if original["id"] != data.get("id"):
        raise ValueError("题目已经变更，请重新打开此批。")
    if kind == "cards":
        submitted = data.get("card")
        if not isinstance(submitted, dict) or submitted.get("id") != original["id"]:
            raise ValueError("题号无效。")
        batch[kind][index] = {**original, **valid_card(submitted)}
    else:
        wording = data.get("question")
        if not isinstance(wording, str) or not 0 < len(wording.strip()) <= 1200:
            raise ValueError("请填写不超过 1200 字的补充问法。")
        batch[kind][index] = {**original, "question": wording.strip()}
    return save_preview(c, batch)


def complete_pending(c, data):
    from practice import manual_card

    preview = checked_draft(c, data)
    index = data.get("index")
    if type(index) is not int or not 0 <= index < len(preview["pending"]):
        raise ValueError("暂缓项已变更。")
    item = preview["pending"][index]
    if data.get("question") != item.get("question"):
        raise ValueError("暂缓项已变更，请刷新。")
    card = manual_card(item, data.get("card", {}))
    valid_card(card)
    if card["id"] in {x["id"] for x in preview["cards"]}:
        raise ValueError("此题已在本批。")
    preview["cards"].append(card)
    preview["pending"].pop(index)
    return save_preview(c, preview)


def prepare_batch(data):
    from practice import import_transcript

    raw = data.get("text", "")
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 400000:
        raise ValueError("请粘贴或导入有效文本，每批最多四十万字。")
    raw = raw.strip()
    fp = hashlib.sha256(re.sub(r"\s+", " ", raw).encode()).hexdigest()
    with store.db() as c:
        existing = c.execute(
            "SELECT * FROM batches WHERE fingerprint=?", (fp,)
        ).fetchone()
        if existing:
            return batch_result(existing)
        known = list(public_bank(c).values())
    result = import_transcript(raw, known, use_model=require_model(data))
    with store.db(True) as c:
        c.execute(
            "INSERT OR IGNORE INTO batches(fingerprint,body) VALUES(?,?)",
            (fp, store.pack({"preview": result})),
        )
        return batch_result(
            c.execute("SELECT * FROM batches WHERE fingerprint=?", (fp,)).fetchone()
        )


def retry_batch(data):
    from practice import retry_pending

    if not require_model(data):
        raise ValueError("请确认使用在线模型整理本批的待处理提问。")
    with store.db() as c:
        original = checked_draft(c, data)
        known = list(public_bank(c).values())
    result = retry_pending(original, known)
    with store.db(True) as c:
        current = checked_draft(
            c, {"batch": original["id"], "revision": original["revision"]}
        )
        return save_preview(c, {**current, **result})


def batch_result(row):
    if not row:
        raise ValueError("找不到该批次。")
    body = json.loads(row["body"])
    preview = body["preview"]
    result = {
        "id": row["id"],
        "published": bool(row["published"]),
        "revision": store.digest(preview),
    }
    if not row["published"]:
        from practice import can_retry

        return {
            **result,
            **preview,
            "pending": [{**q, "retryable": can_retry(q)} for q in preview["pending"]],
        }
    release = body["release"]
    omitted = {
        k: len(preview[k]) - len(release.get(k, []))
        for k in ("cards", "merged", "pending")
    }
    return {**result, **release, "pending": [], "omitted": omitted}


def batch_list(c):
    rows = c.execute(
        "SELECT id,created,published FROM batches ORDER BY published DESC,id DESC"
    )
    batches = [
        {"id": r["id"], "created": r["created"], "published": bool(r["published"])}
        for r in rows
    ]
    for i, batch in enumerate(batches):
        batch["can_undo"] = i == 0 and batch["published"]
    return batches


def undo(c, data):
    latest = c.execute(
        "SELECT id FROM batches WHERE published>0 ORDER BY published DESC,id DESC LIMIT 1"
    ).fetchone()
    if not latest or latest[0] != data.get("batch"):
        raise ValueError("可从最近发布的批次开始撤回。")
    c.execute("UPDATE batches SET published=0 WHERE id=?", (latest[0],))
    return {"ok": True}


def publish(c, data):
    row = c.execute("SELECT * FROM batches WHERE id=?", (data.get("batch"),)).fetchone()
    preview = batch_result(row)
    if preview["published"]:
        return {"id": row["id"]}
    if data.get("revision") is not None and data["revision"] != preview["revision"]:
        raise ValueError("其他窗口已修改本批，请重新核对后发布。")
    selected = data.get("cards", [])
    merged = data.get("merged", [])
    if not isinstance(selected, list) or not isinstance(merged, list):
        raise ValueError("无效的发布选择。")
    cards = [valid_card(x) for x in selected]
    base = public_bank(c)
    allowed = {q["id"]: q for q in preview["cards"]}
    if any(
        q["id"] not in allowed or q != valid_card(allowed[q["id"]]) for q in cards
    ) or len({q["id"] for q in cards}) != len(cards):
        raise ValueError("待发布题卡和本批草稿不一致，请先保存并重新核对。")
    if any(q["id"] in base and q != valid_card(base[q["id"]]) for q in cards):
        raise ValueError("有题号已经发布为其他内容，请核对后再发布。")
    aliases = []
    permitted = {(x["id"], x["question"]) for x in preview["merged"]}
    for item in merged:
        key = item.get("id")
        question = item.get("question", "").strip()
        if (
            (key, question) not in permitted
            or key not in (set(base) | {q["id"] for q in cards})
            or not question
        ):
            raise ValueError("已有题关联无效。")
        aliases.append({"id": key, "question": question})
    if not cards and not aliases:
        raise ValueError("请至少勾选一道新题或一种新问法。")
    updated = {
        "preview": {k: preview[k] for k in ("cards", "merged", "pending")},
        "release": {"cards": cards, "merged": aliases},
    }
    c.execute(
        "UPDATE batches SET body=?,published=(SELECT COALESCE(MAX(published),0)+1 FROM batches) WHERE id=?",
        (store.pack(updated), row["id"]),
    )
    return {"id": row["id"], "cards": len(cards), "merged": len(aliases)}
