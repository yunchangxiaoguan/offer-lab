"""Versioned student materials and the server-side release decisions."""

import hashlib
import json

import store

KINDS = ("resume", "five", "eighteen")
RULES = "materials-2026-11-26.1"


def material_info(record):
    review = record.get("review") or {}
    status = "legacy"
    if (
        record.get("rules") == RULES
        and review.get("status") in ("ready", "draft")
        and review.get("body_sha256")
        == hashlib.sha256(record["text"].encode()).hexdigest()
    ):
        status = review["status"]
    return {"status": status, "review": review, "issues": review.get("issues", [])}


def profile_info(profile):
    from resume_review import review_profile

    return {**profile, "issues": review_profile(profile)}


def save_profile(c, owner, data):
    profile = store.profile(data)
    last = c.execute(
        "SELECT id,body FROM records WHERE owner=? AND kind='profile' ORDER BY id DESC LIMIT 1",
        (owner,),
    ).fetchone()
    key = (
        last["id"]
        if last and json.loads(last["body"]) == profile
        else store.add(c, owner, "profile", profile)
    )
    return {"id": key, "issues": profile_info(profile)["issues"]}


class MaterialBlocked(ValueError):
    def __init__(self, message, issues=()):
        super().__init__(message)
        self.issues = list(issues)


def approved(c, owner, key, kind, profile_id=None):
    label = "简历" if kind == "resume" else "五点稿"
    if not key:
        raise MaterialBlocked(f"请先选择已通过核对的{label}版本。")
    record = store.get(c, owner, key, (kind,))
    if profile_id is not None and record["profile_id"] != profile_id:
        raise MaterialBlocked(f"{label}与所选资料版本不一致。")
    info = material_info(record)
    if info["status"] != "ready":
        raise MaterialBlocked(f"这版{label}需要先完成核对。", info["issues"])
    return record


def script_sources(c, owner, kind, profile_id, resume_id, five_id, find_five=False):
    resume = approved(c, owner, resume_id, "resume", profile_id)
    if kind == "five":
        return resume["text"], None, None
    if find_five and five_id is None:
        rows = c.execute(
            "SELECT id,body FROM records WHERE owner=? AND parent=? AND kind='five' ORDER BY id DESC",
            (owner, profile_id),
        )
        for row in rows:
            five = json.loads(row["body"])
            if (
                five.get("based_on") == resume_id
                and material_info(five)["status"] == "ready"
            ):
                five_id = row["id"]
                break
    five = approved(c, owner, five_id, "five", profile_id)
    if five.get("based_on") != resume_id:
        raise MaterialBlocked("五点稿与所选简历版本不一致。")
    return resume["text"], five["text"], five_id


class Checkpoint(dict):
    """Persist each accepted section before sending the next model request."""

    def __init__(self, owner, job):
        self.owner, self.job = owner, job
        with store.db() as c:
            super().__init__(
                (row[0], json.loads(row[1]))
                for row in c.execute(
                    "SELECT part,body FROM generation_parts WHERE owner=? AND job=?",
                    (owner, job),
                )
            )

    def __setitem__(self, key, value):
        with store.db(True) as c:
            c.execute(
                "INSERT OR REPLACE INTO generation_parts VALUES(?,?,?,?)",
                (self.owner, self.job, key, store.pack(value)),
            )
        super().__setitem__(key, value)


def attach_review(record, review):
    if review.get("status") not in ("ready", "draft"):
        raise ValueError("核对结果不完整，请重新生成。")
    body_hash = hashlib.sha256(record["text"].encode()).hexdigest()
    if review.get("body_sha256", body_hash) != body_hash:
        raise ValueError("正文在核对后发生变化，请重新核对。")
    record["rules"] = RULES
    record["review"] = {**review, "body_sha256": body_hash}


def keep_files(c, key, kind, record, files):
    if kind != "resume":
        return
    if record["review"]["status"] == "ready" and not (
        files.get("pdf") and files.get("docx")
    ):
        raise ValueError("尚未取得本次核对的 Word 和 PDF，请重试。")
    if files.get("pdf") and files.get("docx"):
        checks = record["review"].get("artifacts", {})
        for fmt in ("docx", "pdf"):
            if hashlib.sha256(files[fmt]).hexdigest() != checks.get(fmt, {}).get(
                "sha256"
            ):
                raise ValueError("下载文件与刚刚核对的版本不一致，请重新核对。")
        c.execute(
            "INSERT OR REPLACE INTO resume_files VALUES(?,?,?)",
            (key, files["pdf"], files["docx"]),
        )


