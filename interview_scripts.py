"""Version-bound five-point and eighteen-point interview rehearsal manuscripts."""

import hashlib
import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from http.client import HTTPException
from pathlib import Path

import llm
import materials


RULES = "interview-v1.2.0"
REF = Path(__file__).parent / "skills" / "offer-interview-scripts" / "references"
FIVE = ("项目起因、痛点", "项目架构", "项目难点与解决办法", "技术讲解", "项目优化")
MAIN_POINTS = (0, 1, 6, 2, 8)
CHINESE = "一二三四五六七"
HAN = re.compile(r"[\u3400-\u9fff]")
PUNCT = re.compile(r"[，。；：、？！]")
WORDS = re.compile(r"[A-Za-z0-9]+")
GAPS = re.compile(
    r"填写此处|替换为自己的|该同学应|原简历未提供|本简历未提供|以下为占位|\{[^{}\n]+\}|【待填】"
)
CONTACT = re.compile(
    r"(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}|[\w.+%-]+@[\w.-]+\.[a-zA-Z]{2,}|(?<!\d)\d{17}[\dXx](?!\d)|(?:微信号?|QQ|联系方式)\s*[:：]\s*\S+"
)


@lru_cache(maxsize=4)
def reference(name):
    return json.loads((REF / (name + ".json")).read_text(encoding="utf-8"))


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _estimate(text):
    return round(
        len(HAN.findall(text)) * 60 / 230
        + len(WORDS.findall(text)) * 0.23
        + len(PUNCT.findall(text)) * 0.24
    )


def _sentences(text):
    return [
        s.strip()
        for s in re.findall(r"[^。！？!?\n]+[。！？!?]?", str(text))
        if s.strip()
    ]


def _polish(text):
    edits = {
        "从而能够": "可以",
        "进行了核对": "核对了",
        "进行逐项核查": "逐项核查",
        "我本人我": "我",
        "我负责我负责": "我负责",
        "我参与我参与": "我参与",
        "。。": "。",
        "。；": "。",
        "。 。": "。",
        "；。": "。",
    }
    for original, spoken in edits.items():
        text = text.replace(original, spoken)
    return text.strip()


def _oral_length(candidates, target, high):
    """Keep complete clauses and stop at a natural sentence within the delivery window."""
    out, seen = [], set()
    for paragraph in candidates:
        for sentence in _sentences(_polish(paragraph)):
            sentence = sentence.rstrip("；;，, ")
            if sentence[-1:] not in "。！？!?":
                sentence += "。"
            key = re.sub(r"\W", "", sentence)
            if key in seen:
                continue
            if _estimate(sentence) > high:
                continue
            if _estimate("".join(out) + sentence) <= high:
                out.append(sentence)
                seen.add(key)
            if _estimate("".join(out)) >= target:
                return "".join(out)
    return "".join(out)


def _source(resume):
    return str(
        resume.get("text", "") if isinstance(resume, dict) else resume or ""
    ).strip()


def _issue(code, section, message, source=""):
    return {"code": code, "section": section, "message": message, "source": source}


def _fact(p, *fields, limit=1):
    return _polish(p.get(*fields, limit=limit)).strip("。；; ")


ROLE_IN_PROJECT = re.compile(
    r"在(?:采用|使用|基于)\s*(.{1,55}?)\s*(?:的)?(?:项目|系统|模块)中[，,]\s*((?:我)?(?:负责|参与|协助|配合).+)"
)
BUSINESS = re.compile(
    r"(?:人员|用户|同事|教师|客服|工程师|财务|运营).{0,35}(?:需要|收到|核对|查询|检查|容易|要|难以)"
)


def _as_role(text):
    if not text:
        return ""
    embedded = ROLE_IN_PROJECT.match(text)
    if embedded:
        return _as_role(embedded[2])
    text = re.sub(r"^(?:本人|个人)(?=负责|参与|实现)", "我", text)
    if text.startswith(("我", "团队", "同事", "由", "与", "协助", "配合")):
        return ("我" if text.startswith(("协助", "配合", "与")) else "") + text
    return (
        "我" + text
        if re.match(
            "负责|参与|实现|对接|维护|设计|编写|开发|交付|校验|验证|整理|检查|保留|为|建立|用|把|将|补|按|增加|提供|提取|构建|通过|支持|独立",
            text,
        )
        else "我的工作涉及" + text
    )


def _fact_key(value):
    value = re.sub(
        r"^(?:项目实现使用|项目采用|项目使用|技术上使用|技术栈[：:]|我(?=负责|参与|配合|实现|独立)|本人(?=负责|参与))",
        "",
        value.strip(),
    )
    return _norm(value)


def _projects(text, profile):
    if not re.search(r"(?m)^#{2,3}\s*项目(?:经历|经验|介绍)\s*$", text):
        return []
    originals = {}
    for idx, raw_input in enumerate(profile.get("projects", []), 1):
        if isinstance(raw_input, str):
            original = materials.parse_project(raw_input, idx)
            originals.setdefault(original.title, []).append(original)
    projects = []
    for raw in materials.selected_resume_projects(text):
        # These common resume headings carry ownership/evidence semantics, even if visually bold.
        raw = raw.replace("**", "")
        raw = re.sub(
            r"(?m)^\s*[-•]?\s*(?:我的职责|本人工作|个人工作|责任描述|核心职责|项目责任)\s*[:：]",
            "本人职责：",
            raw,
        )
        raw = re.sub(r"(?m)^\s*[-•]?\s*(?:技术环境|技术工具)\s*[:：]", "技术栈：", raw)
        raw = re.sub(
            r"(?m)^\s*[-•]?\s*(?:验证方式|验证结果|成果验证|核验方式)\s*[:：]",
            "验证：",
            raw,
        )
        raw = re.sub(r"(?m)^\s*[-•]?\s*(?:分工|协作边界)\s*[:：]", "职责边界：", raw)
        p = materials.parse_project(raw, len(projects) + 1)
        # Recover the user's labels only for an identical fact in this project block of the selected
        # version. Never append facts from an older profile or from the skills/education sections.
        matched = originals.get(p.title, [])
        labels = {}
        if len(matched) == 1:
            for original_key, value in matched[0].facts:
                labels.setdefault(_fact_key(value), set()).add(original_key)
        annotated = []
        for key, value in p.facts:
            tech_role = ROLE_IN_PROJECT.fullmatch(value)
            if tech_role:
                annotated.extend(
                    [("tech", tech_role[1].strip()), ("role", tech_role[2])]
                )
                continue
            combined = re.match(
                r"^(.{4,120}?)[，,]\s*(?:难点在于|难点是|困难在于|难的是)(.+)", value
            )
            if combined and BUSINESS.search(combined[1]):
                annotated.extend([("background", combined[1]), ("issue", combined[2])])
                continue
            candidates = labels.get(_fact_key(value), set())
            if len(candidates) == 1:
                key = next(iter(candidates))
            if re.match(
                r"^(?:(?:其他)?(?:组员|同事|团队|队友)|由.{1,10}(?:负责|完成))", value
            ):
                key = "scope"
            elif key not in ("role", "scope") and re.match(
                r"^(?:我|本人)?(?:负责|参与|协助|配合|亲手|独立完成)", value
            ):
                key = "role"
            elif key == "other" and BUSINESS.search(value):
                key = "background"
            elif key == "other" and re.search(
                r"超时|重复提交|混用|丢失|容易遗漏", value
            ):
                key = "issue"
            elif key in ("other", "flow") and value.startswith("项目实现使用"):
                key = "tech"
            annotated.append((key, value))
        p.facts = annotated
        projects.append(p)
    return projects


