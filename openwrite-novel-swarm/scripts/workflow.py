"""Executable SwarmFlow workflow for openwrite-novel-swarm.

Standalone Python workflow module: META + JSON Schema literals +
explicit swarmflow primitive imports + async def run(args).

Topology mirrors workflow.md: 规划 -> 写作 -> 六域并行评审 -> 确定性聚合
-> 修订 + 定向复评（最多 2 轮）-> 交付结算。author-gate 以 approval args
表达：缺批准时 run 返回 gate payload 交由人类决定（HITL handoff）。
"""
import json
import re
from string import Template

from swarmflow import agent, log, parallel, phase

META = {
    "name": "openwrite-novel-swarm",
    "description": "OpenWrite 长篇创作蜂群的可执行编排：规划、写章、六域并行评审、确定性聚合、修订复评闭环、交付报告。",
    "whenToUse": "当需要在 SwarmFlow 中端到端产出单章（或仅评审已有章节）并要求六域评分与修订闭环时使用。",
    "phases": [
        {"title": "规划资产包", "detail": "goethe-planner 收敛意图并产出人物/世界观/分层大纲资产包"},
        {"title": "章节写作", "detail": "dante-writer 按 canonical context packet 撰写章节正文"},
        {"title": "六域并行评审", "detail": "三个隔离评审员并行覆盖六域，输出评分与 blocker"},
        {"title": "聚合判定", "detail": "Leader 确定性规则聚合：blocker 数、最低域分、覆盖完整性"},
        {"title": "修订与复评", "detail": "revision-forge 最小化修订后对未过域定向复评，最多 2 轮"},
        {"title": "交付结算", "detail": "输出章节交付报告：版本链/六域评分/判定/修订历史/回写清单"},
    ],
}

MAX_REWORK_ROUNDS = 2
MIN_DOMAIN_SCORE = 6

# ---------------------------------------------------------------------------
# JSON Schemas for structured agent outputs (permissive: no required keyword,
# no additionalProperties — strictness causes agent() to silently return None).
# ---------------------------------------------------------------------------
PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string"},
        "characters": {"type": "integer"},
        "chapter_count": {"type": "integer"},
        "promises_registered": {"type": "boolean"},
        "asset_pack": {"type": "string"},
        "notes": {"type": "string"},
    },
}

WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string"},
        "conflicts": {"type": "integer"},
        "chapter_text": {"type": "string"},
        "state_updates": {"type": "string"},
    },
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string"},
        "blockers": {"type": "integer"},
        "domain_scores": {"type": "object"},
        "findings": {"type": "string"},
        "summary": {"type": "string"},
    },
}

REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string"},
        "applied": {"type": "integer"},
        "hard_blocks": {"type": "integer"},
        "diff_summary": {"type": "string"},
    },
}

# Domain -> reviewer label mapping (OpenWrite review-dag-framework.v1 六域)
DOMAIN_REVIEWERS = {
    "coherence": "reviewer-canon",
    "canon": "reviewer-canon",
    "plot": "reviewer-drama",
    "pacing": "reviewer-drama",
    "character": "reviewer-prose",
    "style": "reviewer-prose",
}
REVIEWER_LABELS = ["reviewer-canon", "reviewer-drama", "reviewer-prose"]


# ---------------------------------------------------------------------------
# Resilient helpers
# ---------------------------------------------------------------------------

def extract_json(text, fallback=None):
    """Extract the first JSON object from text (LLM output may have prose)."""
    fallback_value = {} if fallback is None else fallback
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return fallback_value
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else fallback_value
    except (json.JSONDecodeError, ValueError):
        pass
    depth = 0
    start = None
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}' and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    parsed = json.loads(text[start:i + 1])
                    return parsed if isinstance(parsed, dict) else fallback_value
                except (json.JSONDecodeError, ValueError):
                    start = None
    return fallback_value


def safe_get(obj, key, default=""):
    if obj is None:
        return str(default)
    if isinstance(obj, dict):
        return str(obj.get(key, default))
    return str(default)


def safe_int(obj, key, default=0):
    try:
        return int(safe_get(obj, key, default))
    except (TypeError, ValueError):
        return default