def job_result(c, owner, job):
    row = c.execute(
        "SELECT r.id,r.body FROM generation_jobs j JOIN records r ON r.id=j.record_id AND r.owner=j.owner "
        "WHERE j.owner=? AND j.job=?",
        (owner, job),
    ).fetchone()
    if row:
        return {
            "id": row["id"],
            **material_info(json.loads(row["body"])),
            "reused": True,
        }


def generate(owner, data, use_model):
    kind, key = data.get("kind"), data.get("profile_id")
    if kind not in KINDS:
        raise ValueError("未知的材料类型。")
    request_id = data.get("request_id", "")
    if not isinstance(request_id, str) or len(request_id) > 160:
        raise ValueError("此生成请求编号无效。")
    source = data.get("resume_id") if kind != "resume" else None
    five_id = data.get("five_id") if kind == "eighteen" else None
    with store.db() as c:
        profile = store.get(c, owner, key, ("profile",))
        if kind != "resume":
            if not source:
                raise MaterialBlocked(
                    "请先选择通过核对的简历版本。", profile_info(profile)["issues"]
                )
            resume, five_text, five_id = script_sources(
                c, owner, kind, key, source, five_id, find_five=True
            )
        job = store.digest([RULES, kind, key, source, five_id, use_model, request_id])
        saved = job_result(c, owner, job)
        if saved and not saved["review"].get("retryable"):
            return saved
    files = {}
    if kind == "resume":
        from resume_review import build_resume

        text, review = build_resume(profile, use_model=use_model, artifacts=files)
    else:
        from interview_scripts import build_script

        text, review = build_script(
            kind,
            profile,
            resume,
            five_text=five_text,
            use_model=use_model,
            checkpoint=Checkpoint(owner, job),
        )
    record = {
        "profile_id": key,
        "based_on": source,
        "five_id": five_id,
        "text": text,
        "mode": "模型生成" if use_model else "本机生成",
    }
    attach_review(record, review)
    with store.db(True) as c:
        if kind != "resume":
            script_sources(c, owner, kind, key, source, five_id)
        concurrent = job_result(c, owner, job)
        if concurrent and (
            not concurrent["review"].get("retryable")
            or review.get("retryable")
            and saved
            and concurrent["id"] != saved["id"]
        ):
            return concurrent
        if concurrent and concurrent["review"] == record["review"]:
            return concurrent
        result_id = store.add(c, owner, kind, record, key)
        keep_files(c, result_id, kind, record, files)
        c.execute(
            "INSERT OR REPLACE INTO generation_jobs VALUES(?,?,?)",
            (owner, job, result_id),
        )
        if not review.get("retryable"):
            c.execute(
                "DELETE FROM generation_parts WHERE owner=? AND job=?", (owner, job)
            )
        return {"id": result_id, **material_info(record)}


def revise(owner, data, edit):
    key = data.get("id")
    with store.db() as c:
        record = store.get(c, owner, key, KINDS)
        kind = c.execute("SELECT kind FROM records WHERE id=?", (key,)).fetchone()[0]
        profile_id = record["profile_id"]
        profile = store.get(c, owner, profile_id, ("profile",))
        text = data.get("text") if edit else record["text"]
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 300000:
            raise ValueError("正文为空或过长。")
        text = text.strip() if edit else text
        files = {}
        if kind == "resume":
            from resume_review import check_resume

            review = check_resume(profile, text, artifacts=files)
        else:
            try:
                resume, five_text, _ = script_sources(
                    c,
                    owner,
                    kind,
                    profile_id,
                    record.get("based_on"),
                    record.get("five_id"),
                )
            except MaterialBlocked as exc:
                review = {
                    "status": "draft",
                    "issues": [
                        {
                            "code": "source_version",
                            "message": str(exc),
                            "section": "生成依据",
                            "source": "请先核对该稿原先使用的版本，或从当前简历生成新稿。",
                        },
                        *exc.issues,
                    ],
                }
            else:
                from interview_scripts import check_script

                review = check_script(kind, profile, resume, text, five_text=five_text)
    record["text"] = text
    attach_review(record, review)
    with store.db(True) as c:
        if edit:
            record["mode"] = "手工修订"
            record["edited_from"] = key
            key = store.add(c, owner, kind, record, profile_id)
        else:
            c.execute(
                "UPDATE records SET body=? WHERE owner=? AND id=?",
                (store.pack(record), owner, key),
            )
        keep_files(c, key, kind, record, files)
    return {"id": key, **material_info(record)}
