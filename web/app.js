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
    "姓名：林禾\n求职方向：大模型应用开发工程师\n邮箱：linhe@example.com\n教育经历：2022年9月—2026年6月，示例理工学院，软件工程专业，本科。\n经历：应届生。以下三个项目为课程团队实践，均在本机或教学测试环境验证。\n专业技能：用 Python 和 FastAPI 编写业务接口，用 LangGraph 编排工单助手，用 RAG 检索有版本的制度。",
  projects: [
    "项目一：工单分流助手\n项目时间：2026年2月—2026年4月\n业务：客服收到催单、退换货和无订单号的问题，要查到对应工单并分派。\n本人职责：我用 Python 和 LangGraph 编写查询工具与路由节点。我负责将接口部署在教学测试机，核对工单归属、工具参数和错误回显。\n团队分工：同学负责客服页面。\n流程：请求进入 FastAPI，先提取工单号，再查测试工单表。有多笔候选时向客服确认，缺少字段时转人工。\n难点：编号相近的订单会被误选。我把编号精确匹配放在路由前，保留本次查询使用的工单号。\n验证：我在测试机回放正常工单、多人同名和无编号三类样例，核对最终分派和人工入口。\n交付：可演示的分流接口、请求日志和三类回归样例，没有线上使用统计。",
    "项目二：制度知识库\n项目时间：2025年10月—2025年12月\n业务：客服查询退换货规定时，旧版与新版制度可能同时命中。\n本人职责：我用 RAG 实现按生效日期过滤，并把回答引用连回原始条款。\n流程：把教学制度按条款切块，记录版本和位置，检索时核对日期，回答附上原文。\n验证：在测试环境用同一问题分别查询两个日期，核对返回的版本、例外条件和链接。\n交付：客服可打开回答所依据的制度原文，项目未统计线上收益。",
    "项目三：售后单据核对\n项目时间：2025年6月—2025年8月\n业务：售后专员需要找出退款申请中缺失或格式异常的字段。\n本人职责：我标注退款说明里的订单号和金额，用 LoRA 微调课程提供的小模型抽取字段，再用 Python 校验格式。\n数据：课程提供的脱敏单据样例，训练和验证按单据编号分开。\n验证：我在本地测试缺订单号、金额格式错误和合规单据，把模型抽取的值与人工标注逐项比对，将无法核实的字段送到人工复核。\n交付：字段抽取与校验脚本、可复查的错误单据清单。",
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
  if (!$("basic")) return;
  const fields = document.querySelectorAll("#parts textarea");
  if (fields.length) {
    parts = Array.from(fields, (field) => field.value);
    $("projects").value = parts.join("\n\n");
  }
  draft = { basic: $("basic").value, text: $("projects").value, standard: $("standard").value };
}

function syncGapNotice() {
  const profile = state.profile;
  if (!$("profileIssues") || !profile) return;
  const changed = $("basic").value !== profile.basic || $("projects").value !== profile.projects.join("\n\n") ||
    $("standard").value !== (profile.standard || "auto");
  $("profileIssues").hidden = changed;
  $("gapNotice").hidden = !changed;
}

function statusLabel(kind, value) {
  if (value === "ready") return kind === "resume" ? "可投递" : "可练习";
  if (value === "draft") return "草稿 · 待补充或修订";
  return "历史版本 · 需重新核对";
}

function statusBadge(kind, status) {
  return `<span class="material-tag ${status === "ready" ? "pass" : "check"}">${statusLabel(kind, status)}</span>`;
}

function currentMaterial(kind, profileId) {
  return state.materials.find((item) => item.kind === kind && item.parent === profileId);
}

function issueList(issues) {
  if (!Array.isArray(issues) || !issues.length) return "";
  return `<ul class="issue-list">${issues.map((issue) => {
    const location = issue.label || issue.section || "";
    const problem = issue.question || issue.message || (typeof issue === "string" ? issue : "");
    return `<li>${location ? `<strong>${esc(location)}</strong> · ` : ""}${esc(problem)}${issueEvidence(issue)}</li>`;
  }).join("")}</ul>`;
}

