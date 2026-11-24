import argparse
import hmac
import json
import mimetypes
import re
import secrets
import sys
import threading
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import service
import store

STATIC = Path(__file__).resolve().parent / "web"
FILES = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(
        self, data, status=200, ctype="application/json; charset=utf-8", filename=None
    ):
        body = data if isinstance(data, bytes) else store.pack(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        if filename:
            self.send_header(
                "Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename)
            )
        if getattr(self, "new_cookie", False):
            self.send_header(
                "Set-Cookie",
                f"offerlab_user={self.owner}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000",
            )
        if getattr(self, "new_teacher", False):
            self.send_header(
                "Set-Cookie",
                f"offerlab_teacher={self.server.teacher_cookie}; HttpOnly; SameSite=Strict; Path=/",
            )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, post):
        try:
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in hosts:
                return self.reply({"error": "本服务仅支持本机访问。"}, 403)
            origin = self.headers.get("Origin")
            if post and origin and origin not in {"http://" + host for host in hosts}:
                return self.reply({"error": "请求来源不匹配。"}, 403)
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            user = cookies.get("offerlab_user")
            self.new_cookie = not user or not re.fullmatch(r"[0-9a-f]{48}", user.value)
            self.owner = secrets.token_hex(24) if self.new_cookie else user.value
            tc = cookies.get("offerlab_teacher")
            self.teacher = bool(
                self.server.teacher_enabled
                and tc
                and hmac.compare_digest(tc.value, self.server.teacher_cookie)
            )
            url = urlsplit(self.path)
            path = url.path
            if not post and path in FILES:
                filename = FILES[path]
                return self.reply(
                    (STATIC / filename).read_bytes(),
                    ctype=mimetypes.guess_type(filename)[0] + "; charset=utf-8",
                )
            data = {k: v[-1] for k, v in parse_qs(url.query).items()}
            if post:
                if self.headers.get_content_type() != "application/json":
                    return self.reply({"error": "需要 JSON 请求。"}, 415)
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 12_000_000:
                    return self.reply({"error": "请求数据过大或为空。"}, 413)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("无效的请求。")
            if path == "/api/teacher/open" and post:
                if not self.server.teacher_enabled or not hmac.compare_digest(
                    str(data.get("key", "")), self.server.teacher_key
                ):
                    return self.reply({"error": "请使用教师维护入口。"}, 403)
                self.new_teacher = True
                return self.reply({"ok": True})
            if path.startswith("/api/teacher/") and not self.teacher:
                return self.reply({"error": "请从教师维护入口打开。"}, 403)
            if not post:
                return self.read(path, data)
            if path == "/api/generate":
                return self.reply(service.generate(self.owner, data))
            if path == "/api/personal":
                return self.reply(service.make_set(self.owner, data))
            if path == "/api/teacher/preview":
                return self.reply(service.prepare_batch(data))
            if path == "/api/teacher/retry":
                return self.reply(service.retry_batch(data))
            with store.db(True) as c:
                result = self.write(c, path, data)
            return self.reply(result)
        except (ValueError, KeyError, TypeError) as exc:
            return self.reply({"error": str(exc)[:400]}, 400)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass
        except Exception as exc:
            print("服务异常", type(exc).__name__, file=sys.stderr, flush=True)
            return self.reply(
                {"error": "本机服务未能完成操作，请检查启动窗口或稍后重试。"}, 500
            )

    def read(self, path, d):
        with store.db() as c:
            if path == "/api/state":
                return self.reply(service.state(c, self.owner, self.teacher))
            if path == "/api/backup":
                return self.reply(
                    store.backup(c, self.owner), filename="我的求职工作台_私有备份.json"
                )
            if path == "/api/taxonomy":
                return self.reply(service.taxonomy())
            if path == "/api/profile":
                return self.reply(store.get(c, self.owner, d.get("id"), ("profile",)))
            if path == "/api/material":
                return self.reply(store.get(c, self.owner, d.get("id"), service.KINDS))
            if path == "/api/export":
                from materials import export_material

                key = d.get("id")
                record = store.get(c, self.owner, key, service.KINDS)
                kind = c.execute(
                    "SELECT kind FROM records WHERE id=?", (key,)
                ).fetchone()[0]
                fmt = d.get("fmt", "md")
                if fmt not in ("md", "pdf", "docx"):
                    raise ValueError("不支持此格式。")
                name = {
                    "resume": "求职简历",
                    "five": "五点面试稿",
                    "eighteen": "十八点面试稿",
                }[kind]
                return self.reply(
                    export_material(kind, fmt, record["text"]),
                    ctype=mimetypes.guess_type("document." + fmt)[0]
                    or "application/octet-stream",
                    filename=f"{name}_V{key}.{fmt}",
                )
            if path == "/api/questions":
                from bank import search_cards

                cards = list(service.pool(c, self.owner, d.get("scope")).values())
                opts = {
                    k: d.get(k, "") for k in ("query", "stage", "topic", "subtopic")
                }
                filtered = search_cards(cards=cards, **opts)
                summaries = []
                for q in filtered:
                    row = {
                        k: q.get(k, "")
                        for k in ("id", "title", "stage", "topic", "subtopic")
                    }
                    if q.get("legacy_status"):
                        row["legacy_status"] = q["legacy_status"]
                    if opts["topic"]:
                        for pair in [row, *q.get("related", [])]:
                            if pair["topic"] == opts["topic"] and (
                                not opts["subtopic"]
                                or pair["subtopic"] == opts["subtopic"]
                            ):
                                row.update(
                                    topic=pair["topic"], subtopic=pair["subtopic"]
                                )
                                break
                    summaries.append(row)
                if d.get("with_status") == "1":
                    from bank import lookup_legacy

                    legacy = (
                        lookup_legacy(opts["query"])
                        if d.get("scope", "public") == "public"
                        else None
                    )
                    return self.reply(
                        {
                            "cards": summaries,
                            "unmapped": bool(legacy and not legacy.get("card_id")),
                        }
                    )
                return self.reply(summaries)
            if path == "/api/question":
                return self.reply(
                    service.student_card(service.get_question(c, self.owner, d))
                )
            if path == "/api/mistakes":
                return self.reply(service.mistakes(c, self.owner))
            if path == "/api/mistake":
                row = c.execute(
                    "SELECT card FROM attempts WHERE owner=? AND id=?",
                    (self.owner, d.get("id")),
                ).fetchone()
                if not row:
                    raise ValueError("找不到本次练习。")
                return self.reply(service.student_card(json.loads(row[0])))
            if path == "/api/mock":
                return self.reply(
                    service.safe_mock(
                        d.get("id"), store.get(c, self.owner, d.get("id"), ("mock",))
                    )
                )
            if path == "/api/teacher/batches":
                return self.reply(service.batch_list(c))
            if path == "/api/teacher/batch":
                return self.reply(
                    service.batch_result(
                        c.execute(
                            "SELECT * FROM batches WHERE id=?", (d.get("id"),)
                        ).fetchone()
                    )
                )
            if path == "/api/teacher/export":
                row = c.execute(
                    "SELECT body FROM batches WHERE id=? AND published>0",
                    (d.get("id"),),
                ).fetchone()
                if not row:
                    raise ValueError("只能导出已发布批次。")
                return self.reply(
                    {
                        "format": "offer-lab-bank-v1",
                        **json.loads(row["body"])["release"],
                    },
                    filename="题库更新_" + str(d.get("id")) + ".json",
                )
        return self.reply({"error": "页面不存在。"}, 404)

    def write(self, c, path, d):
        owner = self.owner
        if path in ("/api/student/new", "/api/student/restore"):
            fresh = secrets.token_hex(24)
            count = store.restore(c, fresh, d) if path.endswith("restore") else 0
            self.owner = fresh
            self.new_cookie = True
            return {"restored": count}
        if path == "/api/split":
            return {"projects": store.split_projects(str(d.get("text", "")))}
        if path == "/api/profile":
            value = store.profile(d)
            last = c.execute(
                "SELECT id,body FROM records WHERE owner=? AND kind='profile' ORDER BY id DESC LIMIT 1",
                (owner,),
            ).fetchone()
            return {
                "id": last["id"]
                if last and json.loads(last["body"]) == value
                else store.add(c, owner, "profile", value)
            }
        if path == "/api/material/edit":
            key = d.get("id")
            value = store.get(c, owner, key, service.KINDS)
            if (
                not isinstance(d.get("text"), str)
                or not 0 < len(d["text"].strip()) <= 300000
            ):
                raise ValueError("正文为空或过长。")
            kind = c.execute("SELECT kind FROM records WHERE id=?", (key,)).fetchone()[
                0
            ]
            return {
                "id": store.add(
                    c,
                    owner,
                    kind,
                    {**value, "text": d["text"].strip(), "mode": "手工修订"},
                    value["profile_id"],
                )
            }
        if path == "/api/answer":
            if d.get("attempt"):
                r = c.execute(
                    "SELECT card,scope FROM attempts WHERE owner=? AND id=?",
                    (owner, d["attempt"]),
                ).fetchone()
                if not r:
                    raise ValueError("找不到该错题。")
                return service.saved_choice(
                    c, owner, r["scope"], json.loads(r["card"]), d.get("selected")
                )
            return service.saved_choice(
                c,
                owner,
                d.get("scope") or "public",
                service.get_question(c, owner, d),
                d.get("selected"),
            )
        if path == "/api/mock/start":
            return service.begin_mock(c, owner, d)
        if path == "/api/mock/answer":
            return service.advance_mock(c, owner, d)
        if path == "/api/teacher/publish":
            return service.publish(c, d)
        if path == "/api/teacher/manual":
            return service.complete_pending(c, d)
        if path == "/api/teacher/draft":
            return service.edit_draft(c, d)
        if path == "/api/teacher/undo":
            return service.undo(c, d)
        if path == "/api/teacher/package":
            if d.get("format") != "offer-lab-bank-v1":
                raise ValueError("无法识别这个题库更新包。")
            cards = [service.valid_card(q) for q in d.get("cards", [])]
            if not cards and not d.get("merged"):
                raise ValueError("更新包没有题目或问法。")
            merged = [
                {"id": str(x["id"]), "question": str(x["question"])}
                for x in d.get("merged", [])
            ]
            preview = {"cards": cards, "merged": merged, "pending": []}
            fp = store.digest(preview)
            c.execute(
                "INSERT OR IGNORE INTO batches(fingerprint,body) VALUES(?,?)",
                (fp, store.pack({"preview": preview})),
            )
            return service.batch_result(
                c.execute("SELECT * FROM batches WHERE fingerprint=?", (fp,)).fetchone()
            )
        raise ValueError("未知操作。")