def parse_args(args):
    """Normalize args to dict. Swarmflow may pass JSON string or dict."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            return json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return {}
    return {}


def arg_text(args, key, default=""):
    value = args.get(key, default)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def parse_bool(value):
    return str(value).strip().lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Deterministic input derivation (Leader 职责：把规划产物装配成写作/评审输入)
# ---------------------------------------------------------------------------
#
# 在完整 openJiuwen 运行时中，这些槽位由 openwrite-mcp 工具实时填充：
#   chapter_brief / outline_nodes  <- get_outline
#   context_packet / style_fingerprint / truth_ledger <- get_context_packet
#   foreshadow_dag / foreshadow_and_truth <- get_chapter_foreshadowing
#   评审基线 <- get_review_framework（47 节点蓝图，topology_locked）
# 独立执行（无 MCP 侧车）时，由本函数从规划资产包确定性提取首章输入，
# 保证蜂群在两种运行形态下都能拿到同构的写作/评审上下文。

CH_ANCHOR = {
    n: re.compile(
        r"(第\s*0*" + str(n) + r"\s*[章回节]"
        r"|Chapter\s*0*" + str(n) + r"\b"
        r"|CHAPTER\s*0*" + str(n) + r"\b"
        r"|ch(?:apter)?[\s_:\-]*0*" + str(n) + r"\b"
        r"|章\s*0*" + str(n) + r"\b)"
    )
    for n in range(1, 201)
}


def derive_chapter_inputs(asset_pack, chapter_number=1):
    """从规划资产包提取指定章节的写作输入；无锚点时退回整体视图。

    chapter_number 支持批量产章模式逐章提取（默认首章）。
    """
    if not asset_pack:
        return {}
    text = str(asset_pack)
    anchor = CH_ANCHOR.get(int(chapter_number), CH_ANCHOR[1])
    nxt = CH_ANCHOR.get(int(chapter_number) + 1)
    brief = "（资产包中未定位到第 " + str(chapter_number) + " 章节点，按整体资产包写作）"
    m1 = anchor.search(text)
    if m1:
        rest = text[m1.start():]
        m2 = nxt.search(rest, 10) if nxt else None
        brief = (rest[: m2.start()] if m2 else rest[:1200]).strip()[:1200]
    pack_view = text.strip()[:3000]
    return {
        "chapter_brief": brief,
        "context_packet": pack_view,
        "outline_nodes": pack_view,
        "world_entities": pack_view,
        "character_cards": pack_view,
        "foreshadow_and_truth": brief,
    }


# ---------------------------------------------------------------------------
# Prompt builders (string.Template — literal braces stay literal)
# ---------------------------------------------------------------------------

PLANNER_PROMPT = Template(
    """你是 openwrite-novel-swarm 的规划师（goethe-planner）。你不写正文，只定骨架：
收敛意图，产出人物卡、世界观实体、卷/幕/节/章四级大纲。每个章级节点必须登记
本章要兑现的承诺（至少 1 条）与伏笔的埋设/回收窗口。

创作意图: $author_intent
题材与约束: $genre_constraints
既有资产: $existing_assets

返回 ONLY 一个 JSON 对象（不要 markdown 围栏）：
字段：verdict（"READY-FOR-GATE" 或 "NEEDS-MORE-WORK"）、characters（人物卡数量，整数）、
chapter_count（章级叶子节点数，整数）、promises_registered（每章是否都登记了承诺，布尔）、
asset_pack（完整资产包文本）、notes（自检说明）。
"""
)

WRITER_PROMPT = Template(
    """你是 openwrite-novel-swarm 的主笔（dante-writer）。你只在已确认的骨架内施工：
先复述本章承诺，再按 canonical context packet 撰写完整章节正文，最后交付状态回写
清单。不修改上游设定；发现设定冲突时在 conflicts 计数登记，不自审质量。

资产包是唯一真源。铁律：
- 主角身份、姓名、场景、关键道具必须与资产包一致，禁止临场更换主角或场景
- 每段叙事必须能指回本章承诺或资产包条目
- 只写本章内容，不预支后续章节

本章纲要与承诺清单: $chapter_brief
资产包（正文基线与章节记忆）: $context_packet
风格指纹: $style_fingerprint
伏笔待办与 truth 状态: $foreshadow_and_truth

