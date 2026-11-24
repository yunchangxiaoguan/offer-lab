"""Exercise the student UI with temporary local records. Requires Playwright + installed Chromium."""

import argparse
import os
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from app import Handler, ThreadingHTTPServer
import store


def run(shots):
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw:
        os.environ["OFFER_DATA_DIR"] = folder
        store.init()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.teacher_enabled = False
        wt = threading.Thread(target=server.serve_forever, daemon=True)
        wt.start()
        browser = None
        try:
            path = os.getenv("OFFER_BROWSER") or next(
                (
                    str(p)
                    for p in (
                        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                        Path(
                            "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
                        ),
                    )
                    if p.exists()
                ),
                None,
            )
            browser = pw.chromium.launch(headless=True, executable_path=path)
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 1000}, accept_downloads=True
            )
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dlg: dlg.accept())
            url = f"http://127.0.0.1:{server.server_port}/"
            page.goto(url)
            expect(page.get_by_role("heading", name="我的求职材料")).to_be_visible()
            page.get_by_role("button", name="使用虚构示例").click()
            page.get_by_role("button", name="生成三份材料").click()
            expect(page.get_by_role("button", name="打开与导出")).to_have_count(3)
            page.get_by_role("button", name="检查项目分段").click()
            expect(page.locator("#parts textarea")).to_have_count(3)
            if shots:
                page.screenshot(path=shots / "学生材料.png")
            page.locator("#open-resume").click()
            expect(page.get_by_role("dialog")).to_contain_text("制度知识库")
            with page.expect_download() as dl:
                page.get_by_role("link", name="下载 PDF").click()
            f = dl.value
            import fitz

            with fitz.open(f.path()) as pdf:
                assert 2 <= len(pdf) <= 3 and "知识库" in "".join(
                    p.get_text() for p in pdf
                )
            with page.expect_download() as dl:
                page.get_by_role("link", name="下载 DOCX").click()
            from docx import Document

            assert any("知识库" in p.text for p in Document(dl.value.path()).paragraphs)
            page.get_by_role("button", name="编辑正文").click()
            before = page.locator("#edited").input_value()
            page.locator("#edited").fill(
                before.replace("版本过滤", "条款版本校核")
                + "\n\n仅本版本留存的核对说明。"
            )
            page.get_by_role("button", name="另存修订版").click()
            expect(page.get_by_role("dialog")).to_contain_text("仅本版本留存")
            page.get_by_role("button", name="关闭", exact=True).click()
            page.get_by_role("button", name="模拟面试", exact=True).click()
            page.get_by_role("button", name="生成专属题").click()
            expect(page.locator("#status")).to_contain_text("道本人专属题")
            page.get_by_role("button", name="开始面试", exact=True).click()
            expect(page.locator("#detail .evidence")).to_have_count(0)
            page.locator(".choice").first.click()
            page.get_by_role("button", name="提交答案").click()
            expect(page.locator("#result")).to_contain_text("面试时可以这样说")
            expect(page.locator("#result .evidence")).to_be_visible()
            page.get_by_role("button", name="下一题").click()
            page.get_by_role("button", name="保存并返回").click()
            page.get_by_role("button", name="继续", exact=True).click()
            for _ in range(5):
                page.locator(".choice").nth(1).click()
                page.get_by_role("button", name="提交答案").click()
                page.locator("#next").click()
            expect(page.get_by_role("heading", name="本场复盘")).to_be_visible()
            assert page.locator("details.version").count() == 6
            page.get_by_role("button", name="面试题库", exact=True).click()
            page.locator("#scope").select_option("public")
            page.locator("#topic").select_option(label="Agent 智能体")
            page.locator("#sub").select_option(label="LangGraph")
            expect(page.locator("#list button").first).to_be_visible()
            page.locator("#list button").first.click()
            expect(page.locator(".choices button")).to_have_count(4)
            if shots:
                page.screenshot(path=shots / "技术子类.png")
            page.locator("#topic").select_option(label="全部技术专题")
            page.locator("#query").fill("I07")
            expect(page.locator("#count")).to_have_text("1 道题")
            target = page.locator("#list button").filter(has_text="混合检索、RRF")
            expect(target).to_be_visible()
            target.click()
            expect(page.locator("#detail h2")).to_contain_text("混合检索、RRF")
            page.locator(".choice").nth(1).click()
            page.locator("#submitChoice").click()
            expect(page.locator("#result .bad")).to_be_visible()
            if shots:
                page.screenshot(path=shots / "错题反馈.png")
            page.get_by_role("button", name="错题复习", exact=True).click()
            page.locator(".item").filter(has_text="混合检索、RRF").click()
            page.locator(".choice").first.click()
            page.locator("#submitChoice").click()
            expect(page.locator("#result .good")).to_be_visible()
            page.get_by_role("button", name="错题复习", exact=True).click()
            expect(
                page.locator(".item").filter(has_text="混合检索、RRF")
            ).to_have_count(0)
            other = browser.new_context()
            otherpage = other.new_page()
            otherpage.goto(url)
            expect(
                otherpage.get_by_role("heading", name="我的求职材料")
            ).to_be_visible()
            expect(otherpage.get_by_role("button", name="打开与导出")).to_have_count(0)
            page.get_by_role("button", name="我的求职材料", exact=True).click()
            page.get_by_role("button", name="备份资料与切换学生").click()
            with page.expect_download() as dl:
                page.get_by_role("link", name="下载我的私有备份").click()
            backup = Path(folder) / "学生备份.json"
            dl.value.save_as(backup)
            page.get_by_role("button", name="切换到新学生").click()
            expect(page.get_by_role("heading", name="我的求职材料")).to_be_visible()
            expect(page.get_by_role("button", name="打开与导出")).to_have_count(0)
            page.get_by_role("button", name="备份资料与切换学生").click()
            page.locator("#restoreFile").set_input_files(backup)
            expect(page.get_by_role("button", name="打开与导出")).to_have_count(3)
            page.reload()
            expect(page.get_by_role("button", name="打开与导出")).to_have_count(3)
            assert not errors, errors
            print(
                "Student browser journey passed: three materials, Word/PDF, resume revisions, personal mock, filters, correction, isolated sessions and backup restore."
            )
        finally:
            if browser:
                browser.close()
            server.shutdown()
            server.server_close()
            wt.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    run(args.screenshots)
