"""Turn one student's own material into a checked, versionable resume."""

from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import date
from difflib import SequenceMatcher
from itertools import combinations
import hashlib
import io
import json
import re

import fitz
from docx import Document
import materials as m


RULE_VERSION = "resume-2026-11-26.1"
ACTION = re.compile(
    r"整理|标注|设计|写|实现|开发|测试|联调|核对|校验|过滤|接入|构建|切分|分块|切块|保留|引用|搭建|查询|采集|训练|微调|部署|维护|复核|录入|编排|对接|检索|解析|优化|修复|配置|打包|回放|处理|跟进|归档|比对|绘制|核查|汇总|跟踪|评测|清洗|提交|保存|交付|筛选"
)
OTHER_OWNER = re.compile(
    r"(?:同事|组员|团队|其他人|队友|老师|导师|同学|我们)(?:承担|做|实现|负责|完成|独立)|由(?:其他|同事|同学|组员|团队|老师)|(?:并非|并不是|不是|不属于)我(?:的)?(?:职责|负责|做)|我(?:没有|未|没)(?:负责|做|参与)"
)
PERSON = re.compile(
    r"本人|我(?!们)(?:只|仅|主要|配合|协助|参与|负责|做|独立|使用|在|用|实现|完成|维护|编写)|个人(?:职责|贡献|负责)|独立(?:完成|编写|交付)"
)
NEGATIVE = re.compile(
    r"没有|从未|并未|尚未|未曾|未做|未使用|不会|没做过|未参与|未负责|未上线|不涉及|不属于|不是本人"
)
LOCAL = re.compile(
    r"(?:仅|只|目前只|一直只).{0,4}(?:本机|本地|离线|演示|沙箱|测试环境)|尚未上线|未生产上线|未上线|没有.{0,4}上线"
)
PROD = re.compile(
    r"已(?:正式)?上线|生产(?:环境)?(?:已)?(?:部署|上线|投产|运行)|正式上线|线上(?:已)?(?:运行|交付|使用)|上线(?:到|至)生产"
)
METRIC = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s*(?:[%％]|个?百分点)|(?<![\d.])\d+(?:\.\d+)?\s*[%％]"
)
NUMBER_UNIT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(%|％|个百分点|条|份|笔|次|秒|毫秒|分钟|小时|人次|人天|万元|万条|万次|元|台|万份|倍|张|件|年)"
)
BASIS = re.compile(
    r"(?:\d+|[零一二三四五六七八九十百千]+)\s*(?:条|份|笔|次|样[本例]|个(?:样本|用例|订单|工单)|张|件)|(?:样本|样例|用例|样本量)[：:\s]*\d+|测试集.{0,8}\d+|平均每|每次|每周|每月|每千次|监控窗口|按.{1,12}统计"
)
CHANGE = re.compile(r"提升|提高|增加|增长|降低|下降|减少|增长率|涨幅|优化了|缩短|节省")
BASELINE = re.compile(
    r"基线|改前|改后|优化前|优化后|对照|相比|从.{1,20}(?:到|至)|由.{1,20}(?:到|至)|前后|同批|同一批"
)
CATEGORIES = {
    "Agent": r"\bAgent\b|智能体|LangGraph|工具调用|人工审批|工具编排",
    "RAG": r"\bRAG\b|知识库|混合检索|检索增强|向量检索|召回|分块|带引用",
    "微调": r"微调|LoRA|QLoRA|适配器训练",
    "部署": r"部署|容器化|Docker|发布服务|上线发布",
    "测试": r"测试|评测|验收|验证|回放|回归",
}
TECH_RELEASES = {
    "LangGraph": (date(2024, 1, 1), "https://blog.langchain.com/langgraph/"),
    "MCP": (date(2024, 11, 1), "https://www.anthropic.com/news/model-context-protocol"),
    "DeepSeek-R1": (date(2025, 1, 1), "https://api-docs.deepseek.com/news/news250120"),
    "GPT-4": (date(2023, 3, 1), "https://openai.com/index/gpt-4-research/"),
}
DATE_TOKEN = (
    r"(?:19|20)\d{2}[-./年](?:0?[1-9]|1[0-2])(?:[-./月](?:0?[1-9]|[12]\d|3[01])日?)?月?"
)
SPAN = re.compile(
    rf"({DATE_TOKEN})(?!\d)\s*(?:至|到|[~～—–-])\s*({DATE_TOKEN}|至今|现在)(?!\d)"
)
PLACEHOLDER = re.compile(
    r"待填(?:写)?|待补(?:充)?|待核实|此处填写|待替换|示例数据|模板数字|教师批注|TODO|XXX|\{[^{}]+\}|\[请.{0,20}\]"
)
EDGES = re.compile(
    r"^\s*(?:[-•*]\s*|(?:背景|本人职责|个人职责|项目成果|交付|验证|分工|技术栈|时间)\s*[:：])*"
)
NOISE = re.compile(
    r"手把手|全面赋能|深度赋能|打造(?:智能|业务)?闭环|全方位赋能|赋能业务发展"
)
UPGRADE = re.compile(r"独立|独自|主导|牵头|全权|从零到一|端到端负责|精通|专家级")


def digest(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else value.encode("utf-8")
    ).hexdigest()


def issue(code, field, label, question, where, source="", **extra):
    return dict(
        code=code,
        field=field,
        label=label,
        question=question,
        where=where,
        source=source[:360],
        **extra,
    )


def compact(value):
    return re.sub(r"[^0-9a-zA-Z\u3400-\u9fff%％]", "", value).lower().replace("％", "%")


def source_lines(text):
    return [
        s.strip(" •-*")
        for s in re.split(
            r"[\n；;。！？]+|[,，]\s*(?=(?:本人|我[负参做只仅用]|同事|其他组员|队友|团队负责|我们负责))",
            text,
        )
        if s.strip(" •-*")
    ]


def positive_prod(text):
    return bool(
        PROD.search(
            re.sub(
                r"(?:未|没有|尚未|计划|准备|拟|暂未|并未|不是|不属于|并非).{0,3}(?:正式|生产)?(?:上线|部署|投产)|(?:未|没有|尚未)(?:正式)?上线生产",
                "",
                text,
            )
        )
    )