def _context(project):
    body = project.title + " " + " ".join(v for _, v in project.facts)
    catalog = reference("scenarios")
    relevant = [
        (key, len(re.findall(v["pattern"], body, re.I)))
        for key, v in catalog.items()
        if v["pattern"]
    ]
    domain, hits = max(relevant, key=lambda pair: pair[1])
    if re.search(
        catalog["dispatch"]["pattern"],
        project.title + " " + _fact(project, "role", "flow", "check"),
        re.I,
    ):
        domain, hits = "dispatch", 1
    c = dict(catalog[domain] if hits else catalog["general"])
    c["domain_key"] = domain if hits else "general"
    c["title"] = project.title
    # Tie a sample to the business object when the selected version actually names it.
    objects = {
        "rag": (
            "设备手册",
            "退换货条款",
            "报销制度",
            "采购制度",
            "质检手册",
            "产品说明",
            "维修手册",
            "制度条款",
            "巡检规范",
            "合同条款",
        ),
        "agent": (
            "发货工单",
            "补货请求",
            "订单",
            "采购单",
            "退款申请",
            "售后工单",
            "工单",
            "理赔申请",
            "缴费记录",
            "排班请求",
        ),
        "sql": (
            "销售额",
            "营收",
            "排班记录",
            "账单",
            "流水",
            "库存",
            "退款",
            "经营指标",
        ),
        "ocr": ("发票", "合同", "扫描件", "图纸", "收据", "检验单", "采购单", "单据"),
        "train": ("意图", "缺陷", "标签", "分类样本", "语音", "文本样本"),
    }
    subject = next((s for s in objects.get(c["domain_key"], ()) if s in body), "")
    if subject:
        c["ticket"] = {
            "rag": f"一条查{subject}的问题",
            "agent": (
                "一笔" + subject
                if subject.endswith(("请求", "申请"))
                else f"一次{subject}处理"
            ),
            "sql": f"一条核对{subject}的查询",
            "ocr": f"一份需要核对的{subject}",
            "train": f"一个需要判别{subject}的样本",
        }[c["domain_key"]]
    background = _fact(project, "background")
    role = _as_role(_fact(project, "role"))
    scope = re.sub(
        r"^(?:团队分工|团队职责|协作范围|职责分工|协作边界)\s*[:：]\s*",
        "",
        _fact(project, "scope"),
    )
    delivery = _fact(project, "result")
    check = _fact(project, "check")
    flow = _fact(project, "flow")
    tech = _fact(project, "tech")
    issue = _fact(project, "issue")
    fix = _fact(project, "solution")
    env = _fact(project, "deploy") or next(
        (
            v
            for _, v in project.facts
            if re.search(
                "测试环境|测试机|本地|本机|生产环境|试运行|预发布|开发环境|课堂演示", v
            )
        ),
        "",
    )
    feedback = _fact(project, "feedback")
    metric = next(
        (
            v
            for k, v in project.facts
            if k in ("check", "result", "scale") and re.search(r"\d", v)
        ),
        "",
    )
    c.update(
        business=(background + "。" if background else ""),
        role=role or "我的具体分工还需要补一条能核对的工作记录",
        scope=scope
        or (role + "；我只按这段工作说明交付范围" if role else "自己的分工还需要核对"),
        delivery=(
            delivery + "。"
            if delivery
            else (check + "。" if check else "我先把可以核对的交付范围说清。")
        ),
        proof=(
            check + "。"
            if check
            else (
                delivery + "。"
                if delivery
                else "要验证这项工作，我会固定输入和预期结果。"
            )
        ),
        flow=(flow + "。" if flow else "我先把业务对象和实际处理动作放到一条线上。"),
        technology=(
            f"这里用到的技术是{tech}。"
            if tech
            else f"我会先讲{project.title}里实际使用的办法。"
        ),
        difficulty=issue or f"我把“{c['risk']}”当作需要防范的设计风险",
        solution=fix
        or f"如果要处理“{c['risk']}”，我会先收集同一次请求的输入和中间结果",
        deployment=env.strip("。；")
        if env
        else "实际运行环境和上线范围还要以发布记录核实",
        feedback=feedback or "我还没有可引用的客户或经理评价",
        measurement=metric.strip("。；")
        if metric
        else "我能解释交付怎样核对，但没有可确认的上线收益数字",
        scale=_fact(project, "scale", "data")
        or "要说数据有多大，我需要先核对对应版本的清单和去重口径",
        costsentence=c["cost"],
    )
    if c["domain_key"] == "agent":
        c["out"] = "业务处理结果和确认记录"
    c["fact_quality"] = {
        "role": bool(role),
        "business": bool(background or flow),
        "proof": bool(delivery or check),
    }
    c["actual"] = {
        "background": background,
        "role": role,
        "scope": scope,
        "flow": flow,
        "issue": issue,
        "solution": fix,
        "tech": tech,
        "check": check,
        "result": delivery,
        "environment": env,
    }
    return c


def _setup(profile, text):
    projects = _projects(text, profile)
    contexts = [_context(p) for p in projects]
    name_from_doc = re.search(r"(?m)^#\s+([^\n]+)", text)
    name = name_from_doc[1].strip() if name_from_doc else ""
    name = re.sub(r"\s*[|｜·]\s*(?:个人|求职)?简历.*$", "", name)
    target = re.search(
        r"(?:求职方向|求职意向|目标岗位|应聘岗位)\s*[:：]\s*([^\n|｜，；]+)", text
    )
    target = target[1].strip("。 ") if target else ""

    def score(entry):
        p, c = entry
        coverage = sum(c["fact_quality"].values())
        depth = len(
            {
                k
                for k, v in p.facts
                if k
                in (
                    "role",
                    "check",
                    "flow",
                    "issue",
                    "solution",
                    "result",
                    "tech",
                    "scope",
                )
            }
        )
        return coverage, depth, -materials.project_priority(p), min(len(p.facts), 15)

    ordered = sorted(zip(projects, contexts), key=score, reverse=True)
    return name, target, ordered