function issueEvidence(issue) {
  const quote = typeof issue.quote === "string" && issue.quote;
  const source = typeof issue.source === "string" && issue.source;
  return (quote ? `<small>待核对表述：${esc(quote)}</small>` : "") +
    (source ? `<small>相关原文：${esc(source)}</small>` : "") +
    (issue.where ? `<small>可以查：${esc(issue.where)}</small>` : "");
}

const clarificationModes = {
  fact: ["补一句事实", "用自己的话补上做过的动作和实际结果，或纠正下面已有的表述。"],
  missing: ["查过了，没有记录", "删去无法核实的数字或结论，写下你查过什么、仍能确认什么。"],
  role: ["这部分不是我做的", "在原文中改清分工：那部分由谁完成？你实际参与了哪一步？"],
};

function profileIssues(profile) {
  const issues = profile?.issues || [];
  if (!issues.length) return "";
  return `<section class="gap-panel" id="profileIssues" aria-labelledby="gapTitle">
    <h3 id="gapTitle">资料 V${esc(profile.id)} 还需补充</h3>
    ${issues.length > 3 ? '<p class="hint">先核对下面三处，保存后继续查看。</p>' : ""}
    ${issues.slice(0, 3).map((issue, index) => `<div class="gap">
      <strong>${esc(issue.label || "资料补充")}</strong><p>${esc(issue.question || issue.message)}</p>
      ${issueEvidence(issue)}
      <div class="gap-actions">${Object.entries(clarificationModes).map(([mode, text]) =>
        `<button data-issue="${index}" data-mode="${mode}">${text[0]}</button>`).join("")}</div>
    </div>`).join("")}</section>`;
}

function materialInfo(item) {
  const parts = [`资料 V${item.parent}`];
  if (item.based_on) parts.push(`简历 V${item.based_on}`);
  if (item.five_id) parts.push(`五点稿 V${item.five_id}`);
  return parts.join(" · ");
}