def metric_supported(sentence, source):
    values = METRIC.findall(sentence)
    if not values:
        return True
    if not BASIS.search(source):
        return False
    if CHANGE.search(sentence) and not BASELINE.search(source):
        return False
    return not m.UNCERTAIN.search(sentence)


def date_bound(token, end=False):
    if token in ("至今", "现在"):
        return date.today()
    parts = list(map(int, re.findall(r"\d+", token)))
    year, month = parts[:2]
    day = (
        parts[2]
        if len(parts) > 2
        else (calendar.monthrange(year, month)[1] if end else 1)
    )
    return date(year, month, day)


def goal_of(profile):
    lines = m.basic_lines(str(profile.get("basic", "")))
    goal = next(
        (
            re.split("[:：]", s, 1)[1].strip()
            for s in lines
            if m.basic_group(s) == "岗位" and re.search("[:：]", s)
        ),
        "",
    )
    if not goal:
        hit = re.search(
            r"(?:希望|准备|想要|计划)?(?:应聘|求职|投递)(?:方向|岗位)?[：:\s]*(.{2,30}?)(?:[，。\n；]|$)",
            str(profile.get("basic", "")),
        )
        goal = hit[1].strip() if hit else ""
    return goal


def project_inputs(profile):
    raw = profile.get("projects", [])
    if (
        not isinstance(raw, list)
        or len(raw) > 5
        or any(not isinstance(v, str) for v in raw)
    ):
        raise ValueError("项目材料可暂存 0–5 项，每个项目请粘贴一段文字。")
    data = []
    for index, text in enumerate(raw):
        if not text.strip():
            continue
        p = m.parse_project(text, index + 1)
        facts = {}
        for k, v in p.facts:
            facts.setdefault(k, []).append(v)
        personal = [
            v
            for k, v in p.facts
            if (k == "role" or PERSON.search(v))
            and not OTHER_OWNER.search(v)
            and re.search(r"[\u3400-\u9fff]{2}", v)
            and ACTION.search(v)
        ]
        if not personal:
            personal = [
                s
                for s in source_lines(text)
                if PERSON.search(s)
                and not OTHER_OWNER.search(s)
                and ACTION.search(s)
                and len(compact(s)) >= 8
            ]
        data.append(
            dict(
                index=index,
                field=f"projects.{index}",
                raw=text,
                parsed=p,
                title=p.title,
                facts=facts,
                personal=personal,
            )
        )
    return data


def project_evidence(item):
    f = item["facts"]
    role = item["personal"]
    context = f.get("background", []) or [
        v
        for _, v in item["parsed"].facts
        if re.search(
            r"需要|为了|原来|面向|痛点|客户|客服|用户|操作员|技术员|财务|业务人员|师傅|家长|同学|运营人员",
            v,
        )
    ]
    result = (
        f.get("result", [])
        + f.get("check", [])
        + f.get("deploy", [])
        + f.get("feedback", [])
    )
    result = [
        s
        for s in result
        if not (NEGATIVE.search(s) and not ACTION.search(s))
        and metric_supported(s, item["raw"])
    ]
    if not result:
        result = [
            v
            for _, v in item["parsed"].facts
            if re.search(
                "可回查|可核查|能回查|通过.{1,10}测试|交付|输出.{2,15}(表|单|结果)|形成.{2,18}(单|表|报告)|演示了|可.{0,5}查看",
                v,
            )
            and metric_supported(v, item["raw"])
        ]
    methods = (
        f.get("flow", [])
        + f.get("solution", [])
        + f.get("tech", [])
        + [s for s in role if ACTION.search(s) and len(compact(s)) >= 6]
    )
    return {"background": context, "role": role, "method": methods, "delivery": result}


def dated_issues(items, basic):
    findings = []
    spans = []
    for item in items + [dict(raw=basic, field="basic", title="工作经历")]:
        raw = item["raw"]
        rows = raw.splitlines() or [raw]
        active_group = ""
        for line in rows:
            if item["field"] == "basic":
                group = m.basic_group(line)
                if group:
                    active_group = group
                if active_group != "工作经历":
                    continue
            for match in SPAN.finditer(line):
                args = (
                    item["field"],
                    item["title"] + "的时间",
                    "请核对开始、结束日期及项目归属；并行项目可以注明分工。",
                    "项目排期、实习证明或本人日历",
                    match[0],
                )
                try:
                    start, end = date_bound(match[1]), date_bound(match[2], True)
                    if (
                        end < start
                        or start > date.today()
                        or (
                            end > date.today()
                            and not re.fullmatch(
                                rf"{date.today().year}[-./年]0?{date.today().month}月?",
                                match[2],
                            )
                        )
                    ):
                        raise ValueError()
                except ValueError:
                    findings.append(issue("invalid_date", *args))
                    continue
                for tech, (floor, url) in TECH_RELEASES.items():
                    if (
                        item["field"] != "basic"
                        and re.search(
                            r"(?<![A-Za-z])" + re.escape(tech) + r"(?![A-Za-z0-9])",
                            raw,
                            re.I,
                        )
                        and end < floor
                    ):
                        findings.append(
                            issue(
                                "tech_date",
                                item["field"],
                                tech + " 的采用时期",
                                f"这段项目结束早于 {tech} 的公开版本。如后来升级，请写实际采用的阶段。",
                                "依赖记录或发布历史",
                                line,
                                reference=url,
                            )
                        )
                spans.append((item["field"], item["title"], start, end, line, raw))
    for i, (field, title, start, end, line, raw) in enumerate(spans):
        if field != "basic":
            owner = re.search(
                r"(?:归属公司|所属公司|项目归属|所属单位)[：:]\s*([^。；\n]{2,30})", raw
            )
            if owner:
                jobs = [
                    r for r in spans if r[0] == "basic" and owner[1].strip() in r[4]
                ]
                if jobs and not any(job[2] <= start <= end <= job[3] for job in jobs):
                    findings.append(
                        issue(
                            "employer_period",
                            field,
                            title + "的任期归属",
                            f"项目的起止不落在{owner[1].strip()}所写任期内。请确认归属、阶段或任职日期。",
                            "任职和项目排期",
                            line + " / " + jobs[0][4],
                        )
                    )
        for f2, t2, s2, e2, l2, raw2 in spans[:i]:
            if (
                (field == "basic") != (f2 == "basic")
                or (field == f2 and field != "basic")
                or max(start, s2) > min(end, e2)
            ):
                continue
            if re.search(
                r"(?:同期|同时|并行)(?:参与|负责|进行|协作|项目|开展|任职|实习)|(?:项目|任职|工作|经历).{0,5}(?:并行|同期)|兼职|兼任|交接期",
                raw + " " + raw2,
            ):
                continue
            findings.append(
                issue(
                    "timeline_overlap",
                    field,
                    title + "的同期安排",
                    f"这段日期与{t2}重合。属于并行协作、同月交接，还是日期要改？",
                    "排期或交接记录",
                    line + " / " + l2,
                )
            )
    return findings