def _rows(c):
    rows = [
        {
            "title": r["title"],
            "answer": _polish(r["answer"].format_map(c)),
            "followups": [
                [_polish(q.format_map(c)), _polish(a.format_map(c))]
                for q, a in r["followups"]
            ],
        }
        for r in reference("questions")
    ]
    facts = " ".join(c["actual"].values())
    for probe in reference("probes"):
        if re.search(probe["pattern"], facts, re.I):
            rows[probe["id"]]["followups"] = [
                pair.copy() for pair in probe["followups"]
            ]
    return rows


def _intro(name, target, c):
    return _oral_length(
        [
            f"面试官您好，我叫{name}。" if name else "面试官您好。",
            f"我这次应聘的是{target}。" if target else "",
            f"我参与过{c['title']}。{c['business']}{c['role']}。",
            c["actual"]["flow"],
            ("这里得留意一件事：" + c["actual"]["issue"])
            if c["actual"]["issue"]
            else "",
            ("对应的做法是" + c["actual"]["solution"])
            if c["actual"]["solution"]
            else "",
            ("最后交付的是" + re.sub(r"^(?:我)?交付(?:了)?", "", c["actual"]["result"]))
            if c["actual"]["result"]
            else "",
            ("验证时，" + c["actual"]["check"]) if c["actual"]["check"] else "",
            c["actual"]["scope"],
            f"拿{c['ticket']}来说，即使前面已经返回了消息，最后还要核对{c['trace']}，把这一次的处理对象和结果对上。遇到条件不全的输入，我会先确认缺了哪一项，这比给出一个看起来完整的答复更重要。",
            f"如果再往下问，我会只改一个条件，比如{c['variant']}，对照{c['mid']}怎样变化。这样区分得开：是原始条件就不够，还是处理以后才出了偏差。我希望继续做这种能追到实际交付的工作。",
            f"如果您想看具体做法，我可以从那次核对讲起，说明输入怎么变、哪一步应该跟着变，以及怎样借助{c['out']}识别一次看似成功的错误处理。",
        ],
        88,
        104,
    )


def _routes(c, rows):
    routes = []
    for title, ids, short, medium, long, extra in reference("routes"):
        anchors = [rows[i - 1] for i in ids]
        phrases = [text.format_map(c) for text in (short, medium, long, extra)]
        texts = [[a["answer"], *[pair[1] for pair in a["followups"]]] for a in anchors]
        short_candidates = [
            phrases[0],
            f"我会从{c['trace']}核对这一点。",
            f"这样可以看清{c['out']}该怎样判断。",
        ]
        routes.append(
            (
                title,
                [
                    _oral_length(short_candidates, 14, 22),
                    _oral_length(
                        [phrases[1], *[t[1] for t in texts], *[t[0] for t in texts]],
                        60,
                        72,
                    ),
                    _oral_length(
                        [
                            phrases[2],
                            phrases[3],
                            *[t[2] for t in texts],
                            *[t[0] for t in texts],
                            *[t[1] for t in texts],
                        ],
                        116,
                        139,
                    ),
                ],
            )
        )
    return routes


def _examples(c):
    if c["domain_key"] == "dispatch":
        return (
            "**样例 A｜正常｜结构演练，虚构编号**\n\n输入：客服提交工单“练习甲”，诉求是查催办进度。中间：按标识找到唯一对应工单，核对其诉求。输出：进入该场景约定的催办处理队列。",
            "**样例 B｜边界｜结构演练，非生产记录**\n\n输入：两个联系人同名，只提供姓名。中间：保留候选而不擅自挑选，提示补充可区分的编号。输出：等待客服确认，尚未分派。",
            "**样例 C｜失败或人工｜结构演练，非生产记录**\n\n输入：用户要求分派，但没有订单号也不能确认工单。中间：标识核对失败，业务去向无法确定。输出：保留诉求交人工核对，不显示分派成功。",
        )
    return (
        f"**样例 A｜正常｜结构演练，非生产数据**\n\n输入：{c['ticket']}，{c['params']}齐全。中间：核查{c['mid']}。输出：{c['out']}，能回到{c['trace']}。",
        f"**样例 B｜边界｜结构演练，非生产数据**\n\n输入：{c['variant']}。中间：重新判定改变的条件，比较新旧适用范围。输出：按新条件核对，不能机械沿用上一笔结果。",
        f"**样例 C｜失败或转人工｜结构演练，非生产数据**\n\n输入：同一业务对象缺少必要信息。中间：无法确认{c['mid']}是否满足要求。输出：{c['exit']}，同时保留可回查的输入。",
    )


def _extra(i, c):
    if i == 9:
        return [
            f"### 指标说明卡\n\n本人可定位的结果：{c['measurement']}。建议补测指标：{c['metric']}。评测对象是一次可独立复核的请求，统计单位为条。分子为满足“{c['passrule']}”的请求数；分母为按固定规则纳入的全部请求数。公式：分子 ÷ 分母。样本来源和环境需和当时的记录对应，基线与最终值没有同批对照时不比较。\n\n手算仅作口径演练：三条输入中两条符合约定、一条不符合，那么分子为二、分母为三。这不是该项目的实测成绩，也不能证明生产收益。"
        ]
    if i == 11:
        return list(_examples(c))
    if i == 16:
        return [
            f"### Bad Case 卡｜风险演练\n\n输入：{c['ticket']}。期望：{c['out']}与{c['trace']}相符。实际（演练设定）：{c['bad']}。假设错误层：产生{c['mid']}或交付结果的一步。根因仍需对照确认：{c['diagnosis']}。拟定修复：{c['fix']}。回归：{c['regression']}。剩余边界：一条样例跑通只能说明该输入恢复。"
        ]
    return []


def _qa(c, rows):
    # Choose and order distinct follow-ups through the actual business path, then its failure branches.
    keys = (
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
        (4, 0),
        (4, 1),
        (5, 0),
        (5, 1),
        (2, 0),
        (3, 0),
        (6, 0),
        (7, 0),
        (7, 1),
        (11, 0),
        (11, 1),
        (8, 1),
        (9, 0),
        (10, 1),
        (16, 1),
        (17, 1),
    )
    pairs = [rows[i]["followups"][j] for i, j in keys]
    # The brief question contains a project cue when it can stand alone on the question bank.
    cues = {2: c["mid"], 5: c["ticket"], 8: c["alt"], 13: c["variant"], 16: c["metric"]}
    return [
        (f"围绕“{cues[i]}”，{q[0].lower() + q[1:]}" if i in cues else q, a)
        for i, (q, a) in enumerate(pairs)
    ]