返回 ONLY 一个 JSON 对象（不要 markdown 围栏）：
字段：verdict（"DELIVERED" 或 "BLOCKED"）、conflicts（设定冲突数，整数）、
chapter_text（完整章节正文）、state_updates（truth/伏笔/人物状态回写）。
"""
)

CANON_REVIEWER_PROMPT = Template(
    """你是 openwrite-novel-swarm 的正典审查员（reviewer-canon），负责"连贯与逻辑"和
"正典与资料"两域。以 truth/ledger、世界观实体、伏笔 DAG 为裁判依据逐条核对正文，
每个 finding 附正文引文与设定条目 id。不评价情节与文笔。与其他评审隔离工作。

章节正文: $chapter_text
truth 与 ledger: $truth_ledger
世界观实体: $world_entities
伏笔 DAG 与本章待办: $foreshadow_dag

返回 ONLY 一个 JSON 对象（不要 markdown 围栏）：
字段：verdict（PASS / PASS-WITH-NOTES / NEEDS-REVISION / BLOCKED）、
blockers（blocker 级 finding 数量，整数）、
domain_scores（对象，含 coherence 与 canon 两个 0-10 的数字）、
findings（逐条 finding 及证据）、summary（一句话）。
"""
)

DRAMA_REVIEWER_PROMPT = Template(
    """你是 openwrite-novel-swarm 的叙事审查员（reviewer-drama），负责"情节与承诺"和
"节奏与场景"两域。以章级承诺清单为账本逐条核对兑现情况，按场景清点叙事功能与节奏。
不核对设定事实，不评价文笔。与其他评审隔离工作。

章节正文: $chapter_text
章级承诺清单: $chapter_brief
卷/幕/节大纲节点: $outline_nodes
前章遗留承诺: $pending_promises

返回 ONLY 一个 JSON 对象（不要 markdown 围栏）：
字段：verdict（PASS / PASS-WITH-NOTES / NEEDS-REVISION / BLOCKED）、
blockers（blocker 级 finding 数量，整数）、
domain_scores（对象，含 plot 与 pacing 两个 0-10 的数字）、
findings（逐条 finding 及证据）、summary（一句话）。
"""
)

PROSE_REVIEWER_PROMPT = Template(
    """你是 openwrite-novel-swarm 的文辞审查员（reviewer-prose），负责"角色与关系"和
"文风与表达"两域。以人物卡为声口基准、风格指纹为文风基准，抽样核对至少一半台词，
并检查 AI 痕迹模式。不核对事实与情节。与其他评审隔离工作。

章节正文: $chapter_text
人物卡与关系图谱: $character_cards
风格指纹: $style_fingerprint
后置规则清单: $post_rules

返回 ONLY 一个 JSON 对象（不要 markdown 围栏）：
字段：verdict（PASS / PASS-WITH-NOTES / NEEDS-REVISION / BLOCKED）、
blockers（blocker 级 finding 数量，整数）、
domain_scores（对象，含 character 与 style 两个 0-10 的数字）、
findings（逐条 finding 及证据）、summary（一句话）。
"""
)

REVISION_PROMPT = Template(
    """你是 openwrite-novel-swarm 的修订匠（revision-forge）。把聚合判定与评审 findings
翻译成结构化修订计划并做最小化应用：每条改动挂接 finding，能改一词不改一句。
你没有复评权，不改大纲/人物/世界观等资产。

聚合判定: $aggregate
各域 findings: $findings
正文基线: $chapter_text

