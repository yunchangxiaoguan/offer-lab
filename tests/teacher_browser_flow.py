"""Run with the local Playwright installation. All student and teacher data are fictional."""

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "tests"))
from test_teacher_flow import application, CARD, SOURCE


with (
    TemporaryDirectory() as tmp,
    application(tmp, teacher=True) as (origin, key),
    sync_playwright() as pw,
):
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    executable = os.getenv("OFFER_BROWSER") or (
        str(chrome) if chrome.exists() else None
    )
    browser = pw.chromium.launch(executable_path=executable, headless=True)
    try:
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000}, accept_downloads=True
        )
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin + "/#teacher=" + key, wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="导入面试转写")).to_be_visible()
        page.get_by_label("转写文本").fill(SOURCE)
        page.get_by_role("button", name="整理本批").click()
        detail = page.locator("#batchDetail")
        expect(detail.get_by_text("发布前核对", exact=False)).to_be_visible()
        detail.get_by_role("button", name="补成选择题").click()
        dialog = page.get_by_role("dialog")
        for field in ("title", "prompt", "spoken", "followup", "followup_answer"):
            dialog.locator("#ec-" + field).fill(CARD[field])
        for i in range(4):
            dialog.locator("#ec-o" + str(i)).fill(CARD["options"][i])
            dialog.locator("#ec-r" + str(i)).fill(CARD["reasons"][i])
        dialog.get_by_label("技术专题").select_option(CARD["topic"])
        dialog.get_by_label("技术子类").select_option(CARD["subtopic"])
        dialog.get_by_role("button", name="保存到本批").click()
        expect(dialog).not_to_be_visible()
        detail.get_by_role("button", name="编辑题卡").click()
        revised = CARD["title"] + "（教学版）"
        dialog.get_by_label("题名").fill(revised)
        dialog.get_by_role("button", name="保存到本批").click()
        expect(dialog).not_to_be_visible()
        detail.get_by_role("button", name="编辑问法").click()
        phrase = "表头换到下一页时，怎样保留列名？"
        dialog.get_by_label("适合公开的提问").fill(phrase)
        dialog.get_by_role("button", name="保存到本批").click()
        expect(dialog).not_to_be_visible()
        page.reload(wait_until="domcontentloaded")
        page.get_by_role("button", name="查看", exact=True).click()
        expect(detail.get_by_text(revised, exact=True)).to_be_visible()
        expect(detail.get_by_text(phrase, exact=False)).to_be_visible()
        detail.get_by_role("checkbox", name=revised).check()
        detail.get_by_role("button", name="发布已勾选内容").click()
        expect(
            detail.get_by_text("本批实际发布 1 道新题、0 条补充问法", exact=False)
        ).to_be_visible()
        expect(detail.get_by_text(phrase, exact=False)).to_have_count(0)
        shots = root / "qa-artifacts"
        shots.mkdir(exist_ok=True)
        page.screenshot(path=str(shots / "teacher-release.png"), full_page=True)
        with page.expect_download() as download:
            page.get_by_role("link", name="导出更新包").click()
        content = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
        assert [x["title"] for x in content["cards"]] == [revised] and content[
            "merged"
        ] == []
        student = browser.new_context(
            viewport={"width": 1440, "height": 1000}
        ).new_page()
        student.goto(origin, wait_until="domcontentloaded")
        expect(student.get_by_role("button", name="教师题库维护")).to_have_count(0)
        student.get_by_role("button", name="面试题库").click()
        student.locator("#query").fill(revised)
        student.get_by_role("button", name=revised, exact=False).click()
        expect(
            student.locator("#detail").get_by_role("heading", name=revised)
        ).to_be_visible()
        page.once("dialog", lambda popup: popup.accept())
        page.get_by_role("button", name="撤回").click()
        expect(page.get_by_text("批次已撤回。", exact=True)).to_be_visible()
        student.reload(wait_until="domcontentloaded")
        student.get_by_role("button", name="面试题库").click()
        student.locator("#query").fill(revised)
        expect(student.locator("#count")).to_have_text("0 道题")
        assert not errors, errors
        print("教师页面录入、编辑、跨刷新保存、发布子集、下载、学生查找和撤回均通过。")
    finally:
        browser.close()