def _five_sections(c, rows, full):
    out = []
    for j, (title, idx) in enumerate(zip(FIVE, MAIN_POINTS), 1):
        out.extend([f"### {j}. {title}", rows[idx]["answer"]])
        if j == 3 and full:
            out.extend(
                [
                    f"#### 难点一｜输入条件及来源\n\n作为风险演练，我会先核对{c['params']}，确认{c['trace']}确实属于同一对象。条件不够时，{c['exit']}。",
                    f"#### 难点二｜定位中间错误\n\n假设{c['bad']}，我会{c['diagnosis']}。只有出现可重复的差异，才能把根因指向那个环节。",
                    f"#### 难点三｜修复后的边界\n\n按演练，{c['variant']}，这个变化可能影响{c['out']}。我会{c['regression']}。",
                ]
            )
        if full:
            out.append(rows[idx]["followups"][0][1])
        if j == 4:
            out.append(c["role"] + "。" + rows[3]["followups"][0][1])
        if j == 5:
            out.append(c["proof"] + rows[7]["followups"][1][1])
    return out


def _compose(kind, name, c, side, intro, rows):
    header = f"# {name}｜" + ("五点面试稿" if kind == "five" else "十八点面试准备稿")
    identity = f"主项目：{c['title']}\n\n本人工作：{c['role']}。"
    intro_head = "## 二、自我介绍｜约90秒（60—120秒）"
    if kind == "five":
        short = _oral_length(
            [
                c["business"],
                c["role"] + "。",
                c["actual"]["flow"],
                c["actual"]["tech"],
                c["actual"]["issue"],
                c["actual"]["solution"],
                c["delivery"],
                c["proof"],
                c["actual"]["scope"],
                rows[4]["answer"],
                rows[2]["answer"],
                rows[6]["answer"],
                rows[7]["answer"],
                rows[8]["answer"],
                rows[5]["followups"][1][1],
                rows[9]["followups"][0][1],
                rows[15]["followups"][0][1],
                rows[12]["answer"],
            ],
            172,
            201,
        )
        out = [
            header,
            "## 一、个人定位与项目安排",
            identity,
            "这个项目能把本人动作和交付依据连起来。",
            intro_head,
            intro,
            "**练习提示：** 先按正常语速朗读，记录真实用时。",
            "## 三、主项目｜约3分钟项目短讲",
            short,
            "## 四、主项目五点展开",
            *_five_sections(c, rows, True),
            "## 五、业务全流程与技术全链路",
            f"### 业务全流程\n\n{c['business']}按演练，使用者给出{c['ticket']}，核对{c['params']}，拿{c['out']}作判断。条件不全时，{c['exit']}。",
            f"### 技术全链路\n\n{c['flow']}{c['role']}。若走一笔演练输入，我会观察{c['mid']}，再回查{c['trace']}；如果{c['risk']}，先暂停确认，再决定下一步。",
        ]
        if side:
            out.extend(
                [
                    "## 六、第二项目｜" + side[0]["title"],
                    *_five_sections(side[0], _rows(side[0]), False),
                ]
            )
        else:
            out.extend(
                ["## 六、第二项目｜无第二项目", "本版只有一个项目，集中准备主线即可。"]
            )
        out.append("## 七、其余项目｜精简备讲")
        for ctx in side[1:]:
            out.extend(
                [
                    "### " + ctx["title"],
                    ctx["business"],
                    "流程与分工：" + ctx["role"] + "。",
                    "设计难点：" + ctx["difficulty"] + "。",
                    "方法与取舍："
                    + ctx["technology"]
                    + "演练时，"
                    + ctx["costsentence"]
                    + "。",
                    "验证与优化：" + ctx["proof"],
                ]
            )
        if len(side) < 2:
            out.append("其余经历只按追问需要补充。")
        out.append("## 八、20 道针对性追问与参考答案")
        for i, (q, a) in enumerate(_qa(c, rows), 1):
            out.extend([f"**{i}. {q}**", a])
        out.extend(
            [
                "## 九、综合面试稿与面试前核对",
                "业务方向：" + rows[0]["answer"],
                "技术方向：" + rows[7]["answer"],
            ]
        )
    else:
        out = [
            header,
            identity,
            intro_head,
            intro,
            "**练习提示：** 本段和五点稿共用，按正常语速实测。",
        ]
        for i, row in enumerate(rows):
            out.extend(
                [
                    f"## {i + 1:02}｜{row['title']}",
                    "**面试时可以这样说：**",
                    row["answer"],
                ]
            )
            for j, (q, a) in enumerate(row["followups"], 1):
                out.extend([f"**追问{j}：{q}**", a])
            out.extend(_extra(i, c))
        out.append("# 七条主线｜口述训练")
        for i, (title, versions) in enumerate(_routes(c, rows)):
            out.append(f"## 主线{CHINESE[i]}：{title}")
            for seconds, passage in zip((15, 60, 120), versions):
                out.extend([f"**{seconds}秒：**", passage])
        out.append("## 面试前核对")
    out.append(
        f"核对{c['title']}所用的版本、本人分工和交付原件。{c['deployment']}。演练不计入实际项目成绩，排练用时以本人朗读为准。"
    )
    return _polish("\n\n".join(out))


def _portion(text, prefix, following):
    start = re.search(r"(?m)^" + prefix + r"[^\n]*\n", text)
    if not start:
        return ""
    return re.split(r"(?m)^" + following, text[start.end() :], maxsplit=1)[0].strip()


def _intro_text(text):
    return _portion(text, r"## 二、自我介绍", r"(?:\*\*练习提示|## )")


def _base_title(text):
    match = re.search(r"(?m)^主项目[：:]\s*([^\n]+)", text)
    return match[1].strip() if match else ""


def _norm(value):
    return "".join(re.findall(r"[\w\u3400-\u9fff]+", value.casefold()))


def _duplicates(values):
    normalized = []
    for value in values:
        key = _norm(
            re.sub(r"^(?:我会|我先|那|那么|请问|如果|围绕“[^”]+”，)", "", value)
        )
        for prev in normalized:
            if key == prev or (
                min(len(key), len(prev)) >= 9
                and 0.7 < len(key) / max(1, len(prev)) < 1.45
                and SequenceMatcher(None, key, prev).ratio() >= 0.88
            ):
                return True
        normalized.append(key)
    return False


def _traced(needle, answer):
    if not needle:
        return False
    src, body = _norm(needle), _norm(answer)
    return src in body or (
        len(src) >= 9 and any(src[i : i + 8] in body for i in range(len(src) - 7))
    )


def _needs_anchor(question, answer, c, facts):
    keys = (
        "title",
        "params",
        "mid",
        "out",
        "trace",
        "risk",
        "metric",
        "ticket",
        "variant",
        "criterion",
        "passrule",
        "alt",
    )
    if any(c[k] in question + answer for k in keys):
        return False
    return not any(
        _traced(v, question + answer) for _, v in facts if len(_norm(v)) >= 6
    )


