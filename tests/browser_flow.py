"""Exercise the student UI with temporary local records. Requires Playwright + installed Chromium."""

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from app import Handler, ThreadingHTTPServer
import store


def sparse_profile(browser, url, shots):
    with browser.new_context(viewport={"width": 1440, "height": 1000}) as ctx:
        page = ctx.new_page()
        requests = []
        page.on("request", lambda r: requests.append(r.post_data_json) if r.url.endswith("/api/generate") else None)
        page.goto(url)
        basic = "姓名：测试同学\n求职方向：软件测试工程师\n邮箱：demo@example.com"
        page.locator("#basic").fill(basic)
        page.locator("#standard").select_option("job")
        page.locator("#save").click()
        expect(page.locator("#status")).to_contain_text("资料已保存")
        page.reload()
        expect(page.locator("#basic")).to_have_value(basic)
        expect(page.locator("#standard")).to_have_value("job")
        expect(page.locator("#profileIssues")).to_contain_text("目前有 0 个项目")
        projects = ["项目一：预约登记", "项目二：报表核对", "项目三：资料归档"]
        page.locator("#projects").fill("\n\n".join(projects))
        expect(page.locator("#profileIssues")).to_be_hidden()
        expect(page.locator("#gapNotice")).to_be_visible()
        page.locator("#generate").click()
        expect(page.locator("#status")).to_contain_text("已保存为草稿")
        assert [r["kind"] for r in requests] == ["resume"]
        assert 1 <= page.locator("#profileIssues .gap").count() <= 3
        assert page.locator("#open-five, #open-eighteen").count() == 0
        if shots:
            page.locator("#profileIssues").scroll_into_view_if_needed()
            page.screenshot(path=shots / "项目原文与待补问题.png")
        page.locator("#open-resume").click()
        expect(page.get_by_role("dialog")).to_contain_text("草稿")
        with page.expect_download() as dl:
            page.get_by_role("link", name="下载草稿 PDF").click()
        assert "草稿" in dl.value.suggested_filename
        page.get_by_role("button", name="关闭", exact=True).click()
        page.get_by_role("button", name="模拟面试", exact=True).click()
        expect(page.locator("#toWorkspace")).to_be_visible()
        expect(page.locator("#resumePick")).to_have_count(0)
        page.locator("#toWorkspace").click()

        issue = page.locator("#profileIssues .gap").filter(has_text="预约登记")
        for action in ["查过了，没有记录", "这部分不是我做的", "补一句事实"]:
            issue.get_by_role("button", name=action).click()
            expect(page.get_by_role("dialog")).to_contain_text(action)
            expect(page.locator("#factEdit")).to_have_value(projects[0])
            page.locator("#applyFact").click()
            expect(page.locator("#factError")).to_contain_text("请写入或改正")
            if action != "补一句事实":
                page.get_by_role("button", name="关闭", exact=True).click()
        projects[0] += "\n业务：社团负责人需要查重报名。我用 Python 比对报名编号，在本地用重复编号的样例核对结果。\n团队分工：页面由同学负责。交付：报名查重脚本，没有线上统计记录。"
        page.locator("#factEdit").fill(projects[0])
        page.locator("#applyFact").click()
        expect(page.locator("#status")).to_contain_text("内容已保存到项目 1")
        page.reload()
        page.locator("#split").click()
        for n, project in enumerate(projects):
            expect(page.locator(f"#project{n}")).to_have_value(project)
        expect(page.locator("#basic")).to_have_value(basic)
        expect(page.locator("#standard")).to_have_value("job")


def exercise_generation(page, url):
    requests = []
    page.on("request", lambda r: requests.append(r.post_data_json) if r.url.endswith("/api/generate") else None)
    page.get_by_role("button", name="使用虚构示例").click()
    expect(page.locator("#standard")).to_have_value("auto")

    # The actual service commits the resume; only its response is lost.
    def lose_reply(route):
        result = route.fetch(timeout=120_000)
        assert result.ok, result.text()
        route.abort("failed")
    page.route("**/api/generate", lose_reply)
    page.locator("#gen-resume").click()
    expect(page.locator("#status")).to_contain_text("本次生成已停下")
    first = page.request.get(url + "api/state").json()["materials"]
    assert len(first) == 1 and first[0]["status"] == "ready", first
    page.unroute("**/api/generate", lose_reply)
    page.reload()
    page.locator("#gen-resume").click()
    expect(page.locator("#status")).to_contain_text("可投递")
    assert len(requests) == 2 and requests[0]["request_id"] == requests[1]["request_id"]
    materials = page.request.get(url + "api/state").json()["materials"]
    assert [m["id"] for m in materials] == [first[0]["id"]]

    def interrupt_eighteen(route):
        if route.request.post_data_json["kind"] == "eighteen":
            route.abort("failed")
        else:
            route.continue_()
    page.route("**/api/generate", interrupt_eighteen)
    page.locator("#generate").click()
    expect(page.locator("#status")).to_contain_text("本次生成已停下")
    saved = page.request.get(url + "api/state").json()["materials"]
    assert [m["kind"] for m in saved] == ["five", "resume"], [(m["kind"], m["issues"]) for m in saved]
    assert saved[0]["based_on"] == saved[1]["id"] and saved[0]["status"] == "ready"
    page.unroute("**/api/generate", interrupt_eighteen)
    page.reload()
    requests.clear()
    page.locator("#generate").click()
    expect(page.locator("#status")).to_contain_text("十八点稿可练习")
    assert [(r["kind"], r["resume_id"], r["five_id"]) for r in requests] == [("eighteen", saved[1]["id"], saved[0]["id"])]
    ready = page.request.get(url + "api/state").json()["materials"]
    assert len(ready) == 3 and all(m["status"] == "ready" for m in ready)
    assert ready[0]["based_on"] == saved[1]["id"] and ready[0]["five_id"] == saved[0]["id"]
    return requests


