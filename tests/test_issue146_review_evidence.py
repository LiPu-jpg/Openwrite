"""Report #146: recover located criterion evidence without relaxing delivery gates."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from tools.agent.base import AgentContext
from tools.agent.reviewer import ReviewerAgent
from tools.chapter_pipeline import _apply_canon_gate
from tools.review_rubric import QUALITY_DOMAINS, resolve_review_dimensions

PROSE = "# 第一章 门\n\n林岑收起雨伞，推开旧宅的门。门后有人问：你终于回来了？\n"
QUOTE = "林岑收起雨伞"
MISSING = {"dialogue_behavior", "character_fidelity", "canon_fidelity"}


def reviewer_with_response(
    tmp_path,
    *,
    missing=MISSING,
    severity="warning",
    evidence=QUOTE,
    status="evaluated",
    gate_status="pass",
):
    prompts = []

    def chat(**kwargs):
        messages = kwargs["messages"]
        system = messages[0].content
        prompts.append(messages[1].content)
        domain = next((d for d in QUALITY_DOMAINS if f"只评审“{d.name}”域" in system), None)
        if domain is None:
            payload = {"id": "safety", "status": gate_status, "findings": []}
        else:
            payload = {
                "id": domain.id,
                "issues": [],
                "criteria": [
                    {
                        "id": c.id,
                        "status": status if c.id in missing else "evaluated",
                        "earned": c.max_points * 0.8,
                        "evidence": [] if c.id in missing else [QUOTE],
                        "rationale": "依据同条问题中的引用进行评分",
                        "issues": (
                            [
                                {
                                    "severity": severity,
                                    "evidence": evidence,
                                    "description": f"{c.id} 待调整",
                                    "suggestion": "复核正文",
                                }
                            ]
                            if c.id in missing
                            else []
                        ),
                    }
                    for c in domain.criteria
                ],
            }
        return SimpleNamespace(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage={},
            total_tokens=0,
        )

    client = SimpleNamespace(
        chat=chat,
        config=SimpleNamespace(max_tokens=24000, context_tokens=64000, model="fixture-model"),
    )
    return ReviewerAgent(AgentContext(client, "fixture-model", str(tmp_path))), prompts


def criterion(result, criterion_id):
    return next(
        c for d in result.review_v2["domains"] for c in d["criteria"] if c["id"] == criterion_id
    )


def test_nested_locatable_evidence_recovers_all_three_reported_criteria(tmp_path):
    reviewer, prompts = reviewer_with_response(tmp_path)
    result = asyncio.run(reviewer.review(PROSE, {}))
    assert len(prompts) == 7
    for name in MISSING:
        item = criterion(result, name)
        assert item["evidence"] == [QUOTE]
        assert item["evidence_source"] == "criterion_issues"
        assert item["status"] == "evaluated" and item["earned"] > 0
    assert result.review_v2["coverage"] == 1
    assert result.score == 80 and result.review_v2["score_valid"] is True
    assert result.passed and result.review_v2["delivery_status"] == "pass"
    assert len([issue for issue in result.issues if issue.description.endswith("待调整")]) == 3
    assert _apply_canon_gate(result.review_v2, strict=False, context={}) == {}
    assert result.review_v2["quality_score"] == 80


@pytest.mark.parametrize(
    "options",
    [
        {"evidence": "不在正文中的完整引用"},
        {"evidence": ""},
        {"status": "inconclusive"},
    ],
)
def test_missing_or_explicitly_inconclusive_evidence_still_prevents_delivery(tmp_path, options):
    reviewer, _ = reviewer_with_response(tmp_path, **options)
    result = asyncio.run(reviewer.review(PROSE, {}))
    assert result.passed is False and result.score is None
    assert result.review_v2["delivery_status"] == "inconclusive"
    assert criterion(result, "canon_fidelity")["status"] == "inconclusive"
    info = _apply_canon_gate(result.review_v2, strict=False, context={})
    assert info["reason"] == "canon_unverified"
    assert result.review_v2["quality_score"] is None


def test_nested_critical_findings_cannot_disappear_when_evidence_is_recovered(tmp_path):
    reviewer, _ = reviewer_with_response(tmp_path, severity="critical")
    result = asyncio.run(reviewer.review(PROSE, {}))
    assert any(issue.severity == "critical" for issue in result.issues)
    assert result.review_v2["gate_status"] == "blocked"
    assert result.review_v2["delivery_status"] == "blocked" and not result.passed


def test_safety_gate_is_not_bypassed_by_recovered_criterion_evidence(tmp_path):
    reviewer, _ = reviewer_with_response(tmp_path, gate_status="inconclusive")
    result = asyncio.run(reviewer.review(PROSE, {}))
    assert result.review_v2["gate_status"] == "inconclusive" and not result.passed


def test_criteria_never_borrow_a_neighbours_evidence_and_reject_malformed_shapes():
    domain = next(d for d in QUALITY_DOMAINS if d.id == "character")
    raw = [
        {
            "id": domain.criteria[0].id,
            "status": "evaluated",
            "earned": 5,
            "evidence": "不存在的句子",
        },
        {
            "id": domain.criteria[1].id,
            "status": "evaluated",
            "earned": 5,
            "evidence": {},
            "issues": [{"severity": "warning", "evidence": QUOTE, "dimension": 2}],
        },
        {"id": domain.criteria[2].id, "status": "evaluated", "earned": 5, "evidence": QUOTE},
    ]
    validated = ReviewerAgent._validated_criteria(raw, domain, PROSE)
    assert validated[0]["evidence"] == []  # the string must not split into character quotes
    assert validated[1]["evidence"] == []  # unrelated check 2 is not evidence for this criterion
    assert validated[2]["evidence"] == [QUOTE]
    assert validated[1]["issues"] == []


def test_partial_coherence_review_cannot_claim_whole_chapter_delivery(tmp_path):
    reviewer, _ = reviewer_with_response(tmp_path, missing=set())
    dimensions = resolve_review_dimensions(domains=["coherence"])
    result = asyncio.run(reviewer.review(PROSE, {}, dimensions=dimensions))
    assert result.review_v2["scope_status"] == "partial"
    assert result.review_v2["scope_passed"] is True
    assert result.review_v2["scope_quality_score"] == 80
    assert result.review_v2["delivery_status"] == "inconclusive"
    assert result.review_v2["delivery_reason"] == "partial_review"
    assert result.score is None and not result.passed
    assert _apply_canon_gate(result.review_v2, strict=False, context={}) == {}
    assert result.review_v2["delivery_status"] == "inconclusive"


def test_machine_annotations_are_removed_before_all_scoring_paths_and_prompts(tmp_path):
    state = "//**林岑[心态]：忐忑 -> 禁用元数据词**"
    relationship = "//**林岑~>苏遥:互相信任**"
    # Authored examples in a mixed code block remain readable content; malformed
    # metadata is also retained rather than silently hiding ordinary author text.
    code = "```text\n普通示例\n//**例子[心态]：旧 -> 新**\n```\n"
    malformed = "//**林岑[心态] 缺少分隔符 -> 不能隐藏**\n"
    source = PROSE + state + "\n" + relationship + "\n" + code + malformed
    path = tmp_path / "chapter.md"
    path.write_text(source, encoding="utf-8")
    reviewer, prompts = reviewer_with_response(tmp_path, missing=set())
    result = asyncio.run(
        reviewer.review(
            source,
            {
                "term_table": [{"term": "禁用元数据词", "forbidden": True}],
            },
        )
    )
    assert len(prompts) == 7
    for prompt in prompts:
        assert state not in prompt and relationship not in prompt
        assert QUOTE in prompt and code in prompt and malformed in prompt
    assert result.review_v2["terminology"]["findings"] == []
    assert path.read_text(encoding="utf-8") == source
    assert result.passed


def test_real_review_pipeline_persists_recovered_score_without_changing_manuscript(
    tmp_path, monkeypatch
):
    import tools.llm as llm
    from tools.chapter_pipeline import execute_review_chapter
    from tools.init_project import init_project
    from tools.review_store import ReviewStore

    init_project(tmp_path, "demo")
    path = tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    annotation = "//**林岑[心态]：忐忑 -> 镇定**\n"
    source = PROSE + annotation
    path.write_text(source, encoding="utf-8")
    reviewer, prompts = reviewer_with_response(tmp_path)
    monkeypatch.setattr(
        llm.LLMConfig, "from_env", classmethod(lambda cls: reviewer.ctx.client.config)
    )
    monkeypatch.setattr(llm, "LLMClient", lambda _config: reviewer.ctx.client)
    result = execute_review_chapter(tmp_path, {"chapter_id": "ch_001"})
    assert result["ok"] is True, result
    assert result["passed"] is True and result["score"] == 80
    assert result["review_v2"]["delivery_status"] == "pass"
    assert result["review_v2"]["delivery_diagnostics"]["code"] == "review_complete"
    saved = ReviewStore(tmp_path, "demo").load("ch_001")
    assert saved["review_v2"]["delivery_status"] == "pass"
    assert saved["score"] == 80
    assert all(annotation.strip() not in prompt for prompt in prompts)
    assert path.read_text(encoding="utf-8") == source


@pytest.mark.parametrize("method", ["domain", "gate", "legacy"])
def test_direct_audit_helpers_also_strip_machine_metadata(tmp_path, method):
    reviewer, prompts = reviewer_with_response(tmp_path, missing=set())
    annotation = "//**林岑[心态]：忐忑 -> 镇定**"
    content = PROSE + annotation + "\n"
    if method == "domain":
        reviewer._llm_review_domain(content, {}, QUALITY_DOMAINS[0], [])
    elif method == "gate":
        reviewer._llm_review_gate(content, {}, [])
    else:

        def legacy_chat(**kwargs):
            prompts.append(kwargs["messages"][1].content)
            return SimpleNamespace(content="[]", finish_reason="stop", usage={}, total_tokens=0)

        reviewer.ctx.client.chat = legacy_chat
        reviewer._llm_audit_batch(content, {}, [2])
    assert len(prompts) == 1
    assert annotation not in prompts[0]
    assert QUOTE in prompts[0]