def class_standard(profile):
    basic = str(profile.get("basic", ""))
    goal = goal_of(profile)
    standard = profile.get("standard") or "auto"
    return bool(
        standard == "class"
        or (
            standard == "auto"
            and (
                re.search(
                    r"(?:大模型|AI|LLM).{0,7}(?:应用开发|应用工程)|(?:Agent|RAG).{0,4}应用开发",
                    goal,
                    re.I,
                )
                or re.search(
                    r"按(?:本|就业|AI)?班(?:级)?(?:简历)?标准|按(?:AI|大模型应用开发)?班级规范",
                    basic,
                    re.I,
                )
            )
        )
    )


def capability_review(profile, items):
    basic = str(profile.get("basic", ""))
    goal = goal_of(profile)
    school = class_standard(profile)
    hard = re.findall(
        r"(?:岗位硬性要求|岗位必须|必备能力|硬性要求|必须具备)[^。\n；]{0,80}", basic
    )
    wanted = [
        name
        for name, expr in CATEGORIES.items()
        if school or any(re.search(expr, phrase, re.I) for phrase in hard)
    ]
    ai = bool(re.search(r"AI|大模型|智能体|LLM|Agent|RAG", goal, re.I) or school)
    advice = []
    must = []
    coverage = {}
    for name, expr in CATEGORIES.items():
        backed = []
        for item in items:
            role = item["personal"]
            direct = [
                s for s in role if re.search(expr, s, re.I) and not NEGATIVE.search(s)
            ]
            if name in ("Agent", "RAG"):
                work = (
                    r"工具调用|调用.{0,10}工具|(?:编写|编排|注册|封装|实现|配置|接入).{0,12}工具|工作流|状态(?:图|机|恢复)|分流规则|人工确认|工具路由"
                    if name == "Agent"
                    else r"文档解析|按标题切分|切块|分块|召回|检索|重排|向量化|原文引用|引用.{0,8}原|日期过滤|按.{0,8}版本过滤|过滤检索"
                )
                if re.search(expr, item["raw"], re.I):
                    direct = [
                        s
                        for s in role
                        if re.search(work, s, re.I)
                        and not NEGATIVE.search(s)
                        and not re.search(r"仅.{0,5}前端|只.{0,5}前端|只负责登录", s)
                    ]
                else:
                    direct = []
            if not direct and name == "测试" and role:
                direct = [
                    s
                    for s in item["facts"].get("check", [])
                    if not OTHER_OWNER.search(s) and not NEGATIVE.search(s)
                ]
            if direct:
                backed.append({"field": item["field"], "source": direct[0][:240]})
        if not backed:
            backed = [
                {"field": "basic", "source": s[:240]}
                for s in source_lines(basic)
                if re.search(expr, s, re.I)
                and PERSON.search(s)
                and ACTION.search(s)
                and not (OTHER_OWNER.search(s) or NEGATIVE.search(s) or s in hard)
                and not re.search(r"要求|必须具备|尚待|计划|打算", s)
            ]
        coverage[name] = backed
        if not backed and (ai or name in wanted):
            row = issue(
                "skill_" + name,
                "basic",
                name + " 的本人实践",
                f"有哪一个项目里你亲手做过{name}？可写具体动作与验证；没做过就保留实际经验。",
                "本人课程练习、项目提交或测试记录",
                requirement="明确标准" if name in wanted else "班级能力参考",
            )
            (must if name in wanted else advice).append(row)
    if (
        school
        and coverage["Agent"]
        and coverage["RAG"]
        and not any(
            a["field"] != b["field"] and a["field"] != "basic" and b["field"] != "basic"
            for a in coverage["Agent"]
            for b in coverage["RAG"]
        )
    ):
        must.append(
            issue(
                "class_projects",
                "projects",
                "班级的两个主项目",
                "请指出哪两个不同项目分别支撑本人的 Agent 与 RAG 能力；实际投另一岗位可选岗位标准。",
                "任务单、课程实践或本人交付。",
            )
        )
    return must, advice, coverage