function workspace() {
  const prof = state.profile;
  if (!draft) draft = { basic: prof?.basic || "", text: prof?.projects.join("\n\n") || "", standard: prof?.standard || "auto" };
  const resume = currentMaterial("resume", prof?.id);
  const five = currentMaterial("five", prof?.id);
  const documents = kinds.map((k) => {
    const item = currentMaterial(k, prof?.id);
    const oldResume = item && k !== "resume" && item.based_on !== resume?.id;
    const oldFive = item && k === "eighteen" && item.five_id && item.five_id !== five?.id;
    const expected = k === "five" ? "先核对当前简历" : "先准备同版简历和五点稿";
    const badge = item ? statusBadge(k, item.status) : "";
    const info = item ? `${materialInfo(item)}${oldResume ? " · 依据旧简历" : oldFive ? " · 依据旧五点稿" : ""}` : (k === "resume" ? "尚未生成" : expected);
    return `<section class="paper"><div><div class="material-heading"><h3>${titles[k]}${item ? " V" + item.id : ""}</h3>${badge}</div>
      <p class="meta">${esc(info)}</p><div class="buttons">
      ${item ? btn("open-" + k, item.status === "ready" ? "打开与导出" : "查看与核对", "link") : ""}
      ${btn("gen-" + k, item ? "单独重生成" : "单独生成", "link")}</div></div></section>`;
  }).join("");
  $("view").innerHTML = head("我的求职材料", "贴入基本信息和准备好的项目。资料齐全后，一次生成简历、五点稿和十八点稿。") +
    `<div class="layout"><section class="panel"><div class="titlebar"><h2>学生资料</h2>${btn("example", "使用虚构示例", "link")}</div>
      <label for="basic">基本信息</label><textarea id="basic" rows="4" placeholder="姓名、联系方式、目标岗位、教育与工作或实践经历">${esc(draft.basic)}</textarea>
      <div class="formrow"><label for="projects">项目材料 · 准备 3–5 个</label><textarea id="projects" rows="7" placeholder="项目一：项目名称&#10;谁在用、我做了什么、怎么验证&#10;&#10;项目二：项目名称">${esc(draft.text)}</textarea>
      <p class="hint">每个项目用“项目一：”“项目二：”开头，或用一个空行分隔。资料还没齐，也可以先保存。</p></div>
      ${btn("split", "检查项目分段", "link")}<div id="parts"></div>
      <div class="formrow"><label for="standard">简历标准</label><select id="standard">
        ${opt("auto", "按岗位自动选择（AI 应用开发使用班级标准）", draft.standard)}
        ${opt("job", "按实际目标岗位", draft.standard)}${opt("class", "AI 应用开发班级标准", draft.standard)}</select></div>
      <hr>${modeButton("online")}
      <div class="actions">${btn("generate", "生成三份材料", "primary")}${btn("save", "保存资料")}</div>
      <div id="generationStatus" role="status" class="statusline"></div><p id="gapNotice" hidden class="hint">资料已改动，保存后可查看本版需要补充的内容。</p>${profileIssues(prof)}</section>
      <section class="stack"><div class="titlebar"><h2>本版材料</h2>${prof ? `<span class="meta">资料 V${prof.id}</span>` : ""}</div>${documents}
      <details class="version"><summary>查看历史材料（${state.materials.length}）</summary><div id="versions">${state.materials.map((item) => `<div class="between"><span class="small">${titles[item.kind]} V${item.id} · ${statusLabel(item.kind, item.status)}<small>${esc(materialInfo(item))}</small></span><button class="link" data-doc="${item.id}">打开</button></div>`).join("")}</div></details>
      <button class="link" id="backupMenu">备份资料与切换学生</button></section></div>`;
  click("backupMenu", backupMenu);
  if (parts) renderParts();
  syncGapNotice();
  $("online").checked = !!state.model && sessionStorage.getItem("offerlab:online") === "yes";
  on("online", "change", () => sessionStorage.setItem("offerlab:online", $("online").checked ? "yes" : "no"));
  on("basic", "input", syncGapNotice);
  on("standard", "change", syncGapNotice);
  click("example", () => {
    if (($("basic").value || $("projects").value) && !window.confirm("用虚构示例替换当前输入框吗？已保存的版本可继续查看。")) return;
    draft = { basic: sample.basic, text: sample.projects.join("\n\n"), standard: "auto" };
    parts = null;
    workspace();
    msg("已填入虚构学生林禾的课堂示例。制作自己的材料时，请替换为本人信息和项目。");
  });
  on("projects", "input", () => {
    parts = null;
    $("parts").innerHTML = "";
    syncGapNotice();
  });
  click("split", async () => {
    capture();
    parts = await projectFields();
    renderParts();
  });
  click("save", async () => {
    const saved = await saveProfile();
    await refresh();
    if (page === "workspace") workspace();
    msg(`资料已保存为 V${saved.id}。${saved.issues?.length ? "可按下方问题继续补充。" : ""}`);
  });
  click("generate", () => generate(kinds));
  for (const k of kinds) {
    click("gen-" + k, () => generate([k]));
    click("open-" + k, () => showDoc(currentMaterial(k, prof?.id).id));
  }
  on("versions", "click", (event) => {
    const id = event.target.closest("button")?.dataset.doc;
    if (id) return showDoc(id);
  });
  on("profileIssues", "click", (event) => {
    const button = event.target.closest("button[data-issue]");
    if (button) return clarify(prof.issues[Number(button.dataset.issue)], button.dataset.mode);
  });
  if (generating) lockWorkspace();
}

function renderParts() {
  $("parts").innerHTML = `<p class="hint">已识别 ${parts.length} 个项目。可逐段修改，或调整上方项目分隔。</p>` +
    parts.map((p, i) => `<label class="small" for="project${i}">项目 ${i + 1}</label><textarea id="project${i}" rows="3">${esc(p)}</textarea>`).join("");
  $("parts").oninput = () => { capture(); syncGapNotice(); };
}

async function projectFields() {
  if (parts) return [...parts];
  if (!draft.text.trim()) return [];
  if (state.profile?.projects.join("\n\n") === draft.text) return [...state.profile.projects];
  return (await api("split", { text: draft.text })).projects;
}