COUNT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:[%％]|个百分点|万条|万份|条|份|个月|毫秒|台|万元|倍|小时|年)"
)
CLAIMED_ROLE = re.compile(
    r"(?:我|本人)(?:主要)?负责(?:了)?(?!的)([^。；;，,：:]{2,70})"
)
ASSERTION = re.compile(
    r"(?:我(?:们)?|团队|项目|系统)(?:已经|实际|曾经|独立|亲自|全权|主导|牵头|负责部署|负责上线)|(?:成功|正式|已在生产|已经|全面)上线|生产.{0,4}(?:部署|发布)|上线后.{0,18}(?:提升|达到|降低|增长)|客户.{0,6}(?:认可|好评|表示|评价很高)|(?:准确率|召回率|命中率|成功率|收益|延迟).{0,8}(?:提升|降低|达到|增长|下降)|我(?:使用了|实现了|编写了|搭建了|部署了|完成了|训练了|微调了)"
)
HYPOTHESIS = re.compile(
    r"如果|假设|若|拟定|演练|不能.{0,5}(?:说|算)|没有|还没|没有证据|需要|尚未|不代表|未确认|我会|能否|不承诺|无法"
)


def _fact_error(sentence, project_source, original=""):
    simple = _norm(sentence)
    normalized_source = _norm(project_source)
    if (
        not simple
        or simple in normalized_source
        or (original and simple in _norm(original))
    ):
        return ""
    nums = COUNT.findall(sentence)
    for value in nums:
        if value.strip() not in project_source:
            return "数值或单位找不到对应的本项目记录"
        matching = [s for s in _sentences(project_source) if value.strip() in s]
        patterns = (
            r"线上|生产",
            r"提升|涨幅|下降|降低",
            r"个百分点",
            r"准确率|正确率",
            r"召回率|命中率",
            r"收益|节省",
        )
        if not any(
            all(not re.search(k, sentence) or re.search(k, s) for k in patterns)
            for s in matching
        ):
            return "同一数字换了指标、适用环境或比较含义"
    for claim in CLAIMED_ROLE.finditer(sentence):
        if re.search(r"如果|假如|假设|要是|假定", sentence[: claim.start()]):
            continue
        work = _norm(claim[1])
        source_lines = [
            s
            for s in _sentences(project_source)
            if not re.match(r"(?:其他|组员|同事|团队|队友|由)", s)
        ]
        if claim[0] in original or any(
            work in _norm(s) or SequenceMatcher(None, work, _norm(s)).ratio() >= 0.72
            for s in source_lines
        ):
            continue
        return "本人承担的具体工作缺少本项目原句支持"
    if HYPOTHESIS.search(sentence) and not re.search(
        r"(?:我(?:独立|主导)|我负责.{0,8}(?:上线|部署|训练)).{1,45}(?:，|。|$)",
        sentence,
    ):
        return ""
    for word in (
        "独立上线",
        "独立部署",
        "独立完成",
        "独立负责",
        "全权负责",
        "从零搭建",
        "主导",
        "生产上线",
        "正式上线",
    ):
        if word in sentence and word not in project_source:
            return "这句话扩大了本人职责或已完成的范围"
    if ASSERTION.search(sentence):
        pieces = [_norm(s) for s in _sentences(project_source)]
        if not any(
            len(p) >= 6
            and (p in simple or SequenceMatcher(None, simple, p).ratio() > 0.72)
            for p in pieces
        ):
            return "已发生的工作、结果或反馈缺少原句支持"
    return ""


def _check_claims(text, ordered, kind):
    main = ordered[0][0]
    sources = {p.title: "\n".join(v for _, v in p.facts) for p, _ in ordered}
    current = main.title
    issues = []
    for line in text.splitlines():
        if line.startswith("## 六、第二项目") and len(ordered) > 1:
            current = ordered[1][0].title
        elif line.startswith("## 八、"):
            current = main.title
        elif line.startswith("### ") and line[4:].strip() in sources:
            current = line[4:].strip()
        if line.startswith(("#", "**")) or not line.strip():
            continue
        for sentence in _sentences(line):
            if not (
                COUNT.search(sentence)
                or ASSERTION.search(sentence)
                or CLAIMED_ROLE.search(sentence)
            ):
                continue
            problem = _fact_error(sentence, sources[current])
            if problem and sentence not in {i["source"] for i in issues}:
                issues.append(_issue("fact_drift", current, problem, sentence))
    return issues