def review_profile(profile):
    basic = str(profile.get("basic", ""))
    items = project_inputs(profile)
    issues = []
    if not goal_of(profile):
        issues.append(
            issue(
                "target",
                "basic",
                "目标岗位",
                "你打算投递什么岗位？写一个目标名称即可。",
                "意向岗位或招聘描述",
            )
        )
    if len(items) < 3:
        issues.append(
            issue(
                "project_count",
                "projects",
                "项目数量",
                f"目前有 {len(items)} 个项目。投递版需要至少 3 个，请补充不同的真实项目，也可以写课程或个人实践。",
                "作业、实习任务、个人项目",
            )
        )
    names = [
        re.split("[:：]", s, 1)[1].strip()
        for s in m.basic_lines(basic)
        if m.basic_group(s) == "姓名" and re.search("[:：]", s)
    ]
    saved = m.cleaned(profile.get("name"))
    if len(set(names)) > 1 or (names and saved and compact(saved) != compact(names[0])):
        issues.append(
            issue(
                "identity",
                "basic",
                "姓名不一致",
                "请确认这份简历属于哪一位同学，只保留本人的材料。",
                "基本信息",
                " / ".join([saved] + names),
            )
        )
    if not saved and not names:
        issues.append(
            issue(
                "name", "basic", "简历姓名", "投递简历使用什么姓名？", "本人的求职信息"
            )
        )
    labels = [compact(p["title"]) for p in items]
    selected = selected_items(profile, items)
    for item in selected:
        f = item["field"]
        title = item["title"]
        ev = project_evidence(item)
        raw = item["raw"]
        if labels.count(compact(title)) > 1:
            issues.append(
                issue(
                    "duplicate_project",
                    f,
                    title + "的项目边界",
                    "同名项目是同一次交付还是两个独立阶段？请确认各自职责和交付，重复的可合并。",
                    "项目任务单或实际交接记录",
                    title,
                )
            )
        missing = [k for k in ev if not ev[k]]
        if missing:
            asks = {
                "background": "谁在什么场景遇到什么问题",
                "role": "你亲手改过哪一环，同事负责什么",
                "method": "用了什么具体方法处理",
                "delivery": "最后交出了什么、或怎样验证它能用",
            }
            issues.append(
                issue(
                    "project_facts",
                    f,
                    title + "的个人经历",
                    "请用一次真实任务说明："
                    + "；".join(asks[k] for k in missing)
                    + "。",
                    "本人提交记录、接口测试、演示或任务单，也可以直接说明亲手做过的事",
                    raw,
                    missing=missing,
                )
            )
        if (
            LOCAL.search(raw)
            and positive_prod(raw)
            and not re.search(
                r"后来|后续.{0,6}(?:上线|投产)|随后|后在|早期|第一版|一期|二期|同事.{0,8}(?:上线|发布)|团队.{0,8}(?:上线|发布)",
                raw,
            )
        ):
            issues.append(
                issue(
                    "deployment_conflict",
                    f,
                    title + "的使用阶段",
                    "这里同时出现本机验证和正式上线。请分别说明你验证的版本、环境，以及哪一版实际交给谁使用。",
                    "发布记录、演示或接收方确认",
                    raw,
                )
            )
        if class_standard(profile) and not missing and not SPAN.search(raw):
            issues.append(
                issue(
                    "project_period",
                    f,
                    title + "的起止时间",
                    "这个项目从哪年哪月做到哪年哪月？若还在做可写“至今”。",
                    "项目日历、课程任务、实习排期或本人记录",
                    title,
                )
            )
    issues += dated_issues(selected, basic)
    issues += capability_review(profile, selected)[0]
    return issues


def nearby(source, sentence):
    a = compact(sentence)
    candidates = source_lines(source)
    if not candidates:
        return "", 0

    def score(s):
        b = compact(s)
        if a and (a in b or b in a and len(b) >= 10):
            return 1
        overlap = sum(
            n
            for _, _, n in SequenceMatcher(
                None, a, b, autojunk=False
            ).get_matching_blocks()
        )
        return overlap / max(1, len(a))

    ranked = max(candidates, key=score)
    return ranked, score(ranked)


def claim_problem(sentence, source, personal):
    raw = EDGES.sub("", sentence)
    stack = re.match(r"在采用(.+?)的项目中，", raw)
    if stack and compact(stack[1]) in compact(source):
        raw = raw[stack.end() :]
    norm = compact(raw)
    if not norm:
        return None
    evidence, score = nearby(source, raw)
    nums = NUMBER_UNIT.findall(raw)
    if METRIC.search(raw) or nums:
        nearest = [
            s
            for s in source_lines(source)
            if any(compact(n + u) in compact(s) for n, u in nums)
        ] or [evidence]
        if not all(any(compact(n + u) in compact(s) for s in nearest) for n, u in nums):
            return "number_drift", "数字或单位与这个项目的原句不一致", evidence
        if METRIC.search(raw):
            usable = [
                s
                for s in nearest
                if any(compact(v) in compact(s) for v in METRIC.findall(raw))
            ]
            if not usable or not metric_supported(raw, source):
                return "metric_basis", "百分数缺少评测对象、样本或前后口径", evidence
            if not any(
                (bool(CHANGE.search(raw)) == bool(CHANGE.search(s)))
                and (("百分点" in raw) == ("百分点" in s))
                and not any(
                    re.search(expr, raw) and not re.search(expr, s)
                    for expr in (
                        r"线上|生产",
                        r"召回|命中",
                        r"回答.{0,4}(正确|准确)|生成.{0,4}(正确|准确)",
                        r"延迟|时延|耗时",
                        r"成本|费用",
                        r"准确率",
                        r"通过率",
                    )
                )
                for s in usable
            ):
                return (
                    "metric_meaning",
                    "分数属于哪一种统计、环境或变化方式需要核对",
                    usable[0],
                )
    if any(norm == compact(EDGES.sub("", s)) for s in source_lines(source)):
        return None
    for tech in re.findall(
        r"(?<![A-Za-z])[A-Za-z][A-Za-z0-9.+#_-]{1,}(?![A-Za-z])", raw
    ):
        if tech.lower() not in source.lower() and tech.lower() not in (
            "ai",
            "api",
            "id",
        ):
            return "technology_drift", "新增技术没有这个项目的材料支撑", evidence
    if positive_prod(raw) and not positive_prod(source):
        return "deployment_drift", "生产上线的说法超出了原始记录", evidence
    if any(word not in source for word in UPGRADE.findall(raw)):
        return "role_drift", "独立程度或责任范围超出了原始记录", evidence
    if re.search(
        r"我(?:负责|实现|完成)|本人负责|(?:^|[，。；:：])负责", raw
    ) and not OTHER_OWNER.search(raw):
        if not personal or (
            all(re.search(r"配合|协助|参与", s) for s in personal)
            and not re.search(r"配合|协助|参与", raw)
        ):
            return "role_drift", "协助或团队动作被写成了个人负责", evidence
        for other in source_lines(source):
            if OTHER_OWNER.search(other):
                obj = re.split(r"负责|承担|完成|实现|做的|做", other)[-1].strip(" 。")
                if (
                    len(compact(obj)) >= 2
                    and compact(obj) in norm
                    and not any(compact(obj) in compact(s) for s in personal)
                ):
                    return "role_drift", "这项具体工作归属于其他人", other
    if any(
        re.search(r"(?:没[有做]|未|不)(?:实际)?" + part, source)
        and re.search(part, raw)
        and not re.search(r"没|未|不|仅|只", raw)
        for part in ("参与", "上线", "独立完成", "负责部署")
    ):
        if not any(norm in compact(s) for s in source_lines(source)):
            return "negation_drift", "这句话改变了原文的否定或参与范围", evidence
    if len(norm) >= 7 and score < 0.48:
        return "untraced_claim", "这句工作或结果还找不到对应事实", evidence
    return None


