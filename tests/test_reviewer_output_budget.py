"""Exercise real reviewer calls before any successful usage reveals reasoning."""

import json
from types import SimpleNamespace

import pytest

from tools.agent.base import AgentContext
from tools.agent.reviewer import ReviewerAgent
from tools.llm.response import ProviderResponseError
from tools.review_rubric import CriterionSpec, DomainSpec


DOMAIN = DomainSpec("coherence", "连贯", 5, (CriterionSpec("continuity", "连续性", 5, (2,)),))


@pytest.mark.parametrize("path", ["gate", "domain", "legacy"])
def test_first_review_call_keeps_configured_reasoning_budget(tmp_path, path):
    calls = []
    payload = {
        "gate": {"id": "safety", "status": "pass", "findings": []},
        "domain": {"id": DOMAIN.id, "criteria": [
            {"id": "continuity", "status": "evaluated", "earned": 5, "evidence": ["雨停了"]}
        ], "issues": []},
        "legacy": [],
    }[path]

    def chat(**kwargs):
        calls.append(kwargs)
        # Reproduce #69 through BaseAgent's response classifier, including the
        # single-criterion and safety paths that had no budget-raising retry.
        truncated = kwargs["max_tokens"] < 16_000
        return SimpleNamespace(
            content="" if truncated else json.dumps(payload),
            reasoning="reasoning", finish_reason="length" if truncated else "stop",
            usage={"completion_tokens_details": {"reasoning_tokens": 15_000}},
            total_tokens=15_100,
        )

    client = SimpleNamespace(chat=chat, config=SimpleNamespace(max_tokens=24_000, context_tokens=64_000))
    reviewer = ReviewerAgent(AgentContext(client, "reasoning-model", str(tmp_path)))
    if path == "gate":
        result, _ = reviewer._llm_review_gate("雨停了。", {}, [])
        assert result["status"] == "pass"
    elif path == "domain":
        result, _ = reviewer._llm_review_domain("雨停了。", {}, DOMAIN, [])
        assert result["criteria"][0]["earned"] == 5
    else:
        assert reviewer._llm_audit_batch("雨停了。", {}, [2]) == []
    assert [call["max_tokens"] for call in calls] == [24_000]
    assert reviewer._audit_context_reports[0]["max_output_tokens"] == 24_000


@pytest.mark.parametrize("configured,context,expected", [(2048, 64000, 2048), (24000, 64000, 24000), (24000, 8192, 7168)])
def test_review_respects_author_limit_and_context_window(tmp_path, configured, context, expected):
    client = SimpleNamespace(config=SimpleNamespace(max_tokens=configured, context_tokens=context))
    reviewer = ReviewerAgent(AgentContext(client, "test", str(tmp_path)))
    assert reviewer._audit_output_budget([2]) == expected


def test_truncated_single_criterion_does_not_repeat_the_same_capped_request(tmp_path):
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content="", reasoning="reasoning", finish_reason="length", usage={})

    client = SimpleNamespace(chat=chat, config=SimpleNamespace(max_tokens=4096, context_tokens=64000))
    reviewer = ReviewerAgent(AgentContext(client, "test", str(tmp_path)))
    with pytest.raises(ProviderResponseError) as failure:
        reviewer._llm_review_domain("雨停了。", {}, DOMAIN, [])
    assert failure.value.code == "MODEL_OUTPUT_TRUNCATED"
    assert len(calls) == 1


def test_explicit_small_legacy_budget_retries_with_matching_context_reservation(tmp_path):
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        truncated = kwargs["max_tokens"] < 16000
        return SimpleNamespace(content="" if truncated else "[]", reasoning="reasoning",
                               finish_reason="length" if truncated else "stop", usage={}, total_tokens=1)

    client = SimpleNamespace(chat=chat, config=SimpleNamespace(max_tokens=24000, context_tokens=64000))
    reviewer = ReviewerAgent(AgentContext(client, "test", str(tmp_path)))
    assert reviewer._llm_audit_batch("雨停了。" * 12000, {}, [2], output_budget=4096) == []
    assert [call["max_tokens"] for call in calls] == [4096, 24000]
    reports = reviewer._audit_context_reports
    assert [report["max_output_tokens"] for report in reports] == [4096, 24000]
    assert reports[1]["final_estimated_tokens"] <= reports[1]["input_budget_tokens"]


def test_non_truncation_error_is_not_retried_or_split(tmp_path):
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        raise ProviderResponseError("PROVIDER_AUTHENTICATION_ERROR", "authentication failed")

    client = SimpleNamespace(chat=chat, config=SimpleNamespace(max_tokens=24000, context_tokens=64000))
    reviewer = ReviewerAgent(AgentContext(client, "test", str(tmp_path)))
    domain = DomainSpec("coherence", "连贯", 10, (
        DOMAIN.criteria[0], CriterionSpec("cause", "因果", 5, (11,)),
    ))
    with pytest.raises(ProviderResponseError) as failure:
        reviewer._llm_review_domain("雨停了。", {}, domain, [])
    assert failure.value.code == "PROVIDER_AUTHENTICATION_ERROR"
    assert len(calls) == 1
