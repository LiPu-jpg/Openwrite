import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.agent as agent_module
import tools.cli as cli_module
import tools.llm as llm_module
from tools.agent.book_state import BookStateStore
from tools.agent.reviewer import ReviewerAgent
from tools.agent.writer import WriterAgent
from tools.chapter_memory import ChapterMemoryStore
from tools.context_builder import ContextBuilder
from tools.init_project import init_project
from tools.llm.response import ProviderResponseError
from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.review_rubric import QUALITY_DOMAINS
from tools.truth_manager import TruthFiles, TruthFilesManager


def test_chapter_memory_is_bounded_and_enters_next_chapter_context(tmp_path: Path):
    init_project(tmp_path, "demo")
    store = ChapterMemoryStore(tmp_path, "demo")
    store.save(
        chapter_id="ch_001",
        title="雨夜",
        summary="主角收到来自三年前的信。",
        word_count=3000,
    )
    store.save(
        chapter_id="ch_002",
        title="地下室",
        summary="主角发现地下室的门从内部上锁。",
        word_count=3200,
    )

    context = ContextBuilder(tmp_path, "demo").build_generation_context("ch_003")

    assert "ch_001《雨夜》" in context.chapter_summaries
    assert "ch_002《地下室》" in context.chapter_summaries
    assert context.to_prompt_sections()["历史章节记忆"] == context.chapter_summaries
    assert len(store.render_context("ch_003", max_chars=80)) <= 80


def test_project_write_lock_rejects_live_owner_and_recovers_after_release(tmp_path: Path):
    first = ProjectWriteLock(tmp_path, "demo", operation="write:ch_001")
    second = ProjectWriteLock(tmp_path, "demo", operation="review:ch_001")

    first.acquire()
    try:
        with pytest.raises(ProjectBusyError, match="write:ch_001"):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    assert second.acquired is True
    second.release()


def test_writer_payload_preserves_compass_without_canonical_packet():
    context = SimpleNamespace(
        target_words=3000,
        author_intent="# 作者意图\n守住人物选择",
        creative_focus="# 创作罗盘\n本章完成关系反转",
        chapter_goals=["推进冲突"],
        dramatic_context={"section": "midpoint"},
        current_state="当前状态",
        foreshadowing_summary="伏笔A",
        ledger="账本",
        relationships="关系",
        recent_text="上一章正文",
        chapter_summaries="- ch_001：主角收到来信",
    )
    truth = SimpleNamespace(relationships="关系")

    payload = cli_module._build_writer_context_payload(
        context=context,
        truth=truth,
        context_packet={},
        guidance="冲突更直接",
        target_words=0,
    )
    prompt = WriterAgent._build_creative_user_prompt(
        SimpleNamespace(), payload, chapter_number=2, target_words=3000
    )

    assert "守住人物选择" in payload["author_intent"]
    assert "本章完成关系反转" in payload["creative_focus"]
    assert "## 作者意图（长期约束）" in prompt
    assert "## 创作罗盘（本次最高优先级）" in prompt
    assert "## 历史章节记忆" in prompt


def test_writer_settlement_parses_summary_and_aggregates_all_usage():
    writer = WriterAgent.__new__(WriterAgent)
    parsed = writer._parse_settlement(
        """```yaml
state_updates:
  current_state: |
    主角已经进入地下室。
  particle_ledger: |
    钥匙：已消耗
  character_matrix: |
    陈默 -> 林夏：产生怀疑
chapter_summary: |
  主角违背警告进入地下室，并发现来自未来的监控画面。
```""",
        {},
        usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    )

    assert parsed["state_updates"]["ledger"] == "钥匙：已消耗"
    assert parsed["state_updates"]["relationships"].startswith("陈默")
    assert "违背警告" in parsed["chapter_summary"]
    assert writer._merge_usage(
        {"prompt_tokens": 10, "total_tokens": 15},
        {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
    ) == {"prompt_tokens": 30, "total_tokens": 40, "completion_tokens": 5}
    assert writer._merge_usage(
        {"prompt_tokens": 10, "cost_usd": 0, "cost_reported": True},
        {"completion_tokens": 5, "cost_reported": False},
    ) == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_usd": 0,
        "cost_reported": False,
        "cost_reported_calls": 1,
        "usage_calls": 2,
    }


def test_reviewer_usage_summary_preserves_partial_cost_reporting():
    reviewer = ReviewerAgent.__new__(ReviewerAgent)
    reviewer._audit_context_reports = [
        {
            "provider_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "cost_usd": 0,
                "cost_reported": True,
            }
        },
        {
            "provider_usage": {
                "prompt_tokens": 12,
                "completion_tokens": 6,
                "cost_reported": False,
            }
        },
    ]

    usage = reviewer._audit_usage_summary()

    assert usage["prompt_tokens"] == 22
    assert usage["completion_tokens"] == 10
    assert usage["cost_usd"] == 0
    assert usage["cost_reported"] is False
    assert usage["cost_reported_calls"] == 1
    assert usage["usage_calls"] == 2