def project_sections(text):
    area = re.search(r"(?m)^##\s+项目(?:经历|经验)\s*$", text)
    if not area:
        return []
    area = re.split(r"(?m)^##\s+", text[area.end() :], maxsplit=1)[0]
    return [
        (name.strip(), body.strip())
        for name, body in re.findall(r"(?ms)^###\s+([^\n]+)\n(.*?)(?=^###\s+|\Z)", area)
    ]


def text_audit(profile, text, items):
    issues = []
    audit = []
    basic = profile.get("basic", "")
    name = m.profile_data("resume", {**profile, "projects": [p["raw"] for p in items]})[
        0
    ]
    chosen = project_sections(text)

    def add(code, field, short, question, src="", line=""):
        issues.append(
            issue(
                code,
                field,
                short,
                question,
                "核对本段与本人原始材料",
                src,
                quote=line[:380],
            )
        )

    title = re.search(r"(?m)^#\s+(.+)$", text)
    if not title or compact(title[1]) != compact(name):
        add(
            "body_identity",
            "basic",
            "简历姓名",
            "请把正文署名与本次资料对应。",
            name,
            title[1] if title else "",
        )
    if not 3 <= len(chosen) <= 5 and len(items) >= 3:
        add(
            "body_count",
            "projects",
            "项目段落数量",
            "请确保投递正文包含 3–5 个本人项目。",
            line=str(len(chosen)),
        )
    if len(chosen) != len(set(n for n, b in chosen)):
        add(
            "body_duplicate",
            "projects",
            "项目重复",
            "同一个项目在正文内出现了两次，请核对标题。",
        )
    sections = re.findall(r"(?m)^##\s+(.+)$", text)
    if (
        any(
            s.strip() in ("个人优势", "个人技能", "自我评价", "技术栈")
            for s in sections
        )
        or sections.count("专业技能") > 1
    ):
        add(
            "duplicate_skills",
            "basic",
            "专业技能分栏",
            "把具备项目依据的能力合并到一个专业技能栏目。",
        )
    if len(items) >= 3 and "专业技能" not in sections:
        add(
            "missing_skills",
            "basic",
            "专业技能",
            "把本人做过的具体方法和项目用途写进专业技能。",
        )
    for n, body in chosen:
        item = next((x for x in items if compact(x["title"]) == compact(n)), None)
        if not item:
            add(
                "foreign_project",
                "projects",
                "项目不属于本次材料",
                "请确认该项目正来自本人的当前资料。",
                line=n,
            )
            continue
        field = item["field"]
        if not body:
            add(
                "empty_section",
                field,
                n + "缺少正文",
                "请补上本人动作与交付。",
                item["raw"],
                n,
            )
        lines = source_lines(body)
        ev = project_evidence(item)
        if ev["role"] and not any(
            nearby(
                "\n".join(ev["role"]),
                re.sub(r"^在采用.+?的项目中，", "", EDGES.sub("", s)),
            )[1]
            >= 0.52
            for s in lines
        ):
            add(
                "body_role",
                field,
                n + "缺少本人工作",
                "请恢复能与项目材料对应的职责。",
                ev["role"][0],
            )
        if ev["delivery"] and not any(
            nearby("\n".join(ev["delivery"]), EDGES.sub("", s))[1] >= 0.52
            for s in lines
        ):
            add(
                "body_delivery",
                field,
                n + "缺少交付",
                "请写出自己给谁交了什么或如何验证。",
                ev["delivery"][0],
            )
        if ev["background"] and not any(
            nearby("\n".join(ev["background"]), EDGES.sub("", s))[1] >= 0.5
            for s in lines
        ):
            add(
                "body_context",
                field,
                n + "缺少业务背景",
                "请交代原用户及任务，便于理解这项工作为什么需要。",
                ev["background"][0],
            )
        for line in lines:
            diff = claim_problem(line, item["raw"], item["personal"])
            ref, similar = nearby(item["raw"], EDGES.sub("", line))
            audit.append(
                dict(
                    field=field,
                    claim=line[:400],
                    source=ref[:400],
                    match=round(similar, 3),
                )
            )
            if diff:
                code, why, src = diff
                add(
                    code,
                    field,
                    n + "的事实范围",
                    why + "，请使用原始口径或补一句依据。",
                    src,
                    line,
                )
    section = ""
    for line in m.MODE_MARK.sub("", text).splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.strip() or line.startswith("#"):
            continue
        if PLACEHOLDER.search(line) or re.search(
            r"^\s*(?:技术栈|老师点评|核对清单)\s*[:：]", line
        ):
            add(
                "editor_note",
                "basic",
                "投递正文有模板残留",
                "请把提示、批注或单独的技术栈清单移出投递正文。",
                line=line,
            )
        if NOISE.search(line) and len(compact(NOISE.sub("", line))) < 12:
            add(
                "generic_copy",
                "basic",
                "缺少具体内容的表达",
                "请用有材料依据的业务任务、本人动作或交付替换。",
                line=line,
            )
        if section == "项目经历":
            continue
        if section == "专业技能":
            anchors = [x for x in items if compact(x["title"]) in compact(line)]
            if not anchors and items:
                anchors = [max(items, key=lambda x: nearby(x["raw"], line)[1])]
            ref = anchors[0] if anchors else None
            scope = ref["raw"] if ref else basic
            roles = ref["personal"] if ref else []
            body = re.sub(r"^[-*•]\s*", "", line)
            if ref:
                body = re.sub(r"^" + re.escape(ref["title"]) + r"\s*[:：]", "", body)
                if compact(line) == compact(m.resume_skill(ref["parsed"])):
                    audit.append(
                        dict(
                            field=ref["field"],
                            claim=line[:400],
                            source=" ".join(ref["personal"])[:400],
                            method="由有来源的个人动作提炼技能词",
                        )
                    )
                    continue
            diff = claim_problem(body, scope, roles)
            if diff:
                add(
                    diff[0],
                    ref["field"] if ref else "basic",
                    "专业技能的来源",
                    diff[1] + "，请核对技能句。",
                    diff[2],
                    line,
                )
        elif section:
            if line.strip() in m.basic_lines(basic):
                continue
            if any(
                x not in basic for x in m.EMAIL.findall(line) + m.PHONE.findall(line)
            ) or any(
                degree not in basic
                for degree in re.findall(r"硕士|博士|本科|大专|学士|研究生", line)
            ):
                add(
                    "basic_identity",
                    "basic",
                    "学历或联系信息与原资料不一致",
                    "这条信息需要本人材料支持。",
                    basic,
                    line,
                )
                continue
            diff = claim_problem(line, basic, [basic])
            if diff:
                add(
                    diff[0],
                    "basic",
                    "履历信息来源",
                    diff[1] + "，请核对基本信息。",
                    diff[2],
                    line,
                )
    return issues, audit


