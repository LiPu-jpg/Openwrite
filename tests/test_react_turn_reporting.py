"""The ReAct turn must not report work it did not do.

Two defects let the author believe a requested change happened when it did not:
a confirmation-gated mutation was counted as a *successful* result (so the
partial-success message said "已成功并保留"), and a mid-loop stop abandoned the
turn's remaining declared tool calls without mentioning them.
"""

from __future__ import annotations

import json

from tools.agent.confirmation import CONFIRMATION_BLOCK_ERROR
from tools.agent.react import ReActAgent


def _gated(tool: str = "edit_project_document") -> str:
    return json.dumps(
        {
            "ok": False,
            "applied": False,
            "blocked": True,
            "error": CONFIRMATION_BLOCK_ERROR,
            "next_action": "request_mutation_confirmation",
        },
        ensure_ascii=False,
    )


def test_a_confirmation_gate_is_not_counted_as_a_successful_result():
    assert ReActAgent._is_confirmation_gate(_gated()) is True
    # An ordinary failure is not a gate.
    assert ReActAgent._is_confirmation_gate(json.dumps({"ok": False, "error": "boom"})) is False
    assert ReActAgent._is_confirmation_gate("not json") is False


def test_the_partial_success_message_names_gated_changes_as_not_applied():
    message = ReActAgent._partial_success_response(
        [("read_workspace", json.dumps({"ok": True}))],
        failed_tool="edit_outline_structure",
        failure_reason="old_text_not_found",
        failure_count=2,
        gated_results=[("edit_project_document", _gated())],
    )
    assert "尚未应用" in message
    assert "edit_project_document" in message
    assert "等待你明确确认" in message
    # The read-only result is filtered out, so the message must not claim a
    # mutation succeeded.
    assert "已成功并保留" not in message


def test_a_gated_change_never_appears_in_the_retained_list():
    message = ReActAgent._partial_success_response(
        [("edit_project_document", _gated())],
        failed_tool="edit_outline_structure",
        failure_reason="old_text_not_found",
        failure_count=2,
    )
    # Nothing was written, so there is nothing to report as retained.
    assert message == ""


def test_skipped_declared_calls_are_named():
    message = ReActAgent._with_skipped_calls(
        "请确认大纲范围",
        [{"name": "edit_project_document"}, {"name": "update_truth_file"}],
    )
    assert "未执行：edit_project_document、update_truth_file" in message
    assert "未产生任何变更" in message
    # With nothing skipped the message is unchanged.
    assert ReActAgent._with_skipped_calls("完成", []) == "完成"