def check_script(kind, profile, resume, text, five_text=None):
    if kind not in ("five", "eighteen"):
        raise ValueError("请选择五点稿或十八点稿。")
    source = _source(resume)
    text = str(text or "")
    name, target, ordered = _setup(profile, source)
    intro = _intro_text(text)
    issues = []

    def require(condition, code, section, message, detail=""):
        if not condition:
            issues.append(_issue(code, section, message, detail))

    require(bool(ordered), "resume", "简历版本", "需要一份能够定位项目经历的选定简历。")
    selected_name = str(profile.get("name") or "").strip()
    require(
        not selected_name or not name or selected_name == name,
        "identity",
        "学生资料",
        "所选简历姓名与当前档案不一致。",
        name,
    )
    if ordered:
        p, c = ordered[0]
        require(
            c["fact_quality"]["role"],
            "role",
            "主项目",
            "补一句自己做过的动作和分工。",
            p.title,
        )
        require(
            c["fact_quality"]["proof"],
            "evidence",
            "主项目",
            "请说明一项交付或核对方法。",
            p.title,
        )
        require(
            c["fact_quality"]["business"],
            "business",
            "主项目",
            "请说明服务对象或具体请求。",
            p.title,
        )
        require(
            _base_title(text) == p.title,
            "main_project",
            "主项目",
            "主项目须与这版简历的讲稿安排相同。",
            _base_title(text),
        )
        ownership = re.search(r"(?m)^本人工作[：:]([^\n]+)", text)
        personal = c["actual"]["role"]
        require(
            ownership and _traced(personal, ownership[1]) and _traced(personal, intro),
            "role_evidence",
            "介绍与本人工作",
            "请用本人负责的具体动作开场，协作方职责单独说明。",
            personal,
        )
        require(
            not name or f"我叫{name}" in intro,
            "intro_identity",
            "自我介绍",
            "正式开场需要沿用当前学生身份。",
        )
        for raw in profile.get("projects", []):
            if not isinstance(raw, str):
                continue
            old_title = materials.parse_project(raw, 1).title
            if len(old_title) >= 3 and old_title not in source and old_title in text:
                issues.append(
                    _issue(
                        "old_project",
                        "项目经历",
                        "正文含当前简历已移除的项目。",
                        old_title,
                    )
                )
        if selected_name:
            require(
                text.startswith("# " + name + "｜"),
                "identity",
                "稿件标题",
                "稿件姓名与选定版本不一致。",
            )
        issues.extend(_check_claims(text, ordered, kind))
    estimated = _estimate(intro)
    require(
        60 <= estimated <= 120 and len(HAN.findall(intro)) >= 150,
        "intro_time",
        "自我介绍",
        "请保留一份文字估时 60–120 秒的完整自我介绍。",
    )
    if kind == "eighteen" and five_text:
        require(
            intro == _intro_text(five_text)
            and _base_title(text) == _base_title(five_text),
            "five_drift",
            "与五点稿对照",
            "两稿的正式介绍和主项目必须相同。",
        )
    require(
        not GAPS.search(text),
        "placeholder",
        "口述正文",
        "删除占位符、未完成字段或教师编辑提示。",
    )
    if kind == "five":
        short = _portion(text, "## 三、主项目", "## 四、")
        if ordered:
            c = ordered[0][1]
            require(
                _traced(c["actual"]["role"], short)
                and any(
                    _traced(v, short)
                    for v in (c["actual"]["check"], c["actual"]["result"])
                ),
                "short_evidence",
                "3分钟短讲",
                "请在短讲中说清实际本人动作与一次验证或交付。",
                c["actual"]["role"],
            )
        require(
            140 <= _estimate(short) <= 240,
            "short_time",
            "3分钟短讲",
            "短讲应能交代一条完整请求和本人的动作。",
        )
        for prefix, end in (("四、主项目五点", "五、"), ("六、第二项目", "七、")):
            group = _portion(text, "## " + prefix, "## " + end)
            if prefix.startswith("六") and ordered and len(ordered) == 1:
                require(
                    "只有一个项目" in group,
                    "second",
                    "第二项目",
                    "标明这版仅有一个主项目。",
                )
            else:
                headers = re.findall(r"(?m)^### ([1-5])\. (.+)", group)
                require(
                    [int(n) for n, _ in headers] == list(range(1, 6))
                    and all(
                        len(HAN.findall(b)) >= 15
                        for b in re.split(r"(?m)^### [1-5]\. [^\n]+\n", group)[1:]
                    ),
                    "five_points",
                    prefix,
                    "五个部分各自需要一段可练习的答法。",
                )
        require(
            len(re.findall(r"(?m)^#### 难点[一二三]", text)) >= 3
            and all(
                s in text
                for s in ("业务全流程", "技术全链路", "综合面试稿", "面试前核对")
            ),
            "five_flow",
            "五点展开",
            "补全三类难点、请求流程和核对部分。",
        )
        area = _portion(text, "## 八、", "## 九、")
        qa = re.findall(
            r"(?ms)^\*\*(\d+)\. ([^\n]+?)\*\*\s*\n(.*?)(?=^\*\*\d+\.|\Z)", area
        )
        require(
            len(qa) >= 20
            and [int(n) for n, _, _ in qa] == list(range(1, len(qa) + 1))
            and all(len(HAN.findall(a)) >= 18 for _, _, a in qa),
            "target_questions",
            "项目追问",
            "需要至少二十个有完整答复的项目追问。",
        )
        require(
            not _duplicates([q for _, q, _ in qa])
            and not _duplicates([a for _, _, a in qa]),
            "repeated_answers",
            "项目追问",
            "重复问法或套用同一答案，需要分别回应。",
        )
        if ordered:
            coverage = sum(
                not _needs_anchor(q, a, ordered[0][1], ordered[0][0].facts)
                for _, q, a in qa
            )
            require(
                coverage >= 9,
                "generic_answers",
                "项目追问",
                "请把追问落在这个项目的动作、对象、边界和结果上。",
            )
    else:
        headings = list(re.finditer(r"(?m)^## (\d{2})｜([^\n]+)", text))
        require(
            [h[0] for h in headings]
            == [
                f"## {i:02}｜{r['title']}"
                for i, r in enumerate(reference("questions"), 1)
            ],
            "eighteen_titles",
            "十八点",
            "请保留课堂原题名、编号和顺序。",
        )
        main_answers = []
        for idx, h in enumerate(headings):
            body = text[
                h.end() : headings[idx + 1].start()
                if idx + 1 < len(headings)
                else len(text)
            ].split("# 七条主线", 1)[0]
            oral = _portion(
                body, r"\*\*(?:面试时可以这样说|口述回答)[：:]\*\*", r"\*\*追问"
            )
            qas = re.findall(
                r"(?ms)^\*\*追问([12])：[ \t]*([^\n]+?)\*\*\s*\n(.*?)(?=^\*\*追问|^### |^\*\*样例|\Z)",
                body,
            )
            answers = [a.strip() for _, _, a in qas]
            require(
                len(HAN.findall(oral)) >= 35
                and [n for n, _, _ in qas] == ["1", "2"]
                and all(len(HAN.findall(a)) >= 12 for a in answers),
                "point_depth",
                h[0],
                "请补主答及两层有答复的追问。",
            )
            require(
                not _duplicates([q for _, q, _ in qas]) and not _duplicates(answers),
                "duplicate_probe",
                h[0],
                "两层追问须考察不同细节。",
            )
            main_answers.append(oral)
        require(
            not _duplicates(main_answers),
            "repeated_points",
            "十八点主答",
            "不同考点不能套用同一段话。",
        )
        for pattern, words in (
            ("10｜", ("分子", "分母", "公式", "手算")),
            ("12｜", ("样例 A", "样例 B", "样例 C", "中间", "输出", "输入")),
            ("17｜", ("期望", "实际", "根因", "修复", "回归", "边界")),
        ):
            card = _portion(text, "## " + pattern, r"(?:## \d{2}｜|# 七条主线)")
            require(
                all(w in card for w in words),
                "special_card",
                pattern,
                "本节缺少指标、脱敏输入输出或失败复测的必要内容。",
            )
        route_part = _portion(text, "# 七条主线", "## 面试前")
        tracks = list(
            re.finditer(r"(?m)^## 主线([一二三四五六七])：([^\n]+)", route_part)
        )
        require(
            [m[2] for m in tracks] == [r[0] for r in reference("routes")],
            "tracks",
            "七条主线",
            "七条口述主线需要按原序写全。",
        )
        for idx, h in enumerate(tracks):
            section = route_part[
                h.end() : tracks[idx + 1].start()
                if idx + 1 < len(tracks)
                else len(route_part)
            ]
            tiers = re.findall(
                r"(?ms)^\*\*(15|60|120)秒：\*\*\s*(.*?)(?=^\*\*\d+秒|\Z)", section
            )
            require(
                [int(n) for n, _ in tiers] == [15, 60, 120]
                and all(
                    lo <= _estimate(body) <= hi
                    for (_, body), (lo, hi) in zip(
                        tiers, [(10, 22), (50, 75), (100, 145)]
                    )
                )
                and all(len(HAN.findall(body)) >= 20 for _, body in tiers),
                "track_time",
                h[0],
                "三档讲法需要展开同一主线，长度须适合各档。",
            )
    return {
        "status": "draft" if issues else "ready",
        "issues": issues,
        "main_project": ordered[0][0].title if ordered else "",
        "intro_seconds": estimated,
        "source_digest": _digest(source),
        "rules": RULES,
        "retryable": False,
        "timing_basis": "正文估时，未进行本人朗读计时",
    }


def _private_removed(text, name):
    safe = CONTACT.sub("〔隐去〕", text)
    return safe.replace(name, "这位候选人") if name else safe