def selected_items(profile, items):
    goal = goal_of(profile)
    ai = not goal or bool(re.search(r"AI|大模型|智能体|Agent|LLM|RAG", goal, re.I))
    exp = re.search(
        r"(?:开发(?:经验|年限)[：:\s]*(\d+(?:\.\d+)?)\s*年|(\d+(?:\.\d+)?)\s*年(?:以上)?(?:软件|后端|相关)?开发)",
        str(profile.get("basic", "")),
    )
    senior = bool(exp and float(exp[1] or exp[2]) >= 3)
    ranked = sorted(
        items,
        key=lambda i: (
            not all(project_evidence(i).values()),
            m.project_priority(i["parsed"]) if ai else 0,
            i["index"],
        ),
    )
    complete = [i for i in ranked if all(project_evidence(i).values())]
    chosen = complete if senior and len(complete) >= 3 else ranked[:3]
    if class_standard(profile) and not senior and len(complete) > 3:
        chosen = max(
            combinations(complete, 3),
            key=lambda seq: sum(
                bool(v) for v in capability_review(profile, seq)[2].values()
            ),
        )
    chronological = []
    for item in chosen:
        period = SPAN.search(item["raw"])
        if not period:
            return list(chosen)
        try:
            chronological.append((date_bound(period[1]), item))
        except ValueError:
            return list(chosen)
    return [
        row[1] for row in sorted(chronological, key=lambda row: row[0], reverse=True)
    ]


def visual_key(s):
    import unicodedata

    return compact(unicodedata.normalize("NFKC", s))


def inspect_exports(text, output):
    blocks = m.material_blocks(text)
    expected = "".join(visual_key(s) for _, s in blocks)
    pdf_data = m.export_material("resume", "pdf", text)
    docx_data = m.export_material("resume", "docx", text)
    output.update(pdf=pdf_data, docx=docx_data)
    errors = []
    inspected = []
    visible = []
    title_keys = {visual_key(s) for lev, s in blocks if lev}
    with fitz.open(stream=pdf_data, filetype="pdf") as doc:
        for number, page in enumerate(doc, 1):
            lines = []
            for b in page.get_text("dict")["blocks"]:
                for row in b.get("lines", []):
                    value = "".join(s["text"] for s in row["spans"])
                    if row["bbox"][1] > 782 and value.strip() == str(number):
                        continue
                    lines.append((row["bbox"], value))
            rendered = page.get_pixmap(
                matrix=fitz.Matrix(0.9, 0.9), colorspace=fitz.csGRAY, alpha=False
            )
            ink = len(rendered.samples) - rendered.samples.count(255)
            body = "".join(visual_key(v) for _, v in lines)
            visible.append(body)
            clipped = any(
                r[0] < 18
                or r[1] < 18
                or r[2] > page.rect.width - 18
                or r[3] > page.rect.height - 18
                for r, _ in lines
            )
            orphan = bool(lines and visual_key(lines[-1][1]) in title_keys)
            inspected.append(
                dict(
                    page=number,
                    characters=len(body),
                    ink_pixels=ink,
                    image_sha256=digest(rendered.samples),
                    clipped=clipped,
                    orphan_heading=orphan,
                )
            )
            if ink < 25 or not body or clipped or orphan:
                errors.append(f"第 {number} 页存在空白、越界或页末孤立标题")
        pages = len(doc)
    if pages not in (2, 3):
        errors.append(f"实际 PDF 为 {pages} 页，投递版要求 2–3 页")
    if inspected and len(inspected) > 1 and inspected[-1]["characters"] < 35:
        errors.append("末页正文过少，需要整理分页")
    pdf_matches = expected == "".join(visible)
    if not pdf_matches:
        errors.append("PDF 可见正文与最终正文不一致")
    doc = Document(io.BytesIO(docx_data))
    word_body = "".join(visual_key(p.text) for p in doc.paragraphs)
    word_matches = expected == word_body
    if not word_matches:
        errors.append("Word 正文与最终正文不一致")
    return dict(
        body_sha256=digest(text),
        pdf=dict(
            sha256=digest(pdf_data),
            bytes=len(pdf_data),
            pages=pages,
            body_matches=pdf_matches,
            page_checks=inspected,
        ),
        docx=dict(
            sha256=digest(docx_data),
            bytes=len(docx_data),
            paragraphs=len(doc.paragraphs),
            body_matches=word_matches,
            inspection="打开实际 DOCX 核对可编辑正文；逐页渲染检查对应 PDF",
        ),
    ), errors