async function saveProfile() {
  capture();
  const projects = await projectFields();
  return api("profile", { basic: draft.basic, projects: projects.filter((p) => p.trim()), standard: draft.standard });
}

async function clarify(issue, mode) {
  capture();
  const projects = await projectFields();
  const index = /^projects\.(\d+)$/.exec(issue.field || "");
  const basic = issue.field === "basic";
  const original = basic ? draft.basic : index ? projects[Number(index[1])] || "" : projects.join("\n\n");
  const place = basic ? "基本信息" : index ? "项目 " + (Number(index[1]) + 1) : "项目材料";
  modal(clarificationModes[mode][0], `<p class="issue-question">${esc(issue.question || issue.message)}</p>
    <div class="fact-evidence">${issueEvidence(issue)}</div><p>${clarificationModes[mode][1]}</p>
    <div class="formrow"><label for="factEdit">${esc(place)} · 修正后的内容</label><textarea id="factEdit" rows="8">${esc(original)}</textarea></div>
    <p id="factError" class="hint" role="status"></p>${btn("applyFact", "保存补充并检查", "primary")}`);
  click("applyFact", async () => {
    const text = $("factEdit").value.trim();
    if (!text || text === original.trim()) {
      $("factError").textContent = "请写入或改正一条自己能确认的事实。";
      return;
    }
    $("applyFact").disabled = true;
    try {
      let out = projects;
      if (index) out.splice(Math.min(Number(index[1]), out.length), 1, text);
      else if (!basic) out = (await api("split", { text })).projects;
      const next = { basic: basic ? text : draft.basic, projects: out.filter((p) => p.trim()), standard: draft.standard };
      const result = await api("profile", next);
      await refresh();
      draft = { basic: next.basic, text: next.projects.join("\n\n"), standard: next.standard };
      parts = null;
      $("modal").close();
      if (page === "workspace") workspace();
      msg(`补充内容已保存到${place} · 资料 V${result.id}。${result.issues?.length ? "请继续核对提示。" : "可以继续生成材料。"}`);
    } catch (error) {
      $("factError").textContent = error.message;
      $("applyFact").disabled = false;
    }
  });
}
let generating = false;
function lockWorkspace() {
  $("view").querySelectorAll("button, textarea, select, input").forEach((el) => { el.disabled = true; });
}

