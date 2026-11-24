const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const titles = {
  resume: "求职简历",
  five: "五点面试稿",
  eighteen: "十八点面试稿",
};
const kinds = Object.keys(titles);
const labels = ["A", "B", "C", "D"];
let state,
  tax,
  page,
  activeDoc,
  draft,
  parts,
  preview,
  exam,
  selected = -1,
  activeQuestion,
  bankScope = "public",
  attemptId = null,
  querySeq = 0,
  questionSeq = 0;
const sample = {
  basic:
    "姓名：林禾（虚构示例）\n求职方向：大模型应用开发\n教育：软件工程本科\n经历：后端应用开发，负责知识库检索、工单接口和验证。",
  projects: [
    "项目一：工单分流助手\n业务：客服按问题类型分派工单。\n本人职责：编写查询工具、配置分流规则，异常时转人工。\n验证：用三类样例核对处理结果。仅在本地验证。",
    "项目二：制度知识库\n业务：客服要查适用日期的退换货条款。\n本人职责：实现按生效日期过滤和原文引用。\n交付：可在回答中打开对应条款，未统计线上收益。",
    "项目三：售后单据核对\n业务：人工复核单据字段。\n本人职责：校验订单号和金额格式，将缺失字段送到人工复核。\n验证：回放了缺字段和金额格式错误两种样例。",
  ],
};
function msg(t = "", err = false) {
  $("status").className = t ? "statusbox" + (err ? " err" : "") : "";
  $("status").textContent = t;
}
async function api(path, body) {
  const res = await fetch(
    "/api/" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await res.json();
  if (!res.ok) throw Error(data.error || "操作失败");
  return data;
}
const params = (obj) => new URLSearchParams(obj).toString();
const opt = (v, label, sel) =>
  `<option value="${esc(v)}" ${String(v) === String(sel) ? "selected" : ""}>${esc(label)}</option>`;
const btn = (id, label, cl = "") =>
  `<button id="${id}" class="${cl}">${esc(label)}</button>`;
const head = (title, sub) =>
  `<h1>${esc(title)}</h1><p class="intro">${esc(sub)}</p>`;
const empty = (t) => `<p class="empty">${esc(t)}</p>`;
function on(id, evt, fn) {
  const el = $(id);
  if (el)
    el.addEventListener(evt, async (e) => {
      try {
        await fn(e);
      } catch (x) {
        msg(x.message, true);
      }
    });
}
function click(id, fn) {
  on(id, "click", fn);
}
async function refresh() {
  state = await api("state");
  $("teacherNav").hidden = !state.teacher;
}
function reading(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, "")
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((l) => {
      const h = l.match(/^(#{1,6})\s+(.+)/);
      if (h) {
        let n = Math.min(4, h[1].length + 1);
        return "<h" + n + ">" + esc(h[2]) + "</h" + n + ">";
      }
      return (
        "<p>" +
        esc(l).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>") +
        "</p>"
      );
    })
    .join("");
}
function modal(title, html) {
  $("modalTitle").textContent = title;
  $("modalBody").innerHTML = html;
  if (!$("modal").open) $("modal").showModal();
}
function modeButton(id) {
  return `<label class="small muted"><input id="${id}" type="checkbox" ${state.model ? "" : "disabled"}> 使用在线模型${state.model ? "（提交所需文本给已配置服务）" : "（本机未配置密钥）"}</label>`;
}
function capture() {
  if ($("basic")) {
    draft = { basic: $("basic").value, text: $("projects").value };
    const fields = document.querySelectorAll("#parts textarea");
    if (fields.length) parts = Array.from(fields, (field) => field.value);
  }
}
function workspace() {
  const prof = state.profile;
  if (!draft)
    draft = {
      basic: prof?.basic || "",
      text: prof?.projects.join("\n\n") || "",
    };
  const source = state.profiles.find((x) => x.id === prof?.id);
  const documents = kinds
    .map((k, i) => {
      const current = state.materials.find(
        (x) => x.kind === k && x.parent === prof?.id,
      );
      const recent = current || state.materials.find((x) => x.kind === k);
      const latestResume = state.materials.find(
        (x) => x.kind === "resume" && x.parent === prof?.id,
      );
      let info = recent
        ? `V${recent.id} · ${recent.mode}${current ? "" : " · 来自旧版资料"}`
        : "尚未生成";
      if (
        current &&
        k !== "resume" &&
        latestResume &&
        current.based_on !== latestResume.id
      )
        info += current.based_on
          ? ` · 依据旧简历 V${current.based_on}`
          : " · 依据原始资料";
      return `<section class="paper"><span class="icon">${["R", "5", "18"][i]}</span><div><h3>${titles[k]}</h3><p class="meta">${esc(info)}</p><div class="buttons">${recent ? btn("open-" + k, "打开与导出", "link") : ""}${btn("gen-" + k, recent ? "单独重生成" : "单独生成", "link")}</div></div></section>`;
    })
    .join("");
  $("view").innerHTML =
    head(
      "我的求职材料",
      "把基本信息和准备好的项目贴进来，生成一份简历和两份能直接练习的面试稿。",
    ) +
    `<div class="layout"><section class="panel"><div class="titlebar"><h2>学生资料</h2>${btn("example", "使用虚构示例", "link")}</div><label for="basic">基本信息</label><textarea id="basic" rows="4" placeholder="姓名、求职方向、教育与工作经历">${esc(draft.basic)}</textarea><div class="formrow"><label for="projects">项目材料 · 3–5 个</label><textarea id="projects" rows="8" placeholder="项目一：项目名称&#10;业务背景、本人职责、验证或交付&#10;&#10;项目二：项目名称…">${esc(draft.text)}</textarea><p class="hint">可连续粘贴。每个项目用“项目一：”“项目二：”开头，或在项目之间留一个空行。</p></div>${btn("split", "检查项目分段", "link")}<div id="parts"></div><hr>${modeButton("online")}<div class="actions">${btn("generate", "生成三份材料", "primary")}${btn("save", "保存资料")}</div><div id="generationStatus" role="status" class="statusline"></div></section><section class="stack"><div class="titlebar"><h2>我的成品</h2>${source ? `<span class="meta">资料 V${source.id}</span>` : ""}</div>${documents}<details class="version"><summary>查看历史材料（${state.materials.length}）</summary><div id="versions">${state.materials.map((x) => `<div class="between"><span class="small">${titles[x.kind]} · V${x.id} · 资料 V${x.parent}</span><button class="link" data-doc="${x.id}">打开</button></div>`).join("")}</div></details><button class="link" id="backupMenu">备份资料与切换学生</button></section></div>`;
  click("backupMenu", backupMenu);
  if (parts) renderParts();
  click("example", () => {
    if (
      (draft.basic || $("basic").value || $("projects").value) &&
      !window.confirm("用虚构示例替换当前输入框吗？已保存的版本可继续查看。")
    )
      return;
    draft = { basic: sample.basic, text: sample.projects.join("\n\n") };
    parts = null;
    workspace();
  });
  on("projects", "input", () => {
    parts = null;
    $("parts").innerHTML = "";
  });
  click("split", async () => {
    capture();
    parts = (await api("split", { text: draft.text })).projects;
    renderParts();
  });
  click("save", async () => {
    let id = await saveProfile();
    await refresh();
    capture();
    workspace();
    msg("资料已保存为 V" + id);
  });
  click("generate", () => generate(kinds));
  for (const k of kinds) {
    click("gen-" + k, () => generate([k]));
    click("open-" + k, () =>
      showDoc(
        (
          state.materials.find((x) => x.kind === k && x.parent === prof?.id) ||
          state.materials.find((x) => x.kind === k)
        ).id,
      ),
    );
  }
  $("versions").onclick = (e) => {
    let id = e.target.dataset.doc;
    if (id) showDoc(id).catch((x) => msg(x.message, true));
  };
}
function renderParts() {
  const root = $("parts");
  root.innerHTML =
    `<p class="hint">已识别 ${parts.length} 个项目，可在下方修正。若数量不对，请调整上方分隔再检查。</p>` +
    parts
      .map(
        (p, i) =>
          `<label class="small" for="project${i}">项目 ${i + 1}</label><textarea id="project${i}" rows="2">${esc(p)}</textarea>`,
      )
      .join("");
}
async function saveProfile() {
  capture();
  const projects = parts || (await api("split", { text: draft.text })).projects;
  let result = await api("profile", { basic: draft.basic, projects });
  return result.id;
}
let generating = false;
async function generate(todo) {
  if (generating) return;
  const online = $("online").checked;
  generating = true;
  const errs = [];
  try {
    const id = await saveProfile();
    let resumeId = state.materials.find(
      (x) => x.parent === id && x.kind === "resume",
    )?.id;
    for (const k of todo) {
      const note = "正在生成" + titles[k] + "…";
      msg(note);
      if ($("generationStatus")) $("generationStatus").textContent = note;
      try {
        const r = await api("generate", {
          kind: k,
          profile_id: id,
          resume_id: k === "resume" ? null : resumeId,
          use_model: online,
        });
        if (k === "resume") resumeId = r.id;
      } catch (x) {
        errs.push(titles[k] + "：" + x.message);
      }
    }
    await refresh();
    if (page === "workspace") {
      capture();
      workspace();
    }
    msg(
      errs.length
        ? errs.join(" / ")
        : "材料已生成，可在“我的成品”中打开、编辑与导出。",
      !!errs.length,
    );
  } finally {
    generating = false;
  }
}
async function showDoc(id) {
  activeDoc = Number(id);
  const m = await api("material?" + params({ id }));
  const meta = state.materials.find((x) => x.id === activeDoc),
    kind = meta?.kind || "resume";
  modal(
    titles[kind] + " · V" + id,
    `<div class="toolbar">${["docx", "pdf", "md"].map((fmt) => `<a class="download" href="/api/export?${params({ id, fmt })}" download>下载 ${fmt.toUpperCase()}</a>`).join("")}${btn("edit", "编辑正文")}</div><div class="smallline">${esc(m.mode)} · 来源资料 V${m.profile_id}${m.based_on ? " · 简历 V" + esc(m.based_on) : ""}</div><div class="prose">${reading(m.text)}</div>`,
  );
  click("edit", () => {
    modal(
      "编辑" + titles[kind],
      `<textarea id="edited" rows="20">${esc(m.text)}</textarea><div class="actions">${btn("saveDoc", "另存修订版", "primary")}</div>`,
    );
    click("saveDoc", async () => {
      const r = await api("material/edit", { id, text: $("edited").value });
      await refresh();
      if (page === "workspace") {
        capture();
        workspace();
      }
      await showDoc(r.id);
    });
  });
}
function setOptions() {
  return (
    opt("public", "公共题库", bankScope) +
    state.sets
      .map((s) =>
        opt(s.id, "专属题 · 简历 V" + s.parent + " · 题集 " + s.id, bankScope),
      )
      .join("")
  );
}
function topicOptions(sel = "") {
  return (
    opt("", "全部技术专题", sel) +
    Object.keys(tax.topics)
      .map((s) => opt(s, s, sel))
      .join("")
  );
}
function subs() {
  const items = tax.topics[$("topic").value] || [];
  $("sub").innerHTML =
    opt("", "全部子类", "") + items.map((s) => opt(s, s, "")).join("");
}
function bank() {
  activeQuestion = null;
  attemptId = null;
  selected = -1;
  $("view").innerHTML =
    head(
      "面试题库",
      "按面试环节、技术专题和子类找题。选完答案，可以对照口述示范再练一遍。",
    ) +
    `<div class="searchbar"><select aria-label="题库范围" id="scope">${setOptions()}</select><input id="query" aria-label="搜索面试题" placeholder="搜索题目或技术词，如 LangGraph、切块、缓存"></div><div class="toolbar"><select id="stage" aria-label="面试环节">${opt("", "全部面试环节", "") + tax.stages.map((s) => opt(s, s, "")).join("")}</select><select id="topic" aria-label="技术专题">${topicOptions()}</select><select id="sub" aria-label="技术子类"></select><span id="count" class="meta"></span></div><div class="index"><div id="list" class="list"></div><div id="detail" class="question">${empty("从左侧选择一道题开始练习。")}</div></div>`;
  subs();
  on("scope", "change", () => {
    bankScope = $("scope").value;
    return loadList();
  });
  on("topic", "change", () => {
    subs();
    return loadList();
  });
  for (const id of ["sub", "stage"]) on(id, "change", loadList);
  on("query", "input", loadList);
  return loadList();
}
async function loadList() {
  if (!$("query")) return;
  let version = ++querySeq;
  ++questionSeq;
  activeQuestion = null;
  $("list").innerHTML = "";
  $("detail").innerHTML = empty("从左侧选择一道题开始练习。");
  const { cards: rows, unmapped } = await api(
    "questions?" +
      params({
        with_status: "1",
        scope: $("scope").value,
        stage: $("stage").value,
        topic: $("topic").value,
        subtopic: $("sub").value,
        query: $("query").value.trim(),
      }),
  );
  if (version !== querySeq || page !== "bank") return;
  $("count").textContent = rows.length + " 道题";
  $("list").innerHTML = rows.length
    ? rows
        .map(
          (q) =>
            `<button class="item" data-id="${esc(q.id)}">${esc(q.title)}<small>${[q.stage, q.topic, q.subtopic, q.legacy_status].filter(Boolean).map(esc).join(" · ")}</small></button>`,
        )
        .join("")
    : empty(
        unmapped
          ? "该旧题已登记，待专项改编，目前没有对应练习。"
          : "这个组合暂无题目，可以清除一项筛选。",
      );
  ++questionSeq;
  activeQuestion = null;
  $("detail").innerHTML = empty("从左侧选择一道题开始练习。");
  $("list").onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    try {
      const t = ++questionSeq;
      const card = await api(
        "question?" + params({ scope: bankScope, id: b.dataset.id }),
      );
      if (t !== questionSeq || page !== "bank") return;
      document
        .querySelectorAll(".item.selected")
        .forEach((el) => el.classList.remove("selected"));
      b.classList.add("selected");
      activeQuestion = card;
      selected = -1;
      ask(card, "practice");
    } catch (x) {
      msg(x.message, true);
    }
  };
}
function ask(q, mode) {
  const root = $("detail");
  selected = -1;
  root.innerHTML = `<span class="badge">${esc(q.practice_step || q.stage)}</span><h2>${esc(q.title)}</h2><p>${esc(q.prompt)}</p><div class="choices">${q.options.map((o, i) => `<button class="choice" data-i="${i}" aria-pressed="false"><b>${labels[i]}</b><span>${esc(o)}</span></button>`).join("")}</div>${btn("submitChoice", "提交答案", "primary")}<section id="result" aria-live="polite"></section>`;
  root.querySelectorAll(".choice").forEach(
    (el) =>
      (el.onclick = () => {
        selected = Number(el.dataset.i);
        root
          .querySelectorAll(".choice")
          .forEach((x) => x.setAttribute("aria-pressed", String(x === el)));
      }),
  );
  click("submitChoice", async () => {
    if (selected < 0) {
      msg("请先选择一个选项。", true);
      return;
    }
    const button = $("submitChoice");
    const choices = Array.from(root.querySelectorAll(".choice"));
    choices.forEach((choice) => (choice.disabled = true));
    button.disabled = true;
    try {
      let r;
      if (mode === "mock") {
        exam = await api("mock/answer", {
          session: exam.id,
          id: q.id,
          revision: q.revision,
          selected,
        });
        r = exam.history.at(-1);
      } else {
        r = await api("answer", {
          scope: bankScope,
          id: q.id,
          revision: q.revision,
          selected,
          attempt: mode === "review" ? attemptId : null,
        });
      }
      if (!button.isConnected) return;
      for (const [index, choice] of choices.entries()) {
        const right = index === r.correct,
          picked = index === r.selected;
        if (!right && !picked) continue;
        choice.classList.add(right ? "answer-right" : "answer-missed");
        const label = document.createElement("small");
        label.textContent = right
          ? picked
            ? "答对了"
            : "正确答案"
          : "我的选择";
        choice.append(label);
      }
      $("result").innerHTML =
        feedback(r) +
        (mode === "mock"
          ? btn("next", exam.current ? "下一题" : "查看本场复盘", "primary")
          : "");
      msg("");
      if (mode === "mock") click("next", () => renderExam());
      if (mode === "review") await refresh();
    } catch (x) {
      choices.forEach((choice) => (choice.disabled = false));
      button.disabled = false;
      throw x;
    }
  });
}
function feedback(r) {
  return `<div class="feedback"><strong class="${r.selected === r.correct ? "good" : "bad"}">${r.selected === r.correct ? "回答正确" : "本题选 " + labels[r.correct]}</strong><p>${esc(r.reasons[r.selected])}</p>${r.selected !== r.correct ? `<p>正确选项 ${labels[r.correct]} · ${esc(r.reasons[r.correct])}</p>` : ""}${r.card.evidence ? `<p class="evidence">简历依据 · ${esc(r.card.evidence)}</p>` : ""}<h3>面试时可以这样说</h3><p>${esc(r.spoken)}</p>${r.followup ? `<details><summary>继续追问 · ${esc(r.followup)}</summary><p>${esc(r.followup_answer)}</p></details>` : ""}</div>`;
}
async function review() {
  const rows = await api("mistakes");
  if (page !== "review") return;
  $("view").innerHTML =
    head(
      "错题复习",
      "按最后一次作答收集错题。再次答对后，这道题会从待复习列表移出。",
    ) +
    (rows.length
      ? `<div class="index"><div class="list">${rows.map((q) => `<button class="item" data-num="${q.attempt}">${esc(q.title)}<small>${esc(q.stage)}</small></button>`).join("")}</div><section id="detail" class="question">${empty("选一道错题，换个思路再答一次。")}</section></div>`
      : empty("当前没有待复习的错题。"));
  document.querySelectorAll("[data-num]").forEach(
    (el) =>
      (el.onclick = async () => {
        try {
          attemptId = Number(el.dataset.num);
          activeQuestion = await api("mistake?id=" + attemptId);
          ask(activeQuestion, "review");
        } catch (x) {
          msg(x.message, true);
        }
      }),
  );
}
function mock() {
  const resumes = state.materials.filter((x) => x.kind === "resume");
  $("view").innerHTML =
    head(
      "模拟面试",
      "练一场连续的选择题面试，也可以从自己的某一版简历生成专属题。",
    ) +
    `<div class="layout"><div class="stack"><section class="panel"><h2>开始一场面试</h2><div class="formrow"><label for="mockScope">题目范围</label><select id="mockScope">${setOptions()}</select></div><div class="formrow"><label for="mockTopic">公共题专题</label><select id="mockTopic">${topicOptions()}</select></div><div class="actions">${btn("startMock", "开始面试", "primary")}</div></section><section class="panel"><h2>从我的简历出题</h2>${resumes.length ? `<div class="formrow"><label for="resumePick">选择生成或修订过的简历</label><select id="resumePick">${resumes.map((x) => opt(x.id, "简历 V" + x.id + " · 资料 V" + x.parent + " · " + x.mode, "")).join("")}</select></div><div class="formrow">${modeButton("personalModel")}</div><div class="actions">${btn("personal", "生成专属题")}</div>` : `<p class="hint">先生成一份简历，即可按本人职责和项目出题。</p>${btn("toWorkspace", "去生成简历", "link")}`}</section></div><section class="panel"><h2>最近场次</h2>${state.sessions.length ? state.sessions.map((s) => `<div class="rowblock between"><div><b>第 ${s.id} 场</b><p class="meta">${s.scope === "public" ? "公共面试" : "简历专属面试"} · 已答 ${s.count} 题</p></div><button data-session="${s.id}">${s.done ? "复盘" : "继续"}</button></div>`).join("") : empty("完成的场次和答题中的面试会保存在这里。")}</section></div>`;
  const filter = () =>
    ($("mockTopic").disabled = $("mockScope").value !== "public");
  filter();
  on("mockScope", "change", filter);
  click("toWorkspace", () => go("workspace"));
  click("personal", async () => {
    const b = $("personal");
    b.disabled = true;
    try {
      const r = await api("personal", {
        resume_id: Number($("resumePick").value),
        use_model: $("personalModel").checked,
      });
      await refresh();
      bankScope = String(r.id);
      mock();
      msg("生成了 " + r.count + " 道本人专属题，已选中此题集。");
    } finally {
      b.disabled = false;
    }
  });
  click("startMock", async () => {
    exam = await api("mock/start", {
      scope: $("mockScope").value,
      topic: $("mockTopic").value,
    });
    renderExam();
  });
  document.querySelectorAll("[data-session]").forEach(
    (el) =>
      (el.onclick = async () => {
        try {
          exam = await api("mock?id=" + el.dataset.session);
          renderExam();
        } catch (e) {
          msg(e.message, true);
        }
      }),
  );
}
function renderExam() {
  if (exam.current) {
    $("view").innerHTML =
      head(
        "模拟面试",
        "第 " + (exam.history.length + 1) + " 题 / 最多 " + exam.limit + " 题",
      ) +
      `<div id="detail" class="question"></div><div class="actions">${btn("leaveMock", "保存并返回")}</div>`;
    ask(exam.current, "mock");
    click("leaveMock", () => go("mock"));
  } else {
    const n = exam.history.filter((x) => x.selected === x.correct).length;
    $("view").innerHTML =
      head(
        "本场复盘",
        "已答 " + exam.history.length + " 题，答对 " + n + " 题。",
      ) +
      `<div class="stack">${exam.history.map((r, i) => `<details class="version"><summary>第 ${i + 1} 题 · ${r.selected === r.correct ? "答对" : "答错"} · ${esc(r.card.title)}</summary><p>${esc(r.card.prompt)}</p><p>我的选择 · ${esc(r.card.options[r.selected])}</p>${feedback(r)}</details>`).join("")}</div><div class="actions">${btn("again", "返回面试", "primary")}</div>`;
    click("again", () => go("mock"));
  }
}
async function teacher() {
  if (!state.teacher) {
    await go("workspace");
    return;
  }
  const batches = await api("teacher/batches");
  $("view").innerHTML =
    head(
      "教师题库维护",
      "导入转写，核对提问和答案后发布。发布的题目供本机公共练习和模拟面试共用。",
    ) +
    `<div class="layout"><section class="panel"><h2>导入面试转写</h2><div class="formrow"><label for="source">转写文本</label><textarea id="source" rows="8" placeholder="面试官：……&#10;候选人：……"></textarea><input id="files" type="file" multiple accept=".txt,.md,text/plain,text/markdown"></div><div class="formrow">${modeButton("importModel")}</div><div class="actions">${btn("preview", "整理本批", "primary")}</div><hr><label for="bankFile">载入其他电脑导出的题库更新包</label><input id="bankFile" type="file" accept=".json"></section><section class="panel"><h2>批次记录</h2>${batches.length ? batches.map((b) => `<div class="rowblock"><div class="between"><b>批次 ${b.id}</b><span class="badge">${b.published ? "已发布" : "待核对"}</span></div><p class="meta">${esc(b.created)} UTC</p><div class="actions"><button data-batch="${b.id}">查看</button>${b.published ? `<a class="download" href="/api/teacher/export?id=${b.id}" download>导出更新包</a>${b.can_undo ? `<button class="danger" data-undo="${b.id}">撤回</button>` : ""}` : ""}</div></div>`).join("") : empty("还没有导入批次。")}</section></div><div id="batchDetail" class="section"></div>`;
  on("files", "change", async () => {
    const texts = await Promise.all(
      Array.from($("files").files).map((f) => f.text()),
    );
    $("source").value = texts.join("\n\n---\n\n");
  });
  click("preview", async () => {
    let b = $("preview");
    b.disabled = true;
    try {
      preview = await api("teacher/preview", {
        text: $("source").value,
        use_model: $("importModel").checked,
      });
      await teacher();
      renderBatch();
    } finally {
      b.disabled = false;
    }
  });
  on("bankFile", "change", async () => {
    const file = $("bankFile").files[0];
    if (file) {
      preview = await api("teacher/package", JSON.parse(await file.text()));
      await teacher();
      renderBatch();
    }
  });
  document.querySelectorAll("[data-batch]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          preview = await api("teacher/batch?id=" + b.dataset.batch);
          renderBatch();
        } catch (x) {
          msg(x.message, true);
        }
      }),
  );
  document.querySelectorAll("[data-undo]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          if (
            !window.confirm(
              "撤回这批公共题目及新增问法？已完成的场次仍可复盘。",
            )
          )
            return;
          await api("teacher/undo", { batch: Number(b.dataset.undo) });
          await teacher();
          msg("批次已撤回。");
        } catch (x) {
          msg(x.message, true);
        }
      }),
  );
}
function renderBatch() {
  const batch = preview,
    host = $("batchDetail");
  const sameBatch = host.dataset.batch === String(batch.id);
  const checked = new Set(
    sameBatch
      ? [...host.querySelectorAll("input:checked")].map((b) => b.dataset.choice)
      : [],
  );
  host.dataset.batch = batch.id;
  const check = (kind, i, key) =>
    `<input type="checkbox" data-${kind}="${i}" data-choice="${esc(key)}" ${checked.has(key) ? "checked" : ""}>`;
  const detail = (q) =>
    `<details><summary>核对题面、选项和参考答案</summary><div class="prose">${!batch.published && q.review_question ? `<p class="evidence">来源提问${q.source_ref ? " · " + esc(q.source_ref) : ""}：${esc(q.review_question)}</p>` : ""}<p>${esc(q.prompt)}</p>${q.options.map((o, j) => `<p>${labels[j]}. ${esc(o)} · ${esc(q.reasons[j])}</p>`).join("")}<p><b>正确答案 ${labels[q.correct]}</b></p><p>${esc(q.spoken)}</p><p>${esc(q.followup)}　${esc(q.followup_answer)}</p></div></details>`;
  const cards = batch.cards
    .map(
      (q, i) =>
        `<div class="rowblock"><label>${batch.published ? "" : check("new", i, q.id)} ${esc(q.title)}</label>${batch.published ? "" : `<button class="link" data-edit-new="${i}">编辑题卡</button>`}${detail(q)}</div>`,
    )
    .join("");
  const merged = batch.merged
    .map(
      (q, i) =>
        `<div class="rowblock"><label>${batch.published ? "" : check("merge", i, "merge-" + i)} 补充问法 · ${esc(q.question)}</label><small>${esc(q.id)}</small>${batch.published ? "" : `<button class="link" data-edit-merge="${i}">编辑问法</button>`}</div>`,
    )
    .join("");
  const pending = batch.pending
    .map(
      (q, i) =>
        `<p class="hint">待确认${q.source_ref ? " · " + esc(q.source_ref) : ""} · ${esc(q.question || q.text || "原文片段")} · ${esc(q.reason || "请核对原记录")} <button class="link" data-resolve="${i}">补成选择题</button></p>`,
    )
    .join("");
  const summary = batch.published
    ? `本批实际发布 ${batch.cards.length} 道新题、${batch.merged.length} 条补充问法。另有 ${batch.omitted.cards} 道新题、${batch.omitted.merged} 条问法和 ${batch.omitted.pending} 条待确认内容未发布。`
    : `新题 ${batch.cards.length} 道，补充问法 ${batch.merged.length} 条，待确认 ${batch.pending.length} 条。请勾选本次要公开的内容。`;
  const retry =
    state.model && !batch.published && batch.pending.some((q) => q.retryable)
      ? btn("retryPending", "用在线模型整理待处理提问")
      : "";
  host.innerHTML = `<section class="panel"><h2>批次 ${batch.id} · ${batch.published ? "已发布" : "发布前核对"}</h2><p class="hint">${summary}</p>${retry}${cards}${merged}${pending}${batch.published ? "" : btn("publish", "发布已勾选内容", "primary")}</section>`;
  click("retryPending", async () => {
    const button = $("retryPending");
    button.disabled = true;
    try {
      msg("正在把待处理提问分批提交给已配置的模型服务…");
      const next = await api("teacher/retry", {
        batch: batch.id,
        revision: batch.revision,
        use_model: true,
      });
      if (
        page === "teacher" &&
        preview?.id === batch.id &&
        button.isConnected
      ) {
        preview = next;
        renderBatch();
        msg("本批已保存，可继续核对。");
      }
    } finally {
      button.disabled = false;
    }
  });
  host
    .querySelectorAll("[data-resolve]")
    .forEach(
      (b) => (b.onclick = () => editCard(Number(b.dataset.resolve), true)),
    );
  host
    .querySelectorAll("[data-edit-new]")
    .forEach(
      (b) => (b.onclick = () => editCard(Number(b.dataset.editNew), false)),
    );
  host
    .querySelectorAll("[data-edit-merge]")
    .forEach(
      (b) => (b.onclick = () => editWording(Number(b.dataset.editMerge))),
    );
  host.scrollIntoView({ behavior: "smooth" });
  click("publish", async () => {
    const cards = [...host.querySelectorAll("[data-new]:checked")].map(
      (b) => batch.cards[b.dataset.new],
    );
    const merged = [...host.querySelectorAll("[data-merge]:checked")].map(
      (b) => batch.merged[b.dataset.merge],
    );
    const r = await api("teacher/publish", {
      batch: batch.id,
      revision: batch.revision,
      cards,
      merged,
    });
    await refresh();
    await teacher();
    preview = await api("teacher/batch?id=" + r.id);
    renderBatch();
    msg("批次 " + r.id + " 已发布，可导出更新包。");
  });
}
function editWording(index) {
  const original = preview.merged[index];
  modal(
    "编辑补充问法",
    `<label for="editWording">适合公开的提问</label><textarea id="editWording" rows="5" maxlength="1200">${esc(original.question)}</textarea><div class="actions">${btn("saveWording", "保存到本批", "primary")}</div><p id="wordingError" role="alert"></p>`,
  );
  click("saveWording", async () => {
    try {
      preview = await api("teacher/draft", {
        batch: preview.id,
        revision: preview.revision,
        kind: "merged",
        index,
        id: original.id,
        question: $("editWording").value,
      });
      $("modal").close();
      renderBatch();
      msg("补充问法已保存。");
    } catch (e) {
      $("wordingError").textContent = e.message;
    }
  });
}
async function go(next) {
  if (page === "workspace") capture();
  page = next;
  msg("");
  await refresh();
  document
    .querySelectorAll("nav button")
    .forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  if (page === "bank") return bank();
  if (page === "mock") return mock();
  if (page === "review") return review();
  if (page === "teacher" && state.teacher) return teacher();
  page = "workspace";
  workspace();
}
async function boot() {
  try {
    const h = new URLSearchParams(location.hash.slice(1));
    if (h.has("teacher")) {
      await api("teacher/open", { key: h.get("teacher") });
      history.replaceState(null, "", location.pathname);
    }
    tax = await api("taxonomy");
    await refresh();
    document
      .querySelectorAll("nav button")
      .forEach(
        (b) =>
          (b.onclick = () =>
            go(b.dataset.page).catch((x) => msg(x.message, true))),
      );
    document.querySelector(".brand").onclick = (e) => {
      e.preventDefault();
      go("workspace").catch((x) => msg(x.message, true));
    };
    click("close", () => $("modal").close());
    await go(state.teacher ? "teacher" : "workspace");
  } catch (x) {
    $("view").innerHTML = head(
      "工作台暂时无法打开",
      "请检查本机启动窗口，再刷新页面。",
    );
    msg(x.message, true);
  }
}
function editCard(index, pending) {
  const original = pending ? preview.pending[index] : preview.cards[index],
    q = pending
      ? {
          title: "",
          prompt: original.question,
          options: ["", "", "", ""],
          reasons: ["", "", "", ""],
          correct: 0,
          stage: tax.stages[3],
          topic: "",
          subtopic: "",
          spoken: "",
          followup: "",
          followup_answer: "",
        }
      : original;
  const field = (id, label, v, rows = 2) =>
    `<div class="formrow"><label for="ec-${id}">${label}</label><textarea id="ec-${id}" rows="${rows}">${esc(v)}</textarea></div>`;
  modal(
    pending ? "补充待确认题" : "编辑发布题卡",
    field("title", "题名", q.title, 1) +
      field("prompt", "题干与必要条件", q.prompt) +
      `<div class="formrow"><label for="ec-stage">面试环节</label><select id="ec-stage">${tax.stages.map((v) => opt(v, v, q.stage)).join("")}</select> <select id="ec-topic" aria-label="技术专题">${topicOptions(q.topic)}</select> <select id="ec-sub" aria-label="技术子类"></select></div>` +
      q.options
        .map(
          (o, i) =>
            field("o" + i, "选项 " + labels[i], o, 1) +
            field("r" + i, labels[i] + " 的判定理由", q.reasons[i], 1),
        )
        .join("") +
      `<div class="formrow"><label for="ec-correct">正确选项</label><select id="ec-correct">${labels.map((l, i) => opt(i, l, q.correct)).join("")}</select></div>` +
      field("spoken", "可直接口述的回答", q.spoken, 3) +
      field("followup", "下一问", q.followup) +
      field("followup_answer", "下一问的口述答法", q.followup_answer) +
      `<div class="actions">${btn("commitCard", "保存到本批", "primary")}</div><p id="cardError" role="alert"></p>`,
  );
  const fill = () => {
    $("ec-sub").innerHTML =
      opt("", "请选择子类", "") +
      (tax.topics[$("ec-topic").value] || [])
        .map((v) => opt(v, v, q.subtopic))
        .join("");
  };
  fill();
  on("ec-topic", "change", fill);
  click("commitCard", async () => {
    const value = (k) => $("ec-" + k).value.trim();
    let updated = {
      ...q,
      stage: value("stage"),
      topic: value("topic"),
      subtopic: value("sub"),
      correct: Number(value("correct")),
      options: labels.map((_, i) => value("o" + i)),
      reasons: labels.map((_, i) => value("r" + i)),
    };
    for (const k of [
      "title",
      "prompt",
      "spoken",
      "followup",
      "followup_answer",
    ])
      updated[k] = value(k);
    try {
      if (
        [
          updated.title,
          updated.prompt,
          updated.spoken,
          updated.followup,
          updated.followup_answer,
          ...updated.options,
          ...updated.reasons,
        ].some((x) => !x) ||
        new Set(updated.options).size !== 4
      )
        throw Error("请填写完整题面、四个不同的选项、各项理由和口述回答。");
      if (pending) {
        preview = await api("teacher/manual", {
          batch: preview.id,
          revision: preview.revision,
          index,
          question: original.question,
          card: updated,
        });
      } else {
        preview = await api("teacher/draft", {
          batch: preview.id,
          revision: preview.revision,
          kind: "cards",
          index,
          id: original.id,
          card: updated,
        });
      }
      $("modal").close();
      renderBatch();
      msg("题卡已保存到本批，重新打开后可继续核对。");
    } catch (x) {
      $("cardError").textContent = x.message;
    }
  });
}
function backupMenu() {
  modal(
    "本机学生资料",
    `<p>备份包含当前学生的简历、面试稿、专属题、作答及错题，请保存到自己的私有目录。换人前请先下载一份。</p><div class="toolbar"><a class="download" href="/api/backup" download>下载我的私有备份</a></div><div class="formrow"><label for="restoreFile">从文件恢复为独立工作区</label><input type="file" id="restoreFile" accept=".json"></div><div class="actions">${btn("newStudent", "切换到新学生")}</div><p class="hint">切换后，当前浏览器会进入独立工作区。已保存的材料可通过刚下载的备份重新打开。</p>`,
  );
  const reset = async () => {
    $("modal").close();
    draft = null;
    parts = null;
    bankScope = "public";
    activeQuestion = null;
    exam = null;
    page = "";
    await go("workspace");
  };
  click("newStudent", async () => {
    if (!window.confirm("已保存好当前学生的备份，切换到新的空白工作区？"))
      return;
    await api("student/new", {});
    await reset();
  });
  on("restoreFile", "change", async () => {
    const f = $("restoreFile").files[0];
    if (f && window.confirm("要把这个学生备份恢复为独立工作区并切换吗？")) {
      await api("student/restore", JSON.parse(await f.text()));
      await reset();
      msg("已恢复备份。");
    }
  });
}
boot();