def check_resume(profile, text, *, artifacts=None):
    items = project_inputs(profile)
    issues = review_profile(profile)
    chosen = {compact(n) for n, _ in project_sections(text)}
    if len(chosen) >= 3:
        selected = {x["field"] for x in items if compact(x["title"]) in chosen}
        issues = [i for i in issues if i["field"] in {"basic", "projects"} | selected]
    else:
        selected = {x["field"] for x in selected_items(profile, items)}
    body_issues, audit = text_audit(profile, text, items)
    issues += body_issues
    if not text.strip():
        issues.append(
            issue(
                "body_empty", "basic", "简历正文", "请先生成简历后再核对。", "成品正文"
            )
        )
    out = artifacts if artifacts is not None else {}
    exports = {}
    if text.strip():
        exports, layout = inspect_exports(text, out)
        for err in layout:
            if len(items) < 3 and "要求 2–3 页" in err:
                continue
            issues.append(
                issue(
                    "layout",
                    "projects",
                    "投递版排版",
                    err + "。",
                    "最终导出的 PDF 与 Word",
                    err,
                )
            )
    _, advice, coverage = capability_review(
        profile, [i for i in items if i["field"] in selected]
    )
    for item in items:
        for _, v in item["parsed"].facts:
            if METRIC.search(v) and not metric_supported(v, item["raw"]):
                advice.append(
                    issue(
                        "optional_metric",
                        item["field"],
                        item["title"] + "的效果数字",
                        "这项数值对应什么指标、哪批样本和基线？查不到可以只写已确认的功能交付。",
                        "评测表或运行记录",
                        v,
                    )
                )
    unique = {}
    for entry in issues:
        unique.setdefault(
            (
                entry["code"],
                entry["field"],
                entry.get("quote", ""),
                entry["label"],
                entry["question"],
            ),
            entry,
        )
    return dict(
        status="draft" if unique else "ready",
        rule_version=RULE_VERSION,
        body_sha256=digest(text),
        issues=list(unique.values()),
        suggestions=advice,
        evidence=audit,
        coverage=coverage,
        target=goal_of(profile),
        artifacts=exports,
        revisions=[],
        polish={"mode": "手动版本核对", "changes": []},
    )


def plain_edits(text):
    changes = []
    output = []
    seen = set()
    section = ""
    for line in text.splitlines():
        if line.startswith("#"):
            section = line
            seen.clear()
        revised = line
        if line and not line.startswith(("#", "<!--")):
            revised = re.sub(
                r"^(本人职责[：:]\s*)?(?:我|本人)(?=(?:负责|独立|配合|参与|协助|完成|实现|编写|设计|维护|校验|开发|部署))",
                "",
                line,
            )
            revised = re.sub(r"^项目成果[：:]\s*(?=交付|形成|提供|完成)", "", revised)
            revised = re.sub(r"(?<=：)我(?=负责|参与|配合|协助)", "", revised)
            if re.fullmatch(
                r"(?:深度赋能|全面赋能|全方位赋能)(?:业务|业务发展)?[。！!]?",
                revised.strip(),
            ):
                revised = ""
            if revised.strip() in seen and section:
                revised = ""
            seen.add(revised.strip())
        if revised != line:
            changes.append(
                dict(
                    before=line,
                    after=revised,
                    reason="收紧履历措辞或删去本段重复句",
                    section=section,
                )
            )
        output.append(revised)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip() + "\n", changes


def conservative_text(profile, concise=False):
    items = selected_items(profile, project_inputs(profile))
    name, basic, _ = m.profile_data(
        "resume", {**profile, "projects": [i["raw"] for i in items]}
    )
    projects = []
    for i in items:
        p = deepcopy(i["parsed"])
        p.facts = [(k, v) for k, v in p.facts if metric_supported(v, i["raw"])]
        if concise:
            retained = []
            for key in (
                "period",
                "background",
                "role",
                "scope",
                "tech",
                "solution",
                "result",
                "check",
                "deploy",
            ):
                records = [v for k, v in p.facts if k == key]
                if records:
                    retained.append((key, min(records, key=len)))
            p.facts = retained
        projects.append(p)
    return (
        "<!-- 生成方式：本机离线事实整理 -->\n"
        + m.resume_text(name, basic, projects).strip()
        + "\n"
    )


def fix_sections(body, safe, issues):
    # Preserve whitespace outside the section; the student's displayed Markdown
    # can have zero, one or several empty lines on either side of a project.
    headings = dict(project_sections(safe))
    pattern = r"(?ms)^(### ([^\n]+)\n)(.*?)(?=^#{1,3} |\Z)"

    def replace(match):
        title = match[2].strip()
        old = match[3]
        if title in headings and any(
            (i.get("quote") and i["quote"] in old) or i["label"].startswith(title)
            for i in issues
        ):
            return match[1] + "\n" + headings[title] + "\n\n"
        return match[0]

    result = re.sub(pattern, replace, body)
    for section in ("专业技能", "工作经历", "求职信息", "教育经历"):
        rx = rf"(?ms)^## {section}\n.*?(?=^## |\Z)"
        old = re.search(rx, result)
        replacement = re.search(rx, safe)
        if old and any(
            i.get("quote")
            and (i["quote"] in old[0] or compact(i["quote"]) in compact(old[0]))
            for i in issues
        ):
            result = (
                result[: old.start()]
                + (replacement[0] if replacement else "")
                + result[old.end() :]
            )
    return result.strip() + "\n"