def check_sample_content(page, url, materials):
    texts = {m["kind"]: page.request.get(url + f'api/material?id={m["id"]}').json()["text"] for m in materials}

    def passage(kind, heading):
        match = re.search(r"(?ms)^## " + heading + r"[^\n]*\n(.+?)(?=^#{1,2} |\Z)", texts[kind])
        assert match, f"{kind} 缺少 {heading}"
        return match[1]

    # These checks apply to the classroom example only. Its facts include
    # similar order numbers, manual confirmation and a teaching test machine.
    resume = texts["resume"]
    assert re.search("精确匹配|准确匹配|完整编号匹配", resume), "简历漏掉编号相近时实际采取的措施"
    assert "同学负责客服页面" in resume
    intro = passage("five", "二、自我介绍")
    assert "林禾" in intro and "（虚构示例）" not in intro
    short = passage("five", "三、主项目")
    assert "工单" in short and "编号" in short and re.search("匹配|确认|转人工", short)
    second = passage("five", "六、第二项目")
    assert "生效日期" in second and "原文" in second
    metric = passage("eighteen", "10｜")
    assert "分子" in metric and "分母" in metric and re.search("演练|举例", metric)
    cases = passage("eighteen", "12｜")
    assert re.search("工单号|订单号|编号", cases) and re.search("人工|确认", cases), "三类样例未落到工单分派"
    environment = passage("eighteen", "16｜")
    assert re.search("教学测试机|测试机|教学测试环境", environment), "漏掉已经核实的测试环境"
    failure = passage("eighteen", "17｜")
    assert re.search("相近|取错|同名|编号|候选", failure) and re.search("核对|匹配|确认", failure)


def full_bundle(browser, url):
    with browser.new_context(viewport={"width": 1440, "height": 1000}) as ctx:
        page = ctx.new_page()
        sent = []
        page.on("request", lambda r: sent.append(r.post_data_json) if r.url.endswith("/api/generate") else None)
        page.goto(url)
        page.locator("#example").click()
        page.locator("#generate").click()
        expect(page.locator("#status")).to_contain_text("十八点稿可练习")
        assert [r["kind"] for r in sent] == ["resume", "five", "eighteen"]
        materials = page.request.get(url + "api/state").json()["materials"]
        eighteen, five, resume = materials
        assert all(m["status"] == "ready" for m in materials)
        assert resume["id"] == sent[1]["resume_id"] == sent[2]["resume_id"] == eighteen["based_on"]
        assert five["id"] == sent[2]["five_id"] == eighteen["five_id"]
        check_sample_content(page, url, materials)
        page.locator("#generate").click()
        expect(page.locator("#generate")).to_be_enabled()
        assert len(sent) == 3


def run(shots):
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw:
        os.environ["OFFER_DATA_DIR"] = folder
        expect.set_options(timeout=60_000)
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
            sparse_profile(browser, url, shots)
            full_bundle(browser, url)
            requests = exercise_generation(page, url)
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
            page.locator("#edited").fill(before.replace("### 制度知识库", "### 制度知识库\n\n本人独立部署至生产环境，线上准确率提升 90%。"))
            page.get_by_role("button", name="另存修订版").click()
            expect(page.get_by_role("dialog")).to_contain_text("草稿 · 待补充或修订")
            expect(page.locator("#modalBody .issue-list").first).to_contain_text("90%")
            if shots:
                page.screenshot(path=shots / "修订简历核对.png")
            blocked_id = page.request.get(url + "api/state").json()["materials"][0]["id"]
            page.get_by_role("button", name="关闭", exact=True).click()
            requests.clear()
            page.locator("#generate").click()
            expect(page.locator("#status")).to_contain_text("手改的求职简历")
            assert requests == []
            page.get_by_role("button", name="模拟面试", exact=True).click()
            expect(page.locator(f'#resumePick option[value="{blocked_id}"]')).to_have_count(0)
            page.get_by_role("button", name="我的求职材料", exact=True).click()
            page.locator("#open-resume").click()
            page.locator("#edit").click()
            page.locator("#edited").fill(before)
            page.locator("#saveDoc").click()
            expect(page.get_by_role("dialog").locator(".material-tag")).to_have_text("可投递")
            page.get_by_role("button", name="关闭", exact=True).click()
            expect(page.locator(".paper").nth(1)).to_contain_text("依据旧简历")
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
            expect(page.locator("#view details.version")).to_have_count(6)
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
            expect(page.locator("#status")).to_contain_text("已恢复备份")
            expect(page.locator(".paper .material-tag")).to_have_text(["历史版本 · 需重新核对"] * 3)
            page.reload()
            page.locator("#open-resume").click()
            expect(page.get_by_role("link", name="下载历史版 DOCX")).to_be_visible()
            if shots:
                page.screenshot(path=shots / "历史材料重新核对.png")
            page.locator("#recheck").click()
            expect(page.get_by_role("dialog").locator(".material-tag")).to_have_text("可投递")
            assert not errors, errors
            print(
                "Student browser journey passed: incomplete input and correction, graduation standard, draft export and gate, interrupted resume and script recovery, same-version documents, real Word/PDF, edited claims, mock gates, legacy backup recheck, practice and wrong answers."
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