def _edit_problem(proposed, original, source, minimum):
    if not isinstance(proposed, str) or len(HAN.findall(proposed)) < minimum:
        return "未返回足够完整的口述回答"
    if len(proposed) > 850 or GAPS.search(proposed) or "\n#" in proposed:
        return "段落含未完成字段、异常长度或额外标题"
    for sentence in _sentences(proposed):
        problem = _fact_error(sentence, source, original)
        if problem:
            return problem
    if set(COUNT.findall(original)) - set(COUNT.findall(proposed)):
        return "删掉了原有数值或单位"
    if re.search(r"如果|若|演练|我会", original) and not re.search(
        r"如果|若|演练|我会|可以|需要|先|再|会先|要|应该|建议|可用|可按|能否|可以|例如|可作为|可把",
        proposed,
    ):
        if re.search(
            r"做了|实现了|完成了|部署了|正式上线|已经|项目采用了|曾经", proposed
        ):
            return "把演练或建议改成了已经完成的事实"
    if re.search(r"没有|还没|不代表|不能", original) and not re.search(
        r"未|没|还要|不|需|仅|只|待", proposed
    ):
        return "原有否定或范围边界未保留"
    if (
        re.search(r"配合|参与|协助", original)
        and re.search(r"独立|主导|全权", proposed)
        and not re.search(r"独立|主导|全权", original)
    ):
        return "把参与改成了独立负责"
    if any(
        token.lower() not in (source + original).lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{2,}", proposed)
    ):
        return "出现原项目与原答没有的技术名或标识"
    return ""


def _rewrite_row(item, original, source):
    """Validate the main answer and two follow-ups independently; never discard a sound sibling."""
    original_texts = [original["answer"], *[a for _, a in original["followups"]]]
    replies = item.get("replies")
    proposed = [item.get("answer")]
    for i, (question, _) in enumerate(original["followups"]):
        entry = replies[i] if isinstance(replies, list) and i < len(replies) else None
        if isinstance(entry, list) and len(entry) == 2:
            entry = entry[1] if _norm(str(entry[0])) == _norm(question) else None
        elif isinstance(entry, dict):
            query = entry.get("question", question)
            entry = (
                entry.get("answer") if _norm(str(query)) == _norm(question) else None
            )
        proposed.append(entry)
    final, changes, rejected = [], [], []
    for index, (new, old) in enumerate(zip(proposed, original_texts)):
        field = ("主答", "第一层追答", "第二层追答")[index]
        value = _polish(new) if isinstance(new, str) else None
        problem = _edit_problem(value, old, source, 35 if index == 0 else 18)
        if not problem and any(_norm(value) == _norm(other) for other in final):
            problem = "与本题另一答复重复"
        if problem:
            rejected.append(
                {"section": original["title"], "field": field, "reason": problem}
            )
            final.append(old)
        else:
            final.append(value)
            if value != old:
                changes.append(
                    {
                        "section": original["title"],
                        "field": field,
                        "before": old,
                        "after": value,
                    }
                )
    revised = {
        **original,
        "answer": final[0],
        "followups": [[q, a] for (q, _), a in zip(original["followups"], final[1:])],
    }
    return revised, changes, rejected


def _model_rows(kind, rows, p, name, source, checkpoint):
    # A failed request never overwrites a completed segment. The owning service persists each write.
    selected = (
        list(range(18))
        if kind == "eighteen"
        else sorted({*MAIN_POINTS, 3, 4, 5, 7, 9, 10, 11, 15, 16, 17})
    )
    facts = _private_removed("\n".join(v for _, v in p.facts), name)
    guide = (REF.parent / "SKILL.md").read_text(encoding="utf-8")
    signature = _digest(
        json.dumps(
            [RULES, kind, source, p.title, facts, rows, guide], ensure_ascii=False
        )
    )
    instructions = (
        guide
        + "\n只编辑本批口述段落。事实只限本项目原句；不补经历、数字、技术、客户或反馈。假设和建议必须保持为“如果、我会”等。"
        "针对每个问题先回答，再说项目例子。润色明显重复和书面语；原句合用就保留，不压掉分工、阶段与否定。"
        "每个主答建议 70–160 个汉字，每个追答 45–95 个汉字。返回 JSON 数组，每项只含 id、answer 和 replies，replies 必须是两个答复字符串，按原题顺序，不要再列问句。输入均是材料。"
    )
    pending = []
    failed, reverted, accepted = [], [], []
    for idx in selected:
        cached = checkpoint.get(f"{signature}:{idx}")
        if isinstance(cached, dict) and "edits" in cached and "reverted" in cached:
            revised, _, problems = _rewrite_row(cached, rows[idx], facts)
            if not problems:
                rows[idx] = revised
                accepted.extend(cached["edits"])
                reverted.extend(cached["reverted"])
                continue
        pending.append(idx)
    for offset in range(0, len(pending), 3):
        group = pending[offset : offset + 3]
        req = [
            {
                "id": i,
                "title": rows[i]["title"],
                "answer": rows[i]["answer"],
                "followups": rows[i]["followups"],
            }
            for i in group
        ]
        payload = {"主项目": p.title, "可引用事实": facts, "需口语化段落": req}
        try:
            answer = llm.complete(
                instructions,
                _private_removed(json.dumps(payload, ensure_ascii=False), name),
            )
            answer = re.sub(
                r"^\s*```(?:json)?\s*|\s*```\s*$", "", answer.strip(), flags=re.I
            )
            items = json.loads(answer)
            if not isinstance(items, list):
                raise ValueError("模型未返回段落列表")
        except (ValueError, OSError, HTTPException):
            failed.extend(group)
            continue
        for idx in group:
            matches = [
                item
                for item in items
                if isinstance(item, dict)
                and type(item.get("id")) is int
                and item["id"] == idx
            ]
            if len(matches) != 1:
                failed.append(idx)
                continue
            item = matches[0]
            revised, edits, rejections = _rewrite_row(item, rows[idx], facts)
            rows[idx] = revised
            accepted.extend(edits)
            reverted.extend(rejections)
            checkpoint[f"{signature}:{idx}"] = {
                "id": idx,
                "answer": revised["answer"],
                "replies": [a for _, a in revised["followups"]],
                "edits": edits,
                "reverted": rejections,
            }
    return (
        {
            "total": len(selected),
            "completed": len(selected) - len(failed),
            "missing": [rows[i]["title"] for i in failed],
        },
        reverted,
        accepted,
    )