def online_polish(body, items):
    import llm

    accept = []
    checked = []
    guide = (m.SKILLS / "humanizer-zh" / "SKILL.md").read_text(encoding="utf-8")
    candidates = []
    for title, section in project_sections(body):
        for line in section.splitlines():
            if (
                len(line.strip()) >= 13
                and not m.EMAIL.search(line)
                and not m.PHONE.search(line)
            ):
                candidates.append((title, line.strip()))
    if not candidates:
        return body, checked
    data = json.dumps(
        {str(i): s for i, (_, s) in enumerate(candidates)}, ensure_ascii=False
    )
    try:
        response = llm.complete(
            guide
            + "\n这是一轮独立简历文字编辑。只返回 JSON 对象，键为原数字行号，值为换写后的整行。仅改确有重复或空话的行，已通顺可全数保留，返回 {}。不得改变实际技术、数字、归属、阶段和否定。",
            data,
        )
        edits = json.loads(re.sub(r"^\s*```(?:json)?\s*|```\s*$", "", response.strip()))
    except (ValueError, TypeError):
        return body, [
            dict(
                reason="模型本轮未返回可核对的修改，沿用完成事实检查的原文",
                applied=False,
            )
        ]
    if not isinstance(edits, dict):
        return body, checked
    for i, (title, old) in enumerate(candidates):
        new = edits.get(str(i))
        if not isinstance(new, str) or not new.strip() or new.strip() == old:
            continue
        new = new.strip()
        src = next((p for p in items if p["title"] == title), None)
        locks = (
            NUMBER_UNIT,
            r"没(?:有)?|未(?:经)?|仅|尚未|不曾|计划|预计|协助|配合|参与|独立|主导|牵头|负责|团队|同事|测试环境|本地|本机|离线|生产|上线",
        )
        changed = any(
            sorted(re.findall(rx, old)) != sorted(re.findall(rx, new)) for rx in locks
        )
        good = bool(
            src
            and "\n" not in new
            and not changed
            and not claim_problem(new, src["raw"], src["personal"])
            and nearby(old, new)[1] >= 0.6
            and nearby(new, old)[1] >= 0.55
        )
        checked.append(
            dict(
                before=old,
                after=new,
                applied=good,
                reason="通过原项目及敏感事实对照"
                if good
                else "来源、否定、归属、数字或阶段改变，保留原句",
            )
        )
        if good:
            accept.append((title, old, new))
    for title, old, new in accept:
        pattern = r"(?ms)(^### " + re.escape(title) + r"\n)(.*?)(?=^#{1,3} |\Z)"
        body = re.sub(
            pattern,
            lambda match: match[1]
            + re.sub(
                r"(?m)^" + re.escape(old) + r"$", lambda _: new, match[2], count=1
            ),
            body,
            count=1,
        )
    return body, checked


def changed_passages(old, new):
    left = [s for s in old.splitlines() if s.strip()]
    right = [s for s in new.splitlines() if s.strip()]
    return [
        {
            "before": "\n".join(left[start:end]),
            "after": "\n".join(right[new_start:new_end]),
        }
        for tag, start, end, new_start, new_end in SequenceMatcher(
            None, left, right, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]


def build_resume(profile, use_model=False, *, artifacts=None):
    items = project_inputs(profile)
    safe = conservative_text(profile)
    pre = review_profile(profile)
    mode = "本机书面语整理"
    selected = selected_items(profile, items)
    inputs = {**profile, "projects": [item["raw"] for item in selected]}
    rounds = []
    text = safe
    if use_model and not pre:
        # Failure to reach the provider belongs to the resumable service request.
        try:
            text = m.generate_material("resume", inputs, True)
            mode = "模型书面语编辑"
        except ValueError as exc:
            if not any(
                s in str(exc) for s in ("缺少完整项目段落", "百分比", "长度上限")
            ):
                raise
            rounds.append(
                dict(
                    round=1,
                    issues=["model_shape"],
                    reason=str(exc),
                    before="",
                    after=digest(safe),
                )
            )
    edits = []
    out = {}
    review = check_resume(profile, text, artifacts=out)
    fixable = [i for i in review["issues"] if i["code"] not in {x["code"] for x in pre}]
    if fixable and text != safe:
        repaired = fix_sections(text, safe, fixable)
        if repaired == text or any(
            i["code"]
            in (
                "foreign_project",
                "body_count",
                "body_identity",
                "missing_skills",
                "layout",
            )
            for i in fixable
        ):
            repaired = safe
        check = check_resume(profile, repaired, artifacts=out)
        rounds.append(
            dict(
                round=1,
                issues=[x["code"] for x in fixable],
                before=digest(text),
                after=digest(repaired),
                changes=changed_passages(text, repaired),
                references=[x.get("source", "") for x in fixable],
                remaining=[x["code"] for x in check["issues"]],
            )
        )
        text = repaired
        review = check
    if review["issues"] and not pre and text != safe and len(rounds) < 2:
        source_review = check_resume(profile, safe, artifacts=out)
        if len(source_review["issues"]) < len(review["issues"]):
            rounds.append(
                dict(
                    round=len(rounds) + 1,
                    issues=[i["code"] for i in review["issues"]],
                    before=digest(text),
                    after=digest(safe),
                    reason="剩余句不能稳定对照，恢复为已重检的来源文本",
                    changes=changed_passages(text, safe),
                    remaining=[i["code"] for i in source_review["issues"]],
                )
            )
            text = safe
            review = source_review
        else:
            review = check_resume(profile, text, artifacts=out)
    if (
        len(rounds) < 2
        and not pre
        and review["artifacts"].get("pdf", {}).get("pages", 0) > 3
    ):
        shorter = conservative_text(profile, concise=True)
        candidate_files = {}
        candidate = check_resume(profile, shorter, artifacts=candidate_files)
        if len(candidate["issues"]) < len(review["issues"]):
            rounds.append(
                dict(
                    round=len(rounds) + 1,
                    issues=["layout"],
                    before=digest(text),
                    after=digest(shorter),
                    changes=changed_passages(text, shorter),
                    reason="保留每项关键事实，重新导出并检查实际分页",
                )
            )
            text, review, out = shorter, candidate, candidate_files
    previous = text
    if len(rounds) < 2:
        text, edits = plain_edits(text)
    if (
        use_model
        and mode == "模型书面语编辑"
        and not review["issues"]
        and len(rounds) < 2
    ):
        text, more = online_polish(text, items)
        edits += more
    if previous != text:
        polished_review = check_resume(profile, text, artifacts=out)
        old_keys = {(x["code"], x["field"]) for x in review["issues"]}
        new_keys = {(x["code"], x["field"]) for x in polished_review["issues"]}
        applied = not bool(new_keys - old_keys)
        if len(rounds) < 2:
            rounds.append(
                dict(
                    round=len(rounds) + 1,
                    issues=["wording"],
                    before=digest(previous),
                    after=digest(text),
                    applied=applied,
                    remaining=sorted(x[0] for x in new_keys),
                )
            )
        if applied:
            review = polished_review
        else:
            text = previous
            review = check_resume(profile, text, artifacts=out)
    if artifacts is not None:
        artifacts.update(out)
    review["revisions"] = rounds
    review["polish"] = {"mode": mode, "changes": edits, "final_sha256": digest(text)}
    return text, review