def test_writer_settlement_accepts_unfenced_yaml():
    writer = WriterAgent.__new__(WriterAgent)

    parsed = writer._parse_settlement(
        """state_updates:
  current_state: |
    沈烬已提交回响实习申请。
  relationships: |
    沈烬 -> 刑无咎：确认对方隐瞒旧案。
chapter_summary: |
  沈烬听完死亡退出的真实代价后仍提交申请，并得知有人收购万戏社残页。
""",
        {},
    )

    assert parsed["state_updates"]["current_state"].startswith("沈烬已提交")
    assert "隐瞒旧案" in parsed["state_updates"]["relationships"]
    assert "万戏社残页" in parsed["chapter_summary"]


def test_writer_settlement_accepts_prefaced_yaml_block():
    writer = WriterAgent.__new__(WriterAgent)

    parsed = writer._parse_settlement(
        """以下是结算结果：

state_updates:
  ledger: |
    回响残页：持有，风险上升。
chapter_summary: 沈烬确认残页正在被追查。
""",
        {},
    )

    assert parsed["state_updates"]["ledger"].startswith("回响残页")
    assert parsed["chapter_summary"] == "沈烬确认残页正在被追查。"


def test_writer_settlement_rejects_malformed_structured_output():
    from tools.llm.response import ProviderResponseError

    writer = WriterAgent.__new__(WriterAgent)
    with pytest.raises(ProviderResponseError) as raised:
        writer._parse_settlement("state_updates: [broken", {})
    assert raised.value.code == "MALFORMED_STRUCTURED_OUTPUT"


def test_writer_settlement_rejects_invalid_runtime_delta_schema():
    from tools.llm.response import ProviderResponseError

    writer = WriterAgent.__new__(WriterAgent)
    with pytest.raises(ProviderResponseError) as raised:
        writer._parse_settlement(
            """state_delta:
  chapter_id: ch_001
  operations:
    - op: append
      collection: unsupported_collection
      value: fact
chapter_summary: summary
""",
            {},
        )
    assert raised.value.code == "MALFORMED_STRUCTURED_OUTPUT"


def test_writer_settlement_falls_back_when_object_delta_has_string_value():
    writer = WriterAgent.__new__(WriterAgent)

    parsed = writer._parse_settlement(
        """state_delta:
  chapter_id: ch_007
  operations:
    - op: append
      collection: open_threads
      value: 收购者身份仍未确认
state_updates:
  current_state: 沈烬确认有人正在收购残页。
chapter_summary: 沈烬发现残页收购线索。
""",
        {"chapter_number": 7},
    )

    assert parsed["state_updates"] == {"current_state": "沈烬确认有人正在收购残页。"}
    assert parsed["state_delta"]["chapter_id"] == "ch_007"
    assert parsed["state_delta"]["operations"][0]["collection"] == "current_state"


def test_writer_parses_chinese_numeral_chapter_heading():
    writer = WriterAgent.__new__(WriterAgent)

    parsed = writer._parse_creative_output(
        "# 第一章 第十三秒\n\n雨落在旧磁带上。",
        chapter_number=1,
        usage={},
    )

    assert parsed["title"] == "第十三秒"
    assert parsed["content"] == "雨落在旧磁带上。"


def test_writer_rejects_empty_creative_reply():
    writer = WriterAgent.__new__(WriterAgent)

    with pytest.raises(RuntimeError, match="empty model reply"):
        writer._parse_creative_output("\n\n", chapter_number=7, usage={})


def test_post_write_validator_accepts_empty_content():
    from tools.post_validator import PostWriteValidator

    assert PostWriteValidator().validate("") == []


def test_writer_settlement_prompt_keeps_canonical_character_relationships():
    writer = WriterAgent.__new__(WriterAgent)

    truth_context = writer._format_truth_files(
        {
            "active_characters": [
                {
                    "name": "沈砚",
                    "description": "沈禾是已故妹妹，只有她会叫沈砚‘阿迟’。",
                }
            ]
        }
    )

    assert "角色正典（不得改写身份与关系）" in truth_context
    assert "已故妹妹" in truth_context


def test_reviewer_flags_large_target_word_count_deviation():
    reviewer = ReviewerAgent.__new__(ReviewerAgent)

    issues = reviewer._rule_based_check("雨" * 1500, target_words=800)

    assert any(issue.category == "目标字数偏差" for issue in issues)