def _repair_indices(problems, rows, original, c, p):
    """Identify independently edited answer fields responsible for manuscript-level failures."""
    reasons = {}

    def mark(i, j, reason):
        before = original[i]["answer"] if j < 0 else original[i]["followups"][j][1]
        after = rows[i]["answer"] if j < 0 else rows[i]["followups"][j][1]
        if before != after:
            reasons[i, j] = reason

    def duplicates(entries, reason):
        seen = []
        for text, i, j in entries:
            pair = next(
                ((prev, pi, pj) for prev, pi, pj in seen if _duplicates([prev, text])),
                None,
            )
            if pair:
                mark(i, j, reason)
                if (i, j) not in reasons:
                    mark(pair[1], pair[2], reason)
            seen.append((text, i, j))

    all_fields = [(r["answer"], i, -1) for i, r in enumerate(rows)] + [
        (a, i, j) for i, r in enumerate(rows) for j, (_, a) in enumerate(r["followups"])
    ]
    for issue in problems:
        code = issue["code"]
        if code == "repeated_points":
            duplicates(all_fields[: len(rows)], issue["message"])
        elif code == "repeated_answers":
            chosen = {a for _, a in _qa(c, rows)}
            duplicates(
                [entry for entry in all_fields[len(rows) :] if entry[0] in chosen],
                issue["message"],
            )
        elif code == "generic_answers":
            selected = _qa(c, rows)
            needed = 9 - sum(not _needs_anchor(q, a, c, p.facts) for q, a in selected)
            for q, a in selected:
                if needed <= 0:
                    break
                for value, i, j in all_fields[len(rows) :]:
                    if (
                        value == a
                        and _needs_anchor(q, a, c, p.facts)
                        and not _needs_anchor(
                            q, original[i]["followups"][j][1], c, p.facts
                        )
                    ):
                        mark(i, j, issue["message"])
                        needed -= 1
                        break
        elif code in ("point_depth", "duplicate_probe"):
            idx = next(
                (i for i, r in enumerate(rows) if r["title"] in issue["section"]), None
            )
            if idx is not None:
                answers = [
                    (a, idx, j) for j, (_, a) in enumerate(rows[idx]["followups"])
                ]
                if code == "duplicate_probe":
                    duplicates(answers, issue["message"])
                else:
                    for value, i, j in [(rows[idx]["answer"], idx, -1), *answers]:
                        if len(HAN.findall(value)) < (35 if j == -1 else 12):
                            mark(i, j, issue["message"])
        elif code == "fact_drift":
            needle = _norm(issue["source"])
            for value, i, j in all_fields:
                if needle and needle in _norm(value):
                    mark(i, j, issue["message"])
    return reasons


def _section_block(text, heading):
    pattern = r"(?ms)^" + re.escape(heading) + r"[^\n]*\n.*?(?=^#{1,2} |\Z)"
    return re.search(pattern, text)


def _finish(kind, profile, source, five_text, name, p, c, side, intro, rows):
    text = _compose(kind, name, c, side, intro, rows)
    review = check_script(kind, profile, source, text, five_text)
    rounds = []
    original = _rows(c)
    for _ in range(2):
        problems = review["issues"]
        if not problems or any(
            i["code"]
            in (
                "resume",
                "identity",
                "role",
                "evidence",
                "business",
                "old_project",
                "main_project",
                "intro_identity",
                "five_drift",
            )
            for i in problems
        ):
            break
        changes = []
        repairs = _repair_indices(problems, rows, original, c, p)
        for (i, j), reason in repairs.items():
            field = ("主答", "第一层追答", "第二层追答")[j + 1]
            before = rows[i]["answer"] if j == -1 else rows[i]["followups"][j][1]
            after = original[i]["answer"] if j == -1 else original[i]["followups"][j][1]
            changes.append(
                {
                    "section": rows[i]["title"],
                    "field": field,
                    "reason": reason,
                    "before": before,
                    "after": after,
                }
            )
            if j == -1:
                rows[i]["answer"] = after
            else:
                rows[i]["followups"][j][1] = after
        candidate = _compose(kind, name, c, side, intro, rows) if repairs else text
        duration_issues = [
            i for i in problems if i["code"] in ("track_time", "short_time")
        ]
        if duration_issues:
            safe = _compose(kind, name, c, side, intro, original)
            for issue in duration_issues:
                heading = (
                    issue["section"]
                    if issue["code"] == "track_time"
                    else "## 三、主项目"
                )
                old, new = (
                    _section_block(candidate, heading),
                    _section_block(safe, heading),
                )
                if old and new and old[0] != new[0]:
                    candidate = (
                        candidate[: old.start()] + new[0] + candidate[old.end() :]
                    )
                    changes.append(
                        {
                            "section": heading,
                            "reason": issue["message"],
                            "field": "口述时长",
                            "before": old[0],
                            "after": new[0],
                        }
                    )
        if candidate == text or not changes:
            break
        checked = check_script(kind, profile, source, candidate, five_text)
        improved = len(checked["issues"]) < len(problems)
        rounds.append(
            {
                "changes": changes,
                "issues_before": [i["code"] for i in problems],
                "issues_after": [i["code"] for i in checked["issues"]],
                "applied": improved,
            }
        )
        if not improved:
            break
        text, review = candidate, checked
    return text, review, rounds


def build_script(
    kind, profile, resume, five_text=None, use_model=False, checkpoint=None
):
    if kind not in ("five", "eighteen"):
        raise ValueError("请选择五点稿或十八点稿。")
    source = _source(resume)
    name, target, ordered = _setup(profile, source)
    if not ordered:
        text = "简历中的项目经历还不足以生成口述稿。请先补入本人负责的一项工作与可核对的交付。"
        return text, check_script(kind, profile, source, text, five_text)
    p, c = ordered[0]
    rows = _rows(c)
    progress = {"completed": 0, "total": 0, "missing": []}
    reverted, accepted = [], []
    if use_model and all(c["fact_quality"].values()):
        progress, reverted, accepted = _model_rows(
            kind, rows, p, name, source, checkpoint if checkpoint is not None else {}
        )
    intro = _intro(name, target, c)
    if kind == "eighteen" and five_text and _base_title(five_text) == p.title:
        fixed = _intro_text(five_text)
        if fixed:
            intro = fixed
    text, review, rounds = _finish(
        kind,
        profile,
        source,
        five_text,
        name,
        p,
        c,
        [x for _, x in ordered[1:]],
        intro,
        rows,
    )
    for r in rounds:
        if r["applied"]:
            for change in r["changes"]:
                accepted = [
                    e
                    for e in accepted
                    if (e["section"], e["field"])
                    != (change["section"], change["field"])
                ]
    edit_mode = "本机口述编辑"
    if use_model:
        edit_mode = (
            "采用经复核的模型编辑" if accepted else "保留本机原答，未采用模型改写"
        )
    review.update(
        checkpoint=progress,
        repair_rounds=rounds,
        polishing={
            "mode": edit_mode,
            "reverted_sections": list(dict.fromkeys(r["section"] for r in reverted)),
            "rejections": reverted,
            "changes": accepted,
            "applied_model_edits": len(accepted),
            "performed": True,
        },
    )
    if progress["missing"]:
        review.update(status="draft", retryable=True)
        review["issues"].append(
            _issue(
                "model_partial",
                "在线续写",
                "部分段落未取得可解析的回复，可继续本次生成。",
                "、".join(progress["missing"]),
            )
        )
    return text, review