返回 ONLY 一个 JSON 对象（不要 markdown 围栏）：
字段：verdict（APPLIED / PARTIAL / BLOCKED）、applied（已应用修订条数，整数）、
hard_blocks（无法最小化修复的 blocker 数，整数）、
diff_summary（diff 级摘要：定位、改动、对应 finding）。
"""
)

REVIEWER_PROMPTS = {
    "reviewer-canon": CANON_REVIEWER_PROMPT,
    "reviewer-drama": DRAMA_REVIEWER_PROMPT,
    "reviewer-prose": PROSE_REVIEWER_PROMPT,
}


def build_planner_prompt(args):
    return PLANNER_PROMPT.substitute(
        author_intent=arg_text(args, "author_intent", "（未提供，需向用户确认）"),
        genre_constraints=arg_text(args, "genre_constraints", "（无）"),
        existing_assets=arg_text(args, "existing_assets", "（无，全新作品）"),
    )


def build_writer_prompt(args):
    return WRITER_PROMPT.substitute(
        chapter_brief=arg_text(args, "chapter_brief", "（未提供）"),
        context_packet=arg_text(args, "context_packet", "（首章，无基线）"),
        style_fingerprint=arg_text(args, "style_fingerprint", "（默认自然文风）"),
        foreshadow_and_truth=arg_text(args, "foreshadow_and_truth", "（无待办）"),
    )


def build_reviewer_prompt(label, args, chapter_text):
    template = REVIEWER_PROMPTS[label]
    return template.substitute(
        chapter_text=chapter_text,
        truth_ledger=arg_text(args, "truth_ledger", "（无）"),
        world_entities=arg_text(args, "world_entities", "（无）"),
        foreshadow_dag=arg_text(args, "foreshadow_dag", "（无）"),
        chapter_brief=arg_text(args, "chapter_brief", "（未提供）"),
        outline_nodes=arg_text(args, "outline_nodes", "（未提供）"),
        pending_promises=arg_text(args, "pending_promises", "（无）"),
        character_cards=arg_text(args, "character_cards", "（未提供）"),
        style_fingerprint=arg_text(args, "style_fingerprint", "（默认）"),
        post_rules=arg_text(args, "post_rules", "（默认规则）"),
    )


def build_revision_prompt(args, aggregate, findings, chapter_text):
    return REVISION_PROMPT.substitute(
        aggregate=json.dumps(aggregate, ensure_ascii=False),
        findings=json.dumps(findings, ensure_ascii=False),
        chapter_text=chapter_text,
    )


# ---------------------------------------------------------------------------
# Deterministic aggregation (Leader rules from workflow.md Step 5)
# ---------------------------------------------------------------------------

def aggregate_reviews(reviews_by_label):
    """reviews_by_label: dict label -> extracted review dict -> aggregate dict."""
    domain_scores = {}
    blockers_total = 0
    missing = []
    for label in REVIEWER_LABELS:
        review = reviews_by_label.get(label) or {}
        owned = [d for d, owner in DOMAIN_REVIEWERS.items() if owner == label]
        if not review or not safe_get(review, "verdict"):
            for domain in owned:
                domain_scores[domain] = "inconclusive"
            missing.append(label)
            continue
        blockers_total += safe_int(review, "blockers", 0)
        scores = review.get("domain_scores") if isinstance(review, dict) else None
        if isinstance(scores, dict):
            for domain in owned:
                try:
                    domain_scores[domain] = float(scores.get(domain, 0))
                except (TypeError, ValueError):
                    domain_scores[domain] = 0
    numeric = [v for v in domain_scores.values() if isinstance(v, (int, float))]
    inconclusive = [d for d, v in domain_scores.items() if not isinstance(v, (int, float))]
    min_score = min(numeric) if numeric else 0
    passed = (
        blockers_total == 0
        and min_score >= MIN_DOMAIN_SCORE
        and len(inconclusive) == 0
        and len(missing) == 0
    )
    failed_domains = sorted(
        d for d, v in domain_scores.items()
        if isinstance(v, (int, float)) and v < MIN_DOMAIN_SCORE
    )
    return {
        "passed": passed,
        "blockers_total": blockers_total,
        "min_domain_score": min_score,
        "domain_scores": domain_scores,
        "failed_domains": failed_domains,
        "inconclusive_domains": sorted(inconclusive),
        "missing_reviewers": missing,
    }


def reviewers_for_domains(domains):
    labels = []
    for d in domains:
        owner = DOMAIN_REVIEWERS.get(d)
        if owner and owner not in labels:
            labels.append(owner)
    return labels


# ---------------------------------------------------------------------------
# Workflow entrypoint
# ---------------------------------------------------------------------------

async def run(args):
    """Execute the workflow and return a JSON-serializable result."""
    args = parse_args(args)
    review_only = bool(args.get("chapter_text"))
    outline_approved = parse_bool(args.get("outline_approved", True))
    revision_approved = parse_bool(args.get("revision_approved", True))
    max_rounds = safe_int(args, "max_rework_rounds", MAX_REWORK_ROUNDS)

    asset_pack = arg_text(args, "existing_assets", "")
    chapter_text = arg_text(args, "chapter_text", "")
    revision_history = []
    status_flags = []

    # ---- Phase 1: 规划资产包 -------------------------------------------------
    phase("规划资产包")
    if review_only:
        log("进入仅评审模式：跳过规划与写作")
    else:
        log("派发 goethe-planner")
        planner_result = {}
        for attempt in (1, 2):
            raw = await agent(
                build_planner_prompt(args),
                label="goethe-planner",
                phase="规划资产包",
                schema=PLANNER_SCHEMA,
            )
            planner_result = extract_json(raw, fallback={})
            gate_ok = (
                safe_get(planner_result, "verdict") == "READY-FOR-GATE"
                and safe_int(planner_result, "chapter_count", 0) >= 1
                and safe_int(planner_result, "characters", 0) >= 1
                and parse_bool(safe_get(planner_result, "promises_registered", False))
            )
            if gate_ok:
                break
            log("规划质量门未过，重派（第 " + str(attempt) + " 次）")
        else:
            return {
                "status": "failed",
                "failed_at": "规划资产包",
                "planner_result": planner_result,
            }
        asset_pack = safe_get(planner_result, "asset_pack")

        # Leader 确定性装配：从资产包提取本章写作/评审输入（运行时也可由
        # openwrite-mcp 的 get_outline / get_context_packet 等工具填充同构槽位）
        chapter_no = safe_int(args, "chapter_number", 1)
        for key, value in derive_chapter_inputs(asset_pack, chapter_no).items():
            if not arg_text(args, key):
                args[key] = value

        # Human gate: 大纲定稿确认
        if not outline_approved:
            return {
                "status": "awaiting_gate",
                "gate": "OUTLINE-FINAL",
                "payload": asset_pack,
                "note": "作者确认后以便 outline_approved=true 重新进入",
            }
        log("大纲确认门通过")

    # ---- Phase 2: 章节写作 ----------------------------------------------------
    phase("章节写作")
    if review_only:
        log("仅评审模式：使用输入 chapter_text 作为正文基线")
    else:
        log("派发 dante-writer")
        writer_result = {}
        for attempt in (1, 2):
            raw = await agent(
                build_writer_prompt(args),
                label="dante-writer",
                phase="章节写作",
                schema=WRITER_SCHEMA,
            )
            writer_result = extract_json(raw, fallback={})
            gate_ok = (
                safe_get(writer_result, "verdict") == "DELIVERED"
                and safe_int(writer_result, "conflicts", 1) == 0
                and len(safe_get(writer_result, "chapter_text")) > 500
            )
            if gate_ok:
                chapter_text = safe_get(writer_result, "chapter_text")
                break
            log("硬门禁未过，重派（第 " + str(attempt) + " 次）")
        else:
            return {
                "status": "failed",
                "failed_at": "章节写作",
                "writer_result": writer_result,
                "asset_pack": asset_pack,
            }

    # ---- Phase 3: 六域并行评审 --------------------------------------------------
    phase("六域并行评审")
    log("并行派发三名隔离评审")
    raw_results = await parallel([
        lambda: agent(
            build_reviewer_prompt("reviewer-canon", args, chapter_text),
            label="reviewer-canon",
            phase="六域并行评审",
            schema=REVIEW_SCHEMA,
        ),
        lambda: agent(
            build_reviewer_prompt("reviewer-drama", args, chapter_text),
            label="reviewer-drama",
            phase="六域并行评审",
            schema=REVIEW_SCHEMA,
        ),
        lambda: agent(
            build_reviewer_prompt("reviewer-prose", args, chapter_text),
            label="reviewer-prose",
            phase="六域并行评审",
            schema=REVIEW_SCHEMA,
        ),
    ])
    reviews = {}
    for label, raw in zip(REVIEWER_LABELS, raw_results):
        reviews[label] = extract_json(raw, fallback={})
        if not reviews[label]:
            status_flags.append("ROLE MISSING: " + label)

    # ---- Phase 4: 聚合判定 ------------------------------------------------------
    phase("聚合判定")
    aggregate = aggregate_reviews(reviews)
    log("聚合判定通过状态: " + str(aggregate["passed"]))

    # ---- Phase 5: 修订与复评（最多 max_rounds 轮，停止条件见循环条件）------------
    phase("修订与复评")
    round_no = 0
    while not aggregate["passed"] and round_no < max_rounds:
        round_no += 1
        log("进入第 " + str(round_no) + " 轮修订复评")

        # Human gate: 修订应用确认
        if not revision_approved:
            return {
                "status": "awaiting_gate",
                "gate": "REVISION-APPLY",
                "payload": aggregate,
                "chapter_text": chapter_text,
                "note": "作者确认后以便 revision_approved=true 继续复评",
            }

        revision_raw = await agent(
            build_revision_prompt(args, aggregate, reviews, chapter_text),
            label="revision-forge",
            phase="修订与复评",
            schema=REVISION_SCHEMA,
        )
        revision = extract_json(revision_raw, fallback={})
        revision_history.append({
            "round": round_no,
            "applied": safe_int(revision, "applied", 0),
            "hard_blocks": safe_int(revision, "hard_blocks", 0),
            "diff_summary": safe_get(revision, "diff_summary"),
        })
        if safe_get(revision, "verdict") == "BLOCKED":
            status_flags.append("DELIVERED-WITH-BLOCKERS: revision-forge blocked")
            break

        # 定向复评：只对未过域对应的评审员依次重派（评估依据基线已更新）。
        # 评审员集合固定为三个，按字面量分支派发以满足稳定 label 约束。
        failed = aggregate["failed_domains"] + aggregate["inconclusive_domains"]
        targets = reviewers_for_domains(failed)
        if "reviewer-canon" in targets:
            raw = await agent(
                build_reviewer_prompt("reviewer-canon", args, chapter_text),
                label="reviewer-canon",
                phase="修订与复评",
                schema=REVIEW_SCHEMA,
            )
            re_review = extract_json(raw, fallback={})
            if re_review:
                reviews["reviewer-canon"] = re_review
            else:
                status_flags.append("ROLE MISSING on re-review: reviewer-canon")
        if "reviewer-drama" in targets:
            raw = await agent(
                build_reviewer_prompt("reviewer-drama", args, chapter_text),
                label="reviewer-drama",
                phase="修订与复评",
                schema=REVIEW_SCHEMA,
            )
            re_review = extract_json(raw, fallback={})
            if re_review:
                reviews["reviewer-drama"] = re_review
            else:
                status_flags.append("ROLE MISSING on re-review: reviewer-drama")
        if "reviewer-prose" in targets:
            raw = await agent(
                build_reviewer_prompt("reviewer-prose", args, chapter_text),
                label="reviewer-prose",
                phase="修订与复评",
                schema=REVIEW_SCHEMA,
            )
            re_review = extract_json(raw, fallback={})
            if re_review:
                reviews["reviewer-prose"] = re_review
            else:
                status_flags.append("ROLE MISSING on re-review: reviewer-prose")
        aggregate = aggregate_reviews(reviews)
        log("第 " + str(round_no) + " 轮复评后通过状态: " + str(aggregate["passed"]))

    # ---- Phase 6: 交付结算 ------------------------------------------------------
    phase("交付结算")
    final_status = "delivered"
    if not aggregate["passed"]:
        final_status = "delivered-with-blockers"
        status_flags.append("DELIVERED-WITH-BLOCKERS: rework rounds exhausted")
    log("交付结算: " + final_status)

    return {
        "status": final_status,
        "aggregate": aggregate,
        "domain_scores": aggregate["domain_scores"],
        "revision_history": revision_history,
        "reviews": {
            label: {
                "verdict": safe_get(reviews.get(label), "verdict"),
                "summary": safe_get(reviews.get(label), "summary"),
            }
            for label in REVIEWER_LABELS
        },
        "asset_pack_summary": asset_pack[:2000],
        "chapter_text": chapter_text,
        "chapter_length": len(chapter_text),
        "flags": status_flags,
    }