def test_reviewer_context_keeps_author_compass_and_quality_constraints():
    payload = cli_module._build_reviewer_context_payload(
        {
            "author_intent": "长期坚持人物选择有代价",
            "creative_focus": "必须保留雨夜意象；避免突然升级",
            "character_documents": {"陈默": "# 陈默\n谨慎"},
            "concept_documents": {
                "current_state": "陈默在地下室门外",
                "relationships": "陈默 -> 林夏：怀疑",
            },
            "style_documents": {"summary": "克制冷峻"},
            "prompt_sections": {"当前章节": "进入地下室"},
        }
    )

    assert "人物选择有代价" in payload["author_intent"]
    assert "避免突然升级" in payload["creative_focus"]
    assert "进入地下室" in payload["outline"]
    assert payload["relationships"].startswith("陈默")


def test_reviewer_v2_reviews_six_domains_and_one_gate():
    reviewer = ReviewerAgent.__new__(ReviewerAgent)
    reviewer.ctx = SimpleNamespace(
        client=SimpleNamespace(config=SimpleNamespace(model="fake", max_tokens=12_000, context_tokens=64_000))
    )
    reviewer._rule_based_check = lambda content, target_words=0: []
    reviewer._detect_ai_tells = lambda content: []
    reviewer._check_sensitive_words = lambda content: []
    calls: list[str] = []

    def fake_chat(**kwargs):
        prompt = kwargs["messages"][0].content
        calls.append(prompt)
        if "硬门禁评审员" in prompt:
            return SimpleNamespace(content='{"id":"safety","status":"pass","findings":[]}', usage={})
        domain = next(domain for domain in QUALITY_DOMAINS if f'“{domain.name}”' in prompt)
        return SimpleNamespace(
            content=json.dumps(
                {
                    "id": domain.id,
                    "criteria": [
                        {
                            "id": criterion.id,
                            "status": "evaluated",
                            "earned": criterion.max_points,
                            "evidence": ["正文"],
                            "rationale": "证据充分",
                            "issues": [],
                        }
                        for criterion in domain.criteria
                    ],
                    "issues": [],
                },
                ensure_ascii=False,
            ),
            usage={},
        )

    reviewer.chat = fake_chat

    result = asyncio.run(reviewer.review("正文", {}))

    assert result.issues == []
    assert result.score == 100
    assert result.passed is True
    assert len(calls) == 7
    assert sum("硬门禁评审员" in prompt for prompt in calls) == 1
    assert result.review_v2["coverage"] == 1
    assert result.review_v2["provenance"]["audit_calls"] == 7


def test_reviewer_bisects_a_domain_after_output_truncation():
    reviewer = ReviewerAgent.__new__(ReviewerAgent)
    reviewer.ctx = SimpleNamespace(
        client=SimpleNamespace(config=SimpleNamespace(max_tokens=12_000, context_tokens=64_000))
    )
    calls: list[list[str]] = []

    def fake_chat(**kwargs):
        system_prompt = kwargs["messages"][0].content
        requested = [criterion.id for criterion in QUALITY_DOMAINS[0].criteria if f"- {criterion.id}:" in system_prompt]
        calls.append(requested)
        if len(requested) > 2:
            raise ProviderResponseError(
                "MODEL_OUTPUT_TRUNCATED",
                "模型输出因长度限制被截断",
            )
        return SimpleNamespace(
            content=json.dumps(
                {
                    "id": "coherence",
                    "criteria": [
                        {"id": criterion_id, "status": "evaluated", "earned": 5, "evidence": ["正文"]}
                        for criterion_id in requested
                    ],
                    "issues": [],
                },
                ensure_ascii=False,
            ),
            usage={},
        )

    reviewer.chat = fake_chat

    raw, issues = reviewer._llm_review_domain("正文", {}, QUALITY_DOMAINS[0], [])

    assert issues == []
    assert [item["id"] for item in raw["criteria"]] == [
        "temporal_continuity",
        "rules_power_numbers",
        "knowledge_boundary",
        "causality_motivation",
    ]
    assert calls == [
        ["temporal_continuity", "rules_power_numbers", "knowledge_boundary", "causality_motivation"],
        ["temporal_continuity", "rules_power_numbers"],
        ["knowledge_boundary", "causality_motivation"],
    ]