async function generate(todo) {
  if (generating) return;
  const online = $("online").checked;
  const bundle = todo.length > 1;
  let resultMessage = "", failed = false;
  generating = true;
  lockWorkspace();
  try {
    const saved = await saveProfile();
    await refresh();
    const id = saved.id;
    let resume = currentMaterial("resume", id);
    let five = currentMaterial("five", id);
    for (const kind of todo) {
      if (kind !== "resume" && resume?.status !== "ready") {
        resultMessage = `资料 V${id} 需要先有可投递简历。请补充资料或重新核对当前草稿。`;
        break;
      }
      const current = currentMaterial(kind, id);
      const sameResume = kind === "resume" || current?.based_on === resume?.id;
      const sameFive = kind !== "eighteen" || (five?.status === "ready" && current?.five_id === five.id);
      const currentMode = current?.mode || "";
      const sameMode = currentMode === "手工修订" || currentMode.includes(online ? "模型" : "本机");
      if (bundle && current?.status !== "ready" && currentMode === "手工修订" && sameResume && (kind !== "eighteen" || sameFive)) {
        resultMessage = `手改的${titles[kind]} V${current.id} 还需核对。请打开修订正文，或用“单独重生成”从已保存的资料重新生成这份材料。`;
        break;
      }
      if (bundle && current?.status === "ready" && sameResume && sameFive && sameMode) {
        if (kind === "resume") resume = current;
        if (kind === "five") five = current;
        continue;
      }
      const note = "正在生成并核对" + titles[kind] + "…";
      if (page === "workspace") {
        msg(note);
        if ($("generationStatus")) $("generationStatus").textContent = note;
      }
      const body = { kind, profile_id: id, use_model: online };
      if (kind !== "resume") body.resume_id = resume.id;
      if (kind === "eighteen") {
        if (five?.status !== "ready" || five.based_on !== resume.id) {
          resultMessage = `请先生成或重新核对简历 V${resume.id} 对应的五点稿，再生成十八点稿。`;
          break;
        }
        body.five_id = five.id;
      }
      // A retry must address the same server-side generation, even after reloading this tab.
      const pendingKey = "offerlab:generate:" + JSON.stringify(body);
      if (!bundle) {
        body.request_id = sessionStorage.getItem(pendingKey) || crypto.randomUUID();
        sessionStorage.setItem(pendingKey, body.request_id);
      }
      const material = await api("generate", body);
      if (!bundle && !material.review?.retryable) sessionStorage.removeItem(pendingKey);
      if (kind === "resume") resume = material;
      if (kind === "five") five = { ...material, based_on: resume.id };
      if (material.status !== "ready") {
        const first = material.issues?.[0];
        const reason = first?.question || first?.message || "";
        resultMessage = `${titles[kind]} V${material.id} 已保存为草稿。${reason || "打开草稿查看需要补充的内容。"}`;
        break;
      }
      if (!bundle) resultMessage = `${titles[kind]} V${material.id} · ${statusLabel(kind, material.status)}。`;
    }
    if (!resultMessage) resultMessage = "本版简历可投递，五点稿和十八点稿可练习。";
  } catch (error) {
    failed = true;
    resultMessage = `本次生成已停下。${error.message} 已经保存的版本可以继续查看。`;
  } finally {
    generating = false;
    try {
      await refresh();
    } catch (error) {
      failed = true;
      resultMessage = `尚未连上本机服务。恢复连接后可重试，继续核对已保存的材料。`;
    }
    if (page === "workspace") {
      workspace();
      $("online").checked = online && !!state.model;
      msg(resultMessage, failed);
    }
  }
}