def serve(port, teacher=False, open_browser=False, check=False):
    store.init()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.teacher_enabled = teacher
    server.teacher_key = secrets.token_urlsafe(32)
    server.teacher_cookie = secrets.token_hex(32)
    if check:
        from contextlib import closing
        from http.client import HTTPConnection

        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with closing(
                HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            ) as connection:
                connection.request("GET", "/")
                home = connection.getresponse()
                if home.status != 200 or "Offer 来了" not in home.read().decode():
                    raise RuntimeError("无法打开学生工作台。")
                connection.request("GET", "/api/state")
                response = connection.getresponse()
                if response.status != 200 or not json.load(response).get(
                    "public_count"
                ):
                    raise RuntimeError("题库加载失败。")
                if teacher:
                    connection.request(
                        "POST",
                        "/api/teacher/open",
                        store.pack({"key": server.teacher_key}),
                        {"Content-Type": "application/json"},
                    )
                    auth = connection.getresponse()
                    if auth.status != 200 or "offerlab_teacher" not in str(
                        auth.headers
                    ):
                        raise RuntimeError("教师维护入口未通过校验。")
                    auth.read()
            print("本机启动检查通过。", flush=True)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        return
    address = f"http://127.0.0.1:{server.server_port}/"
    url = address + ("#teacher=" + server.teacher_key if teacher else "")
    print("Offer 来了已启动：" + url, flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int)
    p.add_argument("--teacher", action="store_true")
    p.add_argument("--open", action="store_true")
    p.add_argument(
        "--check", action="store_true", help="检查本机页面、题库与所选入口后退出"
    )
    args = p.parse_args()
    try:
        serve(
            args.port
            if args.port is not None
            else (0 if args.check else 8737 if args.teacher else 8736),
            args.teacher,
            args.open,
            args.check,
        )
    except OSError as exc:
        print(
            "启动失败。请检查端口是否已有本程序或其他服务在使用。",
            str(exc),
            file=sys.stderr,
        )
        sys.exit(1)
