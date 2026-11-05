"""Tool narrowing must never deny the model every tool.

`_tools_for_instruction` used to return an empty set whenever the named tool was
not in the active persona's surface. Downstream, `_completion_params` omits the
`tools` key entirely when the list is empty, so the model is invoked with no
tools while the system prompt still advertises them all — the turn "succeeds"
with a text-only answer and the author's request silently does not happen.
"""

from __future__ import annotations

from tools.agent.react import OPENWRITE_TOOLS, ReActAgent


def _agent() -> ReActAgent:
    agent = object.__new__(ReActAgent)
    agent.tools = list(OPENWRITE_TOOLS)
    return agent


def _real_tool() -> str:
    return next(tool.name for tool in OPENWRITE_TOOLS if tool.name.startswith("read_"))


def test_a_tool_outside_the_persona_surface_falls_back_instead_of_denying():
    agent = _agent()
    tools, _requested = agent._tools_for_instruction("只调用 read_outline 读取大纲")
    # `read_outline` is a dsh-plugin tool, not in the Core agent surface: the
    # restriction cannot be honored, so the agent keeps every tool rather than
    # being invoked with none.
    assert len(tools) == len(agent.tools)


def test_a_negated_restriction_does_not_narrow_to_the_excluded_tool():
    agent = _agent()
    tools, requested = agent._tools_for_instruction(
        "不要只调用 get_status，还要读取章节列表"
    )
    assert requested == ""
    assert len(tools) == len(agent.tools)


def test_a_restriction_without_the_verb_is_still_honored():
    agent = _agent()
    name = _real_tool()
    tools, requested = agent._tools_for_instruction(f"只能用 {name}")
    assert requested == name
    assert [tool.name for tool in tools] == [name]


def test_casing_differences_still_narrow():
    agent = _agent()
    name = _real_tool()
    tools, requested = agent._tools_for_instruction(f"只调用 {name.upper()}")
    assert requested == name
    assert [tool.name for tool in tools] == [name]


def test_no_restriction_means_the_full_surface():
    agent = _agent()
    tools, requested = agent._tools_for_instruction("帮我看看大纲")
    assert requested == ""
    assert len(tools) == len(agent.tools)


def test_narrowing_is_never_empty():
    agent = _agent()
    name = _real_tool()
    for text in [
        f"只调用 {name}",
        f"只能用 {name}",
        f"仅允许调用 {name}",
        f"只调用 {name.upper()}",
        "只调用 a_tool_that_does_not_exist",
        "只调用 delegate_chapter_write",
        "",
    ]:
        assert agent._tools_for_instruction(text)[0], f"empty tool set for {text!r}"