def test_reviewer_uses_profile_budget_and_structured_context_compression():
    reviewer = ReviewerAgent.__new__(ReviewerAgent)
    reviewer.ctx = SimpleNamespace(
        client=SimpleNamespace(
            config=SimpleNamespace(max_tokens=12_000, context_tokens=1_000_000, extra={})
        )
    )
    calls: list[dict] = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        domain = QUALITY_DOMAINS[4]
        return SimpleNamespace(
            content=json.dumps(
                {
                    "id": domain.id,
                    "criteria": [
                        {"id": item.id, "status": "evaluated", "earned": 5, "evidence": ["章节正文"]}
                        for item in domain.criteria
                    ],
                    "issues": [],
                },
                ensure_ascii=False,
            ),
            usage={},
        )

    reviewer.chat = fake_chat
    context = {
        "author_intent": "人物选择必须付出代价",
        "creative_focus": "保持克制",
        "outline": "主角进入地下室",
        "character_profiles": "角色正典" * 20_000,
        "style_profile": "风格约束" * 20_000,
    }

    _, issues = reviewer._llm_review_domain("章节正文" * 1000, context, QUALITY_DOMAINS[4], [])

    assert issues == []
    assert calls[0]["max_tokens"] == 7168
    assert "角色设定" not in calls[0]["messages"][1].content
    assert "审稿上下文已按 Token 预算压缩" not in calls[0]["messages"][1].content
    report = reviewer._audit_context_reports[0]
    assert report["compressed"] is True
    assert report["final_estimated_tokens"] <= report["target_input_tokens"]
    assert report["final_estimated_tokens"] < report["original_estimated_tokens"]
    assert report["target_input_tokens"] > 32_000


def test_write_commit_rolls_back_truth_and_draft_when_memory_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    truth_manager = TruthFilesManager(tmp_path, "demo")
    truth_manager.save_truth_files(TruthFiles(current_state="写前状态"))

    class FakeWriter:
        def __init__(self, agent_ctx):
            self.agent_ctx = agent_ctx

        async def write_chapter(self, **kwargs):
            return SimpleNamespace(
                title="第一章",
                content="正文",
                word_count=2,
                state_updates={"current_state": "写后状态"},
                chapter_summary="章节摘要",
                observations="观察",
                token_usage={"total_tokens": 10},
                finish_reason="stop",
                model="reported-model",
                provider="reported-provider",
            )

    monkeypatch.setattr(agent_module, "WriterAgent", FakeWriter)
    monkeypatch.setattr(
        agent_module,
        "AgentContext",
        lambda client, model, project_root: SimpleNamespace(
            client=client, model=model, project_root=project_root
        ),
    )
    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(model="fake-model")),
    )
    monkeypatch.setattr(llm_module, "LLMClient", lambda config: object())
    monkeypatch.setattr(
        ChapterMemoryStore,
        "save",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("memory disk full")),
    )

    result = cli_module._exec_write_chapter(
        tmp_path,
        {"chapter_id": "ch_001", "target_words": 500},
    )

    assert result["ok"] is False
    assert "memory disk full" in result["error"]
    assert cli_module._load_chapter(tmp_path, "demo", "ch_001") is None
    assert TruthFilesManager(tmp_path, "demo").load_truth_files().current_state == "写前状态"
    lock_path = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "workflows"
        / "project.lock"
    )
    assert not lock_path.exists()


def test_write_commit_handles_null_current_chapter_in_book_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    state_path = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "workflows"
        / "book_state.yaml"
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        "novel_id: demo\n"
        "stage: chapter_preflight\n"
        "current_arc: arc_001\n"
        "current_chapter:\n"
        "pending_confirmation: ''\n",
        encoding="utf-8",
    )

    class FakeWriter:
        def __init__(self, agent_ctx):
            self.agent_ctx = agent_ctx

        async def write_chapter(self, **kwargs):
            return SimpleNamespace(
                title="第一章",
                content="正文",
                word_count=2,
                state_updates={},
                chapter_summary="章节摘要",
                observations="观察",
                token_usage={"total_tokens": 10},
                finish_reason="stop",
                model="reported-model",
                provider="reported-provider",
            )

    monkeypatch.setattr(agent_module, "WriterAgent", FakeWriter)
    monkeypatch.setattr(
        agent_module,
        "AgentContext",
        lambda client, model, project_root: SimpleNamespace(
            client=client, model=model, project_root=project_root
        ),
    )
    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(model="fake-model")),
    )
    monkeypatch.setattr(llm_module, "LLMClient", lambda config: object())

    result = cli_module._exec_write_chapter(
        tmp_path,
        {"chapter_id": "ch_001", "target_words": 500},
    )

    assert result["ok"] is True
    assert result["finish_reason"] == "stop"
    assert result["model"] == "reported-model"
    assert result["provider"] == "reported-provider"
    assert cli_module._load_chapter(tmp_path, "demo", "ch_001") is not None
    assert BookStateStore(tmp_path, "demo").load_or_create().current_chapter == "ch_001"
