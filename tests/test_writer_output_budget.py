import asyncio
from types import SimpleNamespace

import pytest

from tools.agent.base import AgentContext
from tools.agent.writer import WriterAgent


@pytest.mark.parametrize("budget", [8192, 32768, 49152])
def test_all_writer_phases_and_retries_use_selected_model_budget(tmp_path, budget):
    responses = iter([
        "# 第一章：雾城\n\n" + "山" * 10,
        "# 第一章：雾城\n\n" + "山" * 100,
        "角色抵达雾城。",
        "not a valid settlement",
        'state_updates: {}\nchapter_summary: "角色抵达雾城。"',
    ])
    budgets = []

    def chat(**kwargs):
        effective = kwargs.get("max_tokens") or budget
        budgets.append(effective)
        # A reasoning model needs room for reasoning plus visible output.
        assert effective > 6000
        return SimpleNamespace(content=next(responses), usage={"reasoning_tokens": 6000}, finish_reason="stop", total_tokens=6100, model="test", provider="fake")

    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "test", str(tmp_path)))
    async def run():
        creative = await writer._creative_write({}, 1, 0.7, 100)
        assert creative["word_count"] == 100
        facts = await writer._observe_facts({}, 1, "雾城", creative["content"])
        result = await writer._settle({}, 1, "雾城", creative["content"], facts["content"])
        assert result["chapter_summary"] == "角色抵达雾城。"
    asyncio.run(run())
    assert budgets == [budget] * 5