async function showDoc(id) {
  const key = Number(id);
  activeDoc = key;
  const m = await api("material?" + params({ id: key }));
  if (activeDoc !== key) return;
  const meta = state.materials.find((x) => x.id === key);
  const kind = meta?.kind || "resume";
  const status = m.status || meta?.status || "legacy";
  const sources = materialInfo({ parent: m.profile_id, based_on: m.based_on, five_id: m.five_id });
  const problems = m.issues || m.review?.issues || [];
  const prefix = status === "draft" ? "草稿 " : status === "legacy" ? "历史版 " : " ";
  const downloads = ["docx", "pdf", "md"].map((fmt) =>
    `<a class="download" href="/api/export?${params({ id: key, fmt })}" download>下载${prefix}${fmt.toUpperCase()}</a>`).join("");
  const advice = m.review?.suggestions || [];
  const checks = [];
  const report = m.review || {};
  if (report.artifacts?.pdf?.pages) {
    const sheets = report.artifacts.pdf.pages;
    checks.push(`实际 PDF 共 ${sheets} 页。Word 正文${report.artifacts.docx?.body_matches ? "与终稿一致" : "仍需核对"}。`);
  }
  if (report.main_project) checks.push(`主项目是“${report.main_project}”。`);
  if (report.intro_seconds) checks.push(`自我介绍按文字估算约 ${report.intro_seconds} 秒，实际用时以本人朗读为准。`);
  if (report.polishing && typeof report.polishing.applied_model_edits === "number" && m.mode.includes("模型")) {
    checks.push(`在线润色中，有 ${report.polishing.applied_model_edits} 处修改通过核对并采用。`);
  }
  const checked = checks.length ? `<details class="version"><summary>查看这版的核对结果</summary>${checks.map((s) => `<p class="hint">${esc(s)}</p>`).join("")}</details>` : "";
  const explanation = status === "legacy" ? '<p class="hint">这份历史材料还没有按当前标准核对。可以阅读原文，或重新核对取得本次结果。</p>' :
    status === "draft" ? '<p class="hint">正文已保存。核对下列内容后，再生成投递或练习版本。</p>' : "";
  modal(titles[kind] + " · V" + key, `<div class="material-heading">${statusBadge(kind, status)}<span class="meta">${esc(sources)} · ${esc(m.mode)}</span></div>
    ${explanation}${issueList(problems)}${checked}
    ${advice.length ? `<details class="version"><summary>可选完善建议（${advice.length}）</summary>${issueList(advice)}</details>` : ""}
    <div class="toolbar">${downloads}${btn("edit", "编辑正文")}
    ${status !== "ready" ? btn("recheck", "重新核对这版材料") : ""}
    ${status === "draft" && m.profile_id === state.profile?.id ? btn("toFacts", "返回补充资料", "link") : ""}</div>
    <p id="docStatus" role="status" class="hint"></p><div class="prose">${reading(m.text || "")}</div>`);
  click("toFacts", async () => {
    $("modal").close();
    await go("workspace");
    ($("profileIssues")?.querySelector("button") || $("basic")).focus();
  });
  click("recheck", async () => {
    $("recheck").disabled = true;
    $("docStatus").textContent = "正在核对这份正文与其来源版本…";
    try {
      const result = await api("material/recheck", { id: key });
      await refresh();
      if (page === "workspace") { capture(); workspace(); }
      await showDoc(result.id);
    } catch (error) {
      $("docStatus").textContent = error.message;
      $("recheck").disabled = false;
    }
  });
  click("edit", () => {
    modal("编辑" + titles[kind] + " · V" + key,
      `<label for="edited">修改后的正文</label><textarea id="edited" rows="20">${esc(m.text)}</textarea>
      <p class="hint">保存后会核对这份修订稿，原版本仍可查看。</p><p id="editError" role="status" class="hint"></p>
      <div class="actions">${btn("saveDoc", "另存修订版", "primary")}</div>`);
    click("saveDoc", async () => {
      $("saveDoc").disabled = true;
      try {
        const result = await api("material/edit", { id: key, text: $("edited").value });
        await refresh();
        if (page === "workspace") { capture(); workspace(); }
        await showDoc(result.id);
      } catch (error) {
        $("editError").textContent = error.message;
        $("saveDoc").disabled = false;
      }
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
  const resumes = state.materials.filter((x) => x.kind === "resume" && x.status === "ready");
  $("view").innerHTML =
    head(
      "模拟面试",
      "练一场连续的选择题面试，也可以从自己的某一版简历生成专属题。",
    ) +
    `<div class="layout"><div class="stack"><section class="panel"><h2>开始一场面试</h2><div class="formrow"><label for="mockScope">题目范围</label><select id="mockScope">${setOptions()}</select></div><div class="formrow"><label for="mockTopic">公共题专题</label><select id="mockTopic">${topicOptions()}</select></div><div class="actions">${btn("startMock", "开始面试", "primary")}</div></section><section class="panel"><h2>从我的简历出题</h2>${resumes.length ? `<div class="formrow"><label for="resumePick">选择已核对的可投递简历</label><select id="resumePick">${resumes.map((x) => opt(x.id, "简历 V" + x.id + " · 资料 V" + x.parent + " · " + x.mode, "")).join("")}</select></div><div class="formrow">${modeButton("personalModel")}</div><div class="actions">${btn("personal", "生成专属题")}</div>` : `<p class="hint">先取得一份可投递简历，再按该版的本人职责和项目生成专属题。</p>${btn("toWorkspace", "去生成简历", "link")}`}</section></div><section class="panel"><h2>最近场次</h2>${state.sessions.length ? state.sessions.map((s) => `<div class="rowblock between"><div><b>第 ${s.id} 场</b><p class="meta">${s.scope === "public" ? "公共面试" : "简历专属面试"} · 已答 ${s.count} 题</p></div><button data-session="${s.id}">${s.done ? "复盘" : "继续"}</button></div>`).join("") : empty("完成的场次和答题中的面试会保存在这里。")}</section></div>`;
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
    sessionStorage.removeItem("offerlab:online");
    for (const key of Object.keys(sessionStorage)) {
      if (key.startsWith("offerlab:generate:")) sessionStorage.removeItem(key);
    }
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
