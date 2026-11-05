"""ReAct Agent 实现

真正的 Agent 循环：
- 接收自然语言指令
- LLM 决定调用哪些工具
- 执行工具，返回结果
- 循环直到 LLM 确认完成
"""

import asyncio
import copy
import hashlib
import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..llm.errors import LLMWrappedError
from ..llm.response import ProviderResponseError, load_tool_arguments
from ..outline_contract import OUTLINE_MARKDOWN_CONTRACT
from ..shared_documents import CHARACTER_MARKDOWN_CONTRACT

logger = logging.getLogger(__name__)


def _redact_debug_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "<max-depth>"
    if isinstance(value, dict):
        payload = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(
                token in lowered
                for token in ("api_key", "apikey", "authorization", "password", "secret", "token")
            ):
                payload[key_text] = "<redacted>"
            elif lowered in {"content", "message", "source", "prompt", "guidance"}:
                payload[key_text] = _debug_string_preview(item)
            else:
                payload[key_text] = _redact_debug_value(item, depth=depth + 1)
        return payload
    if isinstance(value, list):
        return [_redact_debug_value(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return _debug_string_preview(value)
    return value


def _debug_string_preview(value: Any, *, limit: int = 500) -> str:
    text = str(value or "").replace("\n", "\\n")
    return text[:limit] + ("..." if len(text) > limit else "")


def _debug_json(value: Any) -> str:
    return json.dumps(
        _redact_debug_value(value),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _tool_argument_issues(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "$",
) -> list[str]:
    issues: list[str] = []
    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else list(expected or [])
    type_matches = not expected_types or any(
        _matches_json_type(value, expected_type) for expected_type in expected_types
    )
    if not type_matches:
        expected_label = " / ".join(_json_type_label(item) for item in expected_types)
        return [f"字段 {path} 应为{expected_label}，实际为{_python_type_label(value)}"]

    allowed = schema.get("enum")
    if isinstance(allowed, list) and value not in allowed:
        choices = "、".join(repr(item) for item in allowed)
        issues.append(f"字段 {path} 的值无效，可选值为 {choices}")

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for name in required:
                if name not in value:
                    issues.append(f"缺少必填字段 {path}.{name}")
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, item in value.items():
                item_schema = properties.get(name)
                if isinstance(item_schema, dict):
                    issues.extend(
                        _tool_argument_issues(item, item_schema, path=f"{path}.{name}")
                    )
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            issues.extend(
                _tool_argument_issues(
                    item,
                    schema["items"],
                    path=f"{path}[{index}]",
                )
            )
    return issues[:8]


def _matches_json_type(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }
    check = checks.get(str(expected))
    return True if check is None else check()


def _json_type_label(value: str) -> str:
    return {
        "object": "对象",
        "array": "数组",
        "string": "字符串",
        "integer": "整数",
        "number": "数字",
        "boolean": "布尔值",
        "null": "空值",
    }.get(value, value)


def _python_type_label(value: Any) -> str:
    if isinstance(value, bool):
        return "布尔值"
    if isinstance(value, dict):
        return "对象"
    if isinstance(value, list):
        return "数组"
    if isinstance(value, str):
        return "字符串"
    if isinstance(value, int):
        return "整数"
    if isinstance(value, float):
        return "数字"
    if value is None:
        return "空值"
    return type(value).__name__


@dataclass
class ToolDefinition:
    """工具定义"""

    name: str
    description: str
    parameters: dict
    required: list[str] = field(default_factory=list)


@dataclass
class ToolCall:
    """工具调用"""

    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """工具执行结果"""

    tool_call_id: str
    result: str
    error: str | None = None


class ReActAgent:
    """ReAct Agent

    真正的 Agent 循环：
    1. 构建 system prompt（包含工具定义）
    2. 循环（最多 max_turns）：
       - 调用 LLM（带工具）
       - LLM 返回 content 或 tool_calls
       - 如果有 content，打印并检查是否结束
       - 如果有 tool_calls，执行并添加结果到消息
    3. 返回最终结果

    用法:
        agent = ReActAgent(
            client=llm_client,
            model="gpt-4o-mini",
            tools=MY_TOOLS,
            system_prompt=SYSTEM_PROMPT,
        )
        result = await agent.run("写第五章")
    """

    def __init__(
        self,
        client: Any,
        model: str,
        tools: list[ToolDefinition],
        system_prompt: str,
        max_turns: int = 20,
        max_tool_failures: int = 2,
        max_model_repairs: int = 1,
        max_transport_failures: int = 3,
        activity_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.client = client
        self.model = model
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.max_tool_failures = max(1, int(max_tool_failures))
        self.max_model_repairs = max(0, int(max_model_repairs))
        # A provider hiccup says nothing about the request, so the turn may ask
        # again. Without a bound, a provider that is down for a minute would
        # burn every turn of the run on retries.
        self.max_transport_failures = max(0, int(max_transport_failures))
        self.activity_callback = activity_callback

    async def run(
        self,
        instruction: str,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_result: Callable[[str, str], None] | None = None,
        on_message: Callable[[str], None] | None = None,
        context_messages: Sequence[Any] | None = None,
        context_message_factory: Callable[[], Sequence[Any]] | None = None,
    ) -> str:
        """运行 Agent

        Args:
            instruction: 用户指令
            on_tool_call: 工具调用回调 (name, args)
            on_tool_result: 工具结果回调 (name, result)
            on_message: LLM 消息回调 (content)

        Returns:
            最终回复内容
        """
        from ..llm import Message

        messages = [Message("system", self.system_prompt)]
        factory_messages = context_message_factory() if context_message_factory else None
        messages.extend(self._coerce_messages(factory_messages))
        messages.extend(self._coerce_messages(context_messages))
        messages.append(Message("user", instruction))

        final_content = ""
        saw_tool_calls = False
        failed_tool_counts: dict[str, int] = {}
        failed_tool_arguments: dict[
            str,
            tuple[dict[str, Any], set[str], dict[str, Any]],
        ] = {}
        successful_tool_results: list[tuple[str, str]] = []
        gated_tool_results: list[tuple[str, str]] = []
        # Set when a mid-loop branch wants to stop the turn; the remaining
        # declared tool calls are executed first so nothing is dropped silently.
        pending_terminal: tuple[str, list[dict[str, Any]]] | None = None
        pending_failure: str | None = None
        # Consecutive repairs within a turn; the run-level budget below is what
        # bounds total spend.
        model_repairs = 0
        total_model_repairs = 0
        # Consecutive transport failures (rate limit, network, timeout). They
        # are counted apart from model repairs: a provider hiccup is not the
        # model's fault and must not spend the repair budget.
        transport_failures = 0
        model_output_tokens: int | None = None
        active_tools, requested_tool = self._tools_for_instruction(instruction)
        self._emit_activity(
            "run_started",
            instruction_chars=len(instruction),
            requested_tool=requested_tool,
        )

        for turn in range(self.max_turns):
            logger.debug(f"Turn {turn + 1}/{self.max_turns}")
            self._emit_activity(
                "model_started",
                turn=turn + 1,
                max_turns=self.max_turns,
            )

            try:
                response = self._chat_with_tools(
                    messages,
                    active_tools,
                    max_tokens=model_output_tokens,
                    max_retries=0,
                )
                decoded_tool_calls = [
                    (tool_call, load_tool_arguments(tool_call, index=index))
                    for index, tool_call in enumerate(response.tool_calls or [])
                ]
            except ProviderResponseError as exc:
                if (
                    exc.code in self._repairable_model_error_codes()
                    and model_repairs < self.max_model_repairs
                    and total_model_repairs < self.max_model_repairs * self.max_turns
                ):
                    model_repairs += 1
                    total_model_repairs += 1
                    previous_output_tokens = model_output_tokens
                    if exc.code == "MODEL_OUTPUT_TRUNCATED":
                        previous_output_tokens, retry_output_tokens = (
                            self._next_truncation_output_budget(model_output_tokens)
                        )
                        if (
                            retry_output_tokens is not None
                            and retry_output_tokens != previous_output_tokens
                        ):
                            model_output_tokens = retry_output_tokens
                    feedback = self._model_repair_feedback(
                        exc,
                        model_repairs,
                        previous_output_tokens=previous_output_tokens,
                        retry_output_tokens=model_output_tokens,
                    )
                    messages.append(Message("user", feedback))
                    budget_message = ""
                    if (
                        previous_output_tokens is not None
                        and model_output_tokens is not None
                        and model_output_tokens > previous_output_tokens
                    ):
                        budget_message = (
                            "系统已将本次重试的最大输出从 "
                            f"{previous_output_tokens:,} 提高到 {model_output_tokens:,} Token。"
                        )
                    self._emit_activity(
                        "model_retry",
                        turn=turn + 1,
                        reason=str(exc),
                        repair_attempt=model_repairs,
                        repair_limit=self.max_model_repairs,
                        details=exc.details,
                        message=budget_message,
                    )
                    continue
                failure = self._exhausted_model_error(exc, model_repairs)
                self._emit_activity(
                    "run_failed",
                    turn=turn + 1,
                    reason=str(failure),
                    error_code=failure.code,
                )
                raise failure from exc
            except LLMWrappedError as exc:
                # A transport failure says nothing about the request: the same
                # call may well succeed a moment later. The loop used to die
                # here, so one rate limit ended the whole turn - while a
                # malformed answer, which says nothing about the provider,
                # got a repair. The two classes deserve the opposite care.
                from ..llm.retry import classify_failure, wait_before_retry_async

                failure = classify_failure(exc, attempt=turn + 1)
                if (
                    not failure.retryable
                    or transport_failures >= self.max_transport_failures
                ):
                    self._emit_activity(
                        "run_failed",
                        turn=turn + 1,
                        reason=str(exc),
                        error_code=failure.code,
                        transport_attempts=transport_failures,
                    )
                    raise
                transport_failures += 1
                delay = await wait_before_retry_async(transport_failures)
                self._emit_activity(
                    "model_retry",
                    turn=turn + 1,
                    reason=str(exc),
                    error_code=failure.code,
                    transport_attempt=transport_failures,
                    transport_limit=self.max_transport_failures,
                    message=f"服务商暂时不可用，{delay:.1f} 秒后重试",
                )
                continue
            model_repairs = 0
            transport_failures = 0
            self._emit_activity(
                "model_completed",
                turn=turn + 1,
                tool_count=len(response.tool_calls or []),
                has_content=bool(response.content),
                message=(response.content or "") if response.tool_calls else "",
            )

            if response.tool_calls:
                saw_tool_calls = True
                assistant_msg = Message("assistant", response.content or "")
                # 为兼容 OpenAI/兼容接口，显式保留 assistant 的 tool_calls。
                setattr(assistant_msg, "tool_calls", response.tool_calls)
                messages.append(assistant_msg)

            if response.content:
                if not response.tool_calls:
                    final_content = response.content
                    on_message and on_message(response.content)
                    logger.debug("Agent finished (no more tool calls)")
                    self._emit_activity(
                        "response_ready",
                        turn=turn + 1,
                        content_chars=len(response.content),
                    )
                    break

            for call_index, (tool_call, tc_args) in enumerate(decoded_tool_calls):
                tc_id = tool_call.get("id", "")
                tc_name = tool_call.get("name", "")
                remaining_tool_calls = [
                    item[0] for item in decoded_tool_calls[call_index + 1:]
                ]
                failure_key = self._tool_failure_key(tc_name, tc_args)
                inherited_fields: list[str] = []
                corrected_fields: list[str] = []
                previous_failure = failed_tool_arguments.get(failure_key)
                if previous_failure is not None:
                    tc_args, inherited_fields = self._inherit_retry_arguments(
                        tc_name,
                        tc_args,
                        previous_failure[0],
                        invalid_roots=previous_failure[1],
                        tools=active_tools,
                    )
                    tc_args, corrected_fields = self._apply_retry_suggestions(
                        tc_name,
                        tc_args,
                        previous_failure[0],
                        previous_failure[2],
                    )
                    failure_key = self._tool_failure_key(tc_name, tc_args)
                repair_notes = []
                if inherited_fields:
                    repair_notes.append(
                        "继承仍有效的必填字段：" + "、".join(inherited_fields)
                    )
                if corrected_fields:
                    repair_notes.append(
                        "按工具诊断精确修正：" + "、".join(corrected_fields)
                    )
                on_tool_call and on_tool_call(tc_name, tc_args)
                self._emit_activity(
                    "tool_started",
                    turn=turn + 1,
                    tool=tc_name,
                    tool_call_id=tc_id,
                    arguments=tc_args,
                    message="系统已自动修复本次重试参数；" + "；".join(repair_notes)
                    if repair_notes
                    else "",
                )
                logger.debug(
                    "react.tool_call %s %s",
                    tc_name,
                    _debug_json(
                        {
                            "turn": turn + 1,
                            "tool_call_id": tc_id,
                            "arguments": tc_args,
                        }
                    ),
                )

                try:
                    result = await asyncio.to_thread(
                        self._execute_tool,
                        tc_name,
                        tc_args,
                        active_tools,
                    )
                    if inherited_fields or corrected_fields:
                        result = self._annotate_argument_repair(
                            result,
                            inherited_fields,
                            corrected_fields,
                        )
                    on_tool_result and on_tool_result(tc_name, result)
                    logger.debug(
                        "react.tool_result %s %s",
                        tc_name,
                        _debug_json(
                            {
                                "turn": turn + 1,
                                "tool_call_id": tc_id,
                                "result_chars": len(result),
                                "result_preview": result,
                            }
                        ),
                    )
                    failure_reason = self._tool_failure_reason(result)
                    self._emit_activity(
                        "tool_completed",
                        turn=turn + 1,
                        tool=tc_name,
                        tool_call_id=tc_id,
                        ok=not bool(failure_reason),
                        reason=failure_reason,
                        result=result,
                    )
                    if failure_reason:
                        invalid_roots, retry_suggestions = (
                            self._tool_failure_argument_repairs(result)
                        )
                        if invalid_roots or retry_suggestions:
                            failed_tool_arguments[failure_key] = (
                                copy.deepcopy(tc_args),
                                invalid_roots,
                                retry_suggestions,
                            )
                        else:
                            failed_tool_arguments.pop(failure_key, None)
                        failed_tool_counts[failure_key] = (
                            failed_tool_counts.get(failure_key, 0) + 1
                        )
                        if failed_tool_counts[failure_key] >= self.max_tool_failures:
                            partial_response = self._partial_success_response(
                                successful_tool_results,
                                failed_tool=tc_name,
                                failure_reason=failure_reason,
                                failure_count=failed_tool_counts[failure_key],
                                gated_results=gated_tool_results,
                            )
                            if partial_response:
                                self._emit_activity(
                                    "run_completed",
                                    partial=True,
                                    secondary_failure=tc_name,
                                )
                                return partial_response
                            logger.warning(
                                "react.tool_failure_limit %s %s",
                                tc_name,
                                _debug_json(
                                    {
                                        "turn": turn + 1,
                                        "tool_call_id": tc_id,
                                        "failures": failed_tool_counts[failure_key],
                                        "reason": failure_reason,
                                    }
                                ),
                            )
                            self._emit_activity(
                                "run_failed",
                                turn=turn + 1,
                                tool=tc_name,
                                reason=failure_reason,
                                failure_count=failed_tool_counts[failure_key],
                            )
                            pending_failure = (
                                f"工具 {tc_name} 连续失败 "
                                f"{failed_tool_counts[failure_key]} 次，"
                                "我已停止本轮以避免继续重复消耗。"
                                f"最后原因：{failure_reason}"
                            )
                            break
                    else:
                        failed_tool_counts.pop(failure_key, None)
                        failed_tool_arguments.pop(failure_key, None)
                        # A soft confirmation gate is not a failure (so the turn
                        # is not aborted) but it is not a success either: nothing
                        # was written. Keeping it out of `successful_tool_results`
                        # stops `_partial_success_response` from telling the author
                        # a gated mutation "已成功并保留".
                        if self._is_confirmation_gate(result):
                            gated_tool_results.append((tc_name, result))
                        else:
                            successful_tool_results.append((tc_name, result))
                    messages.append(
                        Message(
                            role="tool",
                            content=result,
                            tool_call_id=tc_id,
                        )
                    )
                    if not failure_reason:
                        terminal_response = self._terminal_tool_response(result)
                        if terminal_response:
                            # The assistant declared more tool calls in this turn.
                            # Returning here used to abandon them silently, so the
                            # author saw a clean completion for a turn in which a
                            # requested mutation was skipped. Drain the rest first
                            # and name what was not executed.
                            pending_terminal = (terminal_response, remaining_tool_calls)
                            break
                except Exception as e:
                    failed_tool_arguments.pop(failure_key, None)
                    failure_reason = str(e)
                    error_result = json.dumps({"error": failure_reason})
                    on_tool_result and on_tool_result(tc_name, error_result)
                    logger.debug(
                        "react.tool_error %s %s",
                        tc_name,
                        _debug_json(
                            {
                                "turn": turn + 1,
                                "tool_call_id": tc_id,
                                "error": str(e),
                            }
                        ),
                    )
                    self._emit_activity(
                        "tool_completed",
                        turn=turn + 1,
                        tool=tc_name,
                        tool_call_id=tc_id,
                        ok=False,
                        reason=failure_reason,
                        result=error_result,
                    )
                    failed_tool_counts[failure_key] = (
                        failed_tool_counts.get(failure_key, 0) + 1
                    )
                    if failed_tool_counts[failure_key] >= self.max_tool_failures:
                        partial_response = self._partial_success_response(
                            successful_tool_results,
                            failed_tool=tc_name,
                            failure_reason=failure_reason,
                            failure_count=failed_tool_counts[failure_key],
                            gated_results=gated_tool_results,
                        )
                        if partial_response:
                            self._emit_activity(
                                "run_completed",
                                partial=True,
                                secondary_failure=tc_name,
                            )
                            pending_failure = partial_response
                            break
                        logger.warning(
                            "react.tool_failure_limit %s %s",
                            tc_name,
                            _debug_json(
                                {
                                    "turn": turn + 1,
                                    "tool_call_id": tc_id,
                                    "failures": failed_tool_counts[failure_key],
                                    "reason": failure_reason,
                                }
                            ),
                        )
                        self._emit_activity(
                            "run_failed",
                            turn=turn + 1,
                            tool=tc_name,
                            reason=failure_reason,
                            failure_count=failed_tool_counts[failure_key],
                        )
                        return (
                            f"工具 {tc_name} 连续失败 "
                            f"{failed_tool_counts[failure_key]} 次，"
                            "我已停止本轮以避免继续重复消耗。"
                            f"最后原因：{failure_reason}"
                        )
                    messages.append(
                        Message(
                            role="tool",
                            content=error_result,
                            tool_call_id=tc_id,
                        )
                    )
            # The tool-call loop has now drained. Emit whatever a mid-loop branch
            # deferred, naming the declared calls that were not executed.
            if pending_terminal is not None:
                terminal_response, skipped = pending_terminal
                on_message and on_message(terminal_response)
                self._emit_activity(
                    "response_ready",
                    turn=turn + 1,
                    content_chars=len(terminal_response),
                )
                self._emit_activity("run_completed", content_chars=len(terminal_response))
                return self._with_skipped_calls(terminal_response, skipped)
            if pending_failure is not None:
                self._emit_activity("run_failed", reason="tool_failure_limit")
                return self._with_skipped_calls(pending_failure, remaining_tool_calls)
        else:
            logger.warning(f"Reached max turns ({self.max_turns})")
            self._emit_activity(
                "run_failed",
                reason="max_turns_reached",
                turn=self.max_turns,
            )

        if final_content:
            self._emit_activity("run_completed", content_chars=len(final_content))
            return final_content
        if saw_tool_calls:
            self._emit_activity("run_completed", partial=True)
            return (
                "我已经完成了部分工具操作，但本轮还没有整理出最终结果。"
                "请发送“继续”让我基于刚才的工具结果收尾，或把本轮修改范围缩小。"
            )
        self._emit_activity("run_completed", content_chars=0)
        return ""

    @staticmethod
    def _repairable_model_error_codes() -> set[str]:
        return {
            "MALFORMED_TOOL_ARGUMENTS",
            "MODEL_OUTPUT_TRUNCATED",
            "MODEL_EMPTY_RESPONSE",
            "MODEL_REASONING_ONLY",
        }

    @staticmethod
    def _model_repair_feedback(
        error: ProviderResponseError,
        attempt: int,
        *,
        previous_output_tokens: int | None = None,
        retry_output_tokens: int | None = None,
    ) -> str:
        details = error.details
        lines = [
            "系统校验反馈：你刚才的模型输出未通过校验，任何对应工具都没有执行。",
            f"错误代码：{error.code}",
            f"具体问题：{error}",
        ]
        tool_name = str(details.get("tool_name") or "")
        if tool_name:
            lines.append(f"出错工具：{tool_name}")
        if details.get("line") and details.get("column"):
            lines.append(
                f"错误位置：JSON 第 {details['line']} 行第 {details['column']} 列"
            )
        if details.get("context"):
            lines.append(f"错误附近：{details['context']}")
        lines.extend(
            [
                f"这是第 {attempt} 次自动修复。请根据上面的字段和位置重新生成。",
                "只返回合法、完整的工具调用参数；所有键名和字符串使用英文双引号，"
                "正文中的双引号必须转义。不要重复已经成功的工具操作。",
            ]
        )
        if details.get("likely_truncated") or error.code == "MODEL_OUTPUT_TRUNCATED":
            if (
                previous_output_tokens is not None
                and retry_output_tokens is not None
                and retry_output_tokens > previous_output_tokens
            ):
                lines.append(
                    "系统已将本次重试的最大输出从 "
                    f"{previous_output_tokens:,} 提高到 {retry_output_tokens:,} Token。"
                )
            lines.append(
                "本次输出可能被截断。请缩小单次修改范围；大纲重构按幕或最多 4 节分批，"
                "每批调用一次 stage_outline_edits。"
            )
        return "\n".join(lines)

    def _exhausted_model_error(
        self,
        error: ProviderResponseError,
        repairs: int,
    ) -> ProviderResponseError:
        attempts = repairs + 1
        suggestion = (
            "请缩小单次任务；大纲重构可按幕或最多 4 节分批处理。"
            if error.code in {"MALFORMED_TOOL_ARGUMENTS", "MODEL_OUTPUT_TRUNCATED"}
            else "请稍后重试或更换当前操作使用的模型。"
        )
        return ProviderResponseError(
            error.code,
            (
                f"模型连续 {attempts} 次未能生成可执行输出。最后问题：{error}。"
                f"失败的工具调用没有执行。{suggestion}"
            ),
            details={**error.details, "attempts": attempts, "repairs": repairs},
        )

    def _emit_activity(self, event: str, **payload: Any) -> None:
        callback = self.activity_callback
        if callback is None:
            return
        try:
            callback({"event": event, **payload})
        except Exception:
            logger.debug("react.activity_callback_failed", exc_info=True)

    @staticmethod
    def _with_skipped_calls(message: str, skipped: list[dict[str, Any]]) -> str:
        """Name declared tool calls that were not executed.

        The assistant message declares every call of the turn, so stopping the
        loop early used to drop the rest without a word — the author saw a clean
        completion for a turn in which a requested mutation never ran.
        """
        names = [
            str(item.get("name") or "")
            for item in (skipped or [])
            if isinstance(item, dict) and str(item.get("name") or "")
        ]
        if not names:
            return message
        return f"{message}\n\n未执行：{'、'.join(dict.fromkeys(names))}（本轮已停止，未产生任何变更）。"

    @staticmethod
    def _is_confirmation_gate(result: str) -> bool:
        """Whether a tool result is a soft confirmation gate rather than an outcome."""
        from .confirmation import is_confirmation_policy_block

        try:
            payload = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return False
        return is_confirmation_policy_block(payload)

    @staticmethod
    def _tool_failure_reason(result: str) -> str:
        try:
            payload = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        from .confirmation import is_confirmation_policy_block

        # Soft confirmation gates must not abort the ReAct turn.
        if is_confirmation_policy_block(payload):
            return ""
        is_failure = payload.get("ok") is False or bool(payload.get("error"))
        if not is_failure:
            return ""
        # A named diagnosis first: it says what kind of failure this is and
        # what would move it, which a bare error string does not. The agent in
        # front of the loop needs to act on it, not just read it.
        diagnosis = payload.get("diagnosis")
        if isinstance(diagnosis, dict):
            hint = str(diagnosis.get("hint") or "").strip()
            message = str(diagnosis.get("message") or "").strip()
            category = str(diagnosis.get("category") or "").strip()
            if hint or message:
                detail = message or hint
                if category and category != "unknown":
                    return f"[{category}] {detail} {hint}".strip()
                return f"{detail} {hint}".strip()
        reason = (
            payload.get("message")
            or payload.get("reason")
            or payload.get("error")
            or payload.get("code")
            or "工具返回失败"
        )
        return str(reason)

    @staticmethod
    def _terminal_tool_response(result: str) -> str:
        try:
            payload = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        if payload.get("ok") is False or payload.get("error"):
            return ""
        if payload.get("next_action") != "request_outline_confirmation":
            return ""
        return str(payload.get("message") or "").strip()

    def _coerce_messages(self, messages: Sequence[Any] | None) -> list[Any]:
        from ..llm import Message

        if not messages:
            return []

        normalized: list[Any] = []
        for message in messages:
            if isinstance(message, Message):
                normalized.append(message)
            elif isinstance(message, dict):
                normalized.append(
                    Message(
                        role=message.get("role", "assistant"),
                        content=str(message.get("content", "")),
                        tool_call_id=str(message.get("tool_call_id", "")),
                    )
                )
            else:
                normalized.append(Message("assistant", str(message)))
        return normalized

    def _chat_with_tools(
        self,
        messages: list,
        tools: Sequence[ToolDefinition] | None = None,
        *,
        max_tokens: int | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """调用 LLM（带工具）"""

        llm_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in (self.tools if tools is None else tools)
        ]

        kwargs: dict[str, Any] = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if max_retries is not None:
            from ..llm.client import accepts_parameter

            if accepts_parameter(self.client, "chat_with_tools", "max_retries"):
                # The loop below runs the classified retry policy, so LiteLLM's
                # own retry has to be off: two retry layers stack into a burst.
                kwargs["max_retries"] = max_retries
        return self.client.chat_with_tools(messages, llm_tools, **kwargs)

    def _next_truncation_output_budget(
        self,
        current: int | None,
    ) -> tuple[int | None, int | None]:
        config = getattr(self.client, "config", None)
        configured = getattr(config, "max_tokens", None)
        context_tokens = getattr(config, "context_tokens", None)
        try:
            base = int(current if current is not None else configured)
        except (TypeError, ValueError):
            return current, current
        if base <= 0:
            return current, current
        try:
            context_limit = int(context_tokens)
        except (TypeError, ValueError):
            context_limit = 0
        safe_ceiling = context_limit // 2 if context_limit > 0 else base * 2
        retry = max(base, min(base * 2, safe_ceiling))
        return base, retry

    def _execute_tool(
        self,
        name: str,
        args: dict,
        tools: Sequence[ToolDefinition] | None = None,
    ) -> str:
        """执行工具"""
        # 查找工具
        tool = next(
            (t for t in (self.tools if tools is None else tools) if t.name == name),
            None,
        )
        if not tool:
            return json.dumps({"error": f"Unknown tool: {name}"})

        schema_required = tool.parameters.get("required")
        required = list(
            dict.fromkeys(
                [
                    *tool.required,
                    *(schema_required if isinstance(schema_required, list) else []),
                ]
            )
        )
        issues = [f"缺少必填字段 $.{field}" for field in required if field not in args]
        issues.extend(_tool_argument_issues(args, tool.parameters))
        issues = list(dict.fromkeys(issues))[:8]
        if issues:
            return json.dumps(
                {
                    "ok": False,
                    "error": "工具参数校验失败：" + "；".join(issues),
                    "code": "INVALID_TOOL_ARGUMENTS",
                    "details": {"tool": name, "issues": issues},
                },
                ensure_ascii=False,
            )

        # 调用注册的执行器
        if hasattr(self, f"_tool_{name}"):
            result = getattr(self, f"_tool_{name}")(args)
            return json.dumps(result) if isinstance(result, dict) else str(result)

        return json.dumps({"error": f"Tool '{name}' not implemented"})

    @staticmethod
    def _inherit_retry_arguments(
        name: str,
        args: dict[str, Any],
        previous_args: dict[str, Any],
        *,
        invalid_roots: set[str],
        tools: Sequence[ToolDefinition],
    ) -> tuple[dict[str, Any], list[str]]:
        tool = next((item for item in tools if item.name == name), None)
        if tool is None:
            return args, []
        schema_required = tool.parameters.get("required")
        required = list(
            dict.fromkeys(
                [
                    *tool.required,
                    *(schema_required if isinstance(schema_required, list) else []),
                ]
            )
        )
        merged = copy.deepcopy(args)
        inherited: list[str] = []
        for field_name in required:
            if (
                field_name not in merged
                and field_name in previous_args
                and field_name not in invalid_roots
            ):
                merged[field_name] = copy.deepcopy(previous_args[field_name])
                inherited.append(f"$.{field_name}")
        return merged, inherited

    @staticmethod
    def _tool_failure_argument_repairs(
        result: str,
    ) -> tuple[set[str], dict[str, Any]]:
        try:
            payload = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return set(), {}
        if not isinstance(payload, dict):
            return set(), {}
        details = payload.get("details")
        if not isinstance(details, dict):
            return set(), {}
        candidates: list[str] = []
        field_path = details.get("field_path")
        if isinstance(field_path, str):
            candidates.append(field_path)
        field_paths = details.get("field_paths")
        if isinstance(field_paths, list):
            candidates.extend(str(item) for item in field_paths)
        issues = details.get("issues")
        if isinstance(issues, list):
            candidates.extend(str(item) for item in issues)
        invalid_roots = {
            match.group(1)
            for candidate in candidates
            for match in re.finditer(r"\$\.([A-Za-z_][A-Za-z0-9_]*)", candidate)
        }
        suggestions: dict[str, Any] = {}
        if (
            isinstance(field_path, str)
            and field_path.endswith(".old_text")
            and isinstance(details.get("suggested_old_text"), str)
            and details["suggested_old_text"]
            and not details.get("suggested_old_text_truncated")
        ):
            suggestions[field_path] = details["suggested_old_text"]
        retry_base_revision = details.get("retry_base_revision")
        if isinstance(retry_base_revision, str) and retry_base_revision:
            suggestions["$.base_revision"] = retry_base_revision
        retry_revision = details.get("retry_revision")
        if isinstance(retry_revision, str) and retry_revision:
            suggestions["$.revision"] = retry_revision
        return invalid_roots, suggestions

    @staticmethod
    def _apply_retry_suggestions(
        name: str,
        args: dict[str, Any],
        previous_args: dict[str, Any],
        suggestions: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        if name not in {"stage_outline_edits", "edit_project_document"} or not suggestions:
            return args, []
        repaired = copy.deepcopy(args)
        corrected: list[str] = []
        revision_field = (
            "base_revision" if name == "stage_outline_edits" else "revision"
        )
        retry_revision = suggestions.get(f"$.{revision_field}")
        if isinstance(retry_revision, str) and retry_revision:
            if repaired.get(revision_field) != retry_revision:
                repaired[revision_field] = retry_revision
                corrected.append(f"$.{revision_field}")

        current_edits = repaired.get("edits")
        previous_edits = previous_args.get("edits")
        if not isinstance(current_edits, list) or not isinstance(previous_edits, list):
            return repaired, corrected
        for path, suggested_value in suggestions.items():
            match = re.fullmatch(r"\$\.edits\[(\d+)]\.old_text", path)
            if match is None or not isinstance(suggested_value, str):
                continue
            index = int(match.group(1))
            if index >= len(current_edits) or index >= len(previous_edits):
                continue
            current_edit = current_edits[index]
            previous_edit = previous_edits[index]
            if not isinstance(current_edit, dict) or not isinstance(previous_edit, dict):
                continue
            if current_edit.get("new_text") != previous_edit.get("new_text"):
                continue
            if current_edit.get("old_text") != suggested_value:
                current_edit["old_text"] = suggested_value
                corrected.append(path)
        return repaired, corrected

    @staticmethod
    def _tool_failure_key(name: str, args: dict[str, Any]) -> str:
        """Keep independent document edits from consuming each other's retry budget."""

        if name == "edit_project_document":
            path = str(args.get("path") or args.get("source_path") or "").strip()
            if path:
                return f"{name}:{path}"
        if name == "stage_outline_edits":
            # The system prompt instructs batching a large outline rewrite, so
            # each batch is an independent edit set: one batch's failure must not
            # consume another's retry budget, or the turn aborts with
            # "连续失败 2 次" for two unrelated batches.
            label = str(args.get("batch_label") or "").strip()
            edits = args.get("edits")
            if label:
                return f"{name}:{label}"
            if isinstance(edits, list) and edits:
                digest = hashlib.sha256(
                    json.dumps(edits, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()[:16]
                return f"{name}:{digest}"
        return name

    @staticmethod
    def _annotate_argument_repair(
        result: str,
        inherited_fields: list[str],
        corrected_fields: list[str],
    ) -> str:
        try:
            payload = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return result
        if not isinstance(payload, dict):
            return result
        payload["argument_repair"] = {
            "inherited_fields": inherited_fields,
            "corrected_fields": corrected_fields,
            "message": (
                "系统已根据同一工具上一次失败结果补全未被判错的必填字段，并应用"
                "可验证的精确修复建议；被判错的字段不会从旧调用中继承。"
            ),
        }
        return json.dumps(payload, ensure_ascii=False)

    # A restriction the model could not honor. Narrowing to the empty set denies
    # the model every tool while the system prompt still advertises them all, so
    # the turn "succeeds" with a text-only answer and the request silently does
    # not happen.
    _RESTRICTION_PATTERNS = (
        r"(?:只|仅)(?:需|要|能|允许|许)?[^。；，\n]{0,8}?(?:调用|使用)",
        r"\b(?:only\s+call|call\s+only|only\s+use)\b",
    )
    _NEGATION_BEFORE = "不没别勿莫未"

    def _tools_for_instruction(
        self, instruction: str
    ) -> tuple[list[ToolDefinition], str]:
        """Narrow the offered tools when the author asked for one specific tool.

        Fails open rather than closed: a restriction that cannot be honored
        precisely still gets the full surface, because narrowing to the empty set
        denies the model every tool while the system prompt keeps advertising
        them all — the turn then "succeeds" with a text-only answer and the
        request silently does not happen.
        """
        text = str(instruction or "")
        known = {tool.name.lower(): tool.name for tool in self.tools}
        requested = self._requested_tool_name(text, known)
        if not requested:
            return list(self.tools), ""
        narrowed = [tool for tool in self.tools if tool.name.lower() == requested.lower()]
        if not narrowed:
            # The named tool is not in this persona's surface: a cross-persona
            # name, a casing difference, or a name that no longer exists.
            return list(self.tools), requested
        return narrowed, requested

    @staticmethod
    def _requested_tool_name(text: str, known: dict[str, str]) -> str:
        """Return the tool an instruction restricts the agent to, or "".

        The restriction and the tool name are detected independently: tying the
        name to the exact phrasing ("只能用 X" has no 调用/使用 in it) made the
        matcher miss real restrictions, and a restriction that cannot be honored
        precisely must still fail open rather than deny every tool.
        """
        # A restriction the author stated explicitly.
        restricted = re.search(r"只|仅|\bonly\b", text, re.IGNORECASE)
        if restricted is None:
            return ""
        # "不要只调用 X" excludes X rather than naming it.
        window = text[max(0, restricted.start() - 3):restricted.start()]
        if any(char in ReActAgent._NEGATION_BEFORE for char in window):
            return ""
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9_]*", text):
            if match.group(0).lower() in known:
                return known[match.group(0).lower()]
        return ""

    @staticmethod
    def _partial_success_response(
        successful_results: list[tuple[str, str]],
        *,
        failed_tool: str,
        failure_reason: str,
        failure_count: int,
        gated_results: list[tuple[str, str]] | None = None,
    ) -> str:
        if not successful_results:
            return ""
        retained_results = [
            (name, result)
            for name, result in successful_results
            # A read-only call is not a mutation worth reporting as retained, and
            # a confirmation gate wrote nothing at all. Filtering both here (not
            # only at the call site) keeps the message honest regardless of who
            # builds the list.
            if not ReActAgent._is_read_only_tool(name) and not ReActAgent._is_confirmation_gate(result)
        ]
        # Name the changes that were requested but not applied. This is appended
        # even when nothing was retained: the author must be told which of their
        # requests are still waiting, not left believing everything happened.
        gated = list(gated_results or [])
        gated_notice = ""
        if gated:
            gated_names = "、".join(dict.fromkeys(name for name, _ in gated))
            gated_notice = (
                f"\n\n尚未应用（等待你明确确认）：{gated_names}。"
                "确认后我会重试这些变更。"
            )
        if not retained_results:
            if not gated_notice:
                return ""
            return (
                f"本轮没有已保留的变更。之后的 {failed_tool} 连续失败 "
                f"{failure_count} 次，我已停止后续调用。最后原因：{failure_reason}"
            ) + gated_notice
        names = list(dict.fromkeys(name for name, _ in retained_results))
        details = [
            ReActAgent._summarize_retained_result(name, result)
            for name, result in retained_results[-4:]
        ]
        return (
            f"主操作 {'、'.join(names)} 已成功并保留。之后的 {failed_tool} 连续失败 "
            f"{failure_count} 次，我已停止后续调用。最后原因：{failure_reason}"
            "\n\n已保留的结果：\n"
            + "\n".join(details)
        ) + gated_notice

    @staticmethod
    def _is_read_only_tool(name: str) -> bool:
        return str(name or "").startswith(
            ("read_", "get_", "list_", "query_", "search_", "inspect_", "validate_", "diagnose_")
        )

    @staticmethod
    def _summarize_retained_result(name: str, result: str) -> str:
        try:
            payload = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return f"{name}: {str(result)[:1200]}"
        if not isinstance(payload, dict):
            return f"{name}: {str(result)[:1200]}"
        if name == "stage_outline_edits":
            revision = str(payload.get("draft_revision") or "")
            return (
                f"{name}: 已暂存至第 {int(payload.get('batch_count') or 1)} 批，"
                f"draft_revision={revision[:12] or '未知'}，"
                f"final_batch={str(bool(payload.get('final_batch'))).lower()}；"
                "正式大纲尚未写入。"
            )
        compact_keys = (
            "ok",
            "action",
            "message",
            "next_action",
            "source_id",
            "profile_id",
            "preview_id",
            "promoted",
            "applied",
            "chapter_id",
        )
        compact = {key: payload[key] for key in compact_keys if key in payload}
        rendered = json.dumps(compact or payload, ensure_ascii=False, default=str)
        return f"{name}: {rendered[:2000]}"

    def _register_tool_executors(self, executors: dict):
        """注册工具执行器

        用法:
            agent._register_tool_executors({
                'write_draft': lambda args: pipeline.write_draft(...),
                'audit_chapter': lambda args: pipeline.audit_chapter(...),
            })
        """
        for name, fn in executors.items():
            setattr(self, f"_tool_{name}", fn)


class SimpleResponse:
    """简单响应（用于不支持工具调用时）"""

    def __init__(self, content: str, tool_calls: list):
        self.content = content
        self.tool_calls = tool_calls


# === OpenWrite 内置工具 ===

OPENWRITE_TOOLS = [
    ToolDefinition(
        name="write_chapter",
        description="写一章草稿。根据当前大纲和上下文生成章节正文。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节 ID（如 ch_005）"},
                "guidance": {"type": "string", "description": "创作指导（可选，自然语言）"},
                "target_words": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "目标字数；省略时使用大纲或项目默认值",
                },
                "temperature": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 2,
                    "default": 0.7,
                    "description": "生成温度，默认 0.7",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="review_chapter",
        description="审查章节。检查逻辑、风格、AI痕迹等问题。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节 ID"},
                "strict": {"type": "boolean", "description": "严格模式"},
                "dimensions": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 37},
                    "description": "只审查指定维度；省略时审查全部 37 个维度",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="get_status",
        description="获取项目状态概览。",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="get_context",
        description=(
            "获取指定章节的写作上下文及发送前压缩报告。"
            "压缩报告包含消息预算、L1-L4 触发级别及 packet 文档裁剪记录。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节 ID"},
                "window_size": {"type": "integer", "description": "大纲窗口大小"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="inspect_agent_context",
        description=(
            "只读检查 canonical/Writer/Reviewer/Dante/Goethe 的首轮模型输入、"
            "字段完整性、来源 revision、工具表和压缩警告。默认仅返回消息元数据；"
            "需要审阅原文时设置 include_messages=true。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节 ID，默认 next"},
                "agent": {
                    "type": "string",
                    "enum": ["canonical", "writer", "reviewer", "dante", "goethe"],
                    "description": "待检查 Agent，默认 writer",
                },
                "instruction": {"type": "string", "description": "Dante/Goethe 用户指令"},
                "guidance": {"type": "string", "description": "Writer 临时写作要求"},
                "target_words": {"type": "integer", "description": "Writer 临时目标字数"},
                "include_messages": {
                    "type": "boolean",
                    "description": "是否返回完整首轮消息正文，默认 false",
                },
                "include_payload": {
                    "type": "boolean",
                    "description": "是否返回完整 Agent payload，默认 false",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="list_chapter_runs",
        description=(
            "只读列出章节运行清单，包含目标字数、模型路由、上下文/草稿/审稿 revision、"
            "阶段状态、usage 和错误码。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "可选章节 ID"},
                "statuses": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["running", "written", "reviewed", "failed"],
                    },
                    "description": "可选状态筛选",
                },
                "limit": {"type": "integer", "description": "返回数量，默认 20，最高 100"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="get_chapter_run_v2",
        description=(
            "读取 Chapter Run V2 的八阶段状态、revision、artifact、usage 和干预；"
            "action=list 时列出，action=get 时按 run_id 查看。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "get"]},
                "run_id": {"type": "string"},
                "chapter_id": {"type": "string"},
                "statuses": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
            },
        },
    ),
    ToolDefinition(
        name="record_chapter_intervention",
        description="在指定 run 记录创作方向干预；必须携带刚读取的 revision，不直接应用。",
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "revision": {"type": "string"},
                "scope": {
                    "type": "string",
                    "enum": ["project", "arc", "chapter", "asset"],
                },
                "risk": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "blocker"],
                },
                "request": {"type": "string"},
                "affected_items": {"type": "array", "items": {"type": "string"}},
                "rewrite_required": {"type": "boolean"},
            },
            "required": ["run_id", "revision", "request"],
        },
        required=["run_id", "revision", "request"],
    ),
    ToolDefinition(
        name="update_chapter_intervention",
        description=(
            "推进干预状态并检查 run revision；confirmed/applied 必须在用户明确确认后"
            "设置 confirm=true。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "revision": {"type": "string"},
                "intervention_id": {"type": "string"},
                "state": {"type": "string"},
                "facts_revision": {"type": "string"},
                "impact": {"type": "array", "items": {"type": "string"}},
                "proposal": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["run_id", "revision", "intervention_id", "state"],
        },
        required=["run_id", "revision", "intervention_id", "state"],
    ),
    ToolDefinition(
        name="cancel_chapter_run_v2",
        description="取消指定 Chapter Run V2；必须携带刚读取的 revision。",
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "revision": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["run_id", "revision"],
        },
        required=["run_id", "revision"],
    ),
    ToolDefinition(
        name="diagnose_runtime",
        description=(
            "只读汇总任务、章节运行、审稿、大纲、伏笔、上下文、时间线与 Skill 诊断；"
            "不返回完整正文或本地绝对路径。"
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="manage_rolling_plan",
        description=(
            "创建或读取 revision 绑定的滚动规划候选；stage 只暂存 Goethe 的完整 Markdown "
            "大纲提案，后续仍需独立确认才会更新 canonical 大纲。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "get", "stage"],
                },
                "candidate_id": {"type": "string"},
                "revision": {"type": "string"},
                "current_arc": {"type": "string"},
                "window_size": {"type": "integer"},
                "proposal": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["action"],
        },
        required=["action"],
    ),
    ToolDefinition(
        name="manage_narrative_forecast",
        description=(
            "Goethe 专属的非正史剧情多线推演。list 返回可选大纲章节；create 必须传入"
            "anchor_chapter_id，并固化围绕该章的正典上下文与推演 brief；"
            "同一轮根据 brief 生成 2–5 个相互隔离的分支，再用 stage 写入结构化结果；"
            "get/list 用于读取，select 只记录用户明确选择的分支，不修改大纲、正文或权威状态。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "get", "stage", "select"],
                },
                "forecast_id": {"type": "string"},
                "revision": {"type": "string"},
                "divergence": {
                    "type": "string",
                    "description": "需要比较的开放剧情决策或分歧点",
                },
                "anchor_chapter_id": {
                    "type": "string",
                    "description": "分歧发生的大纲章节 ID；create 时必填，未明确时先让用户选择",
                },
                "branch_count": {"type": "integer", "minimum": 2, "maximum": 5},
                "horizon": {"type": "integer", "minimum": 1, "maximum": 10},
                "branch_id": {"type": "string", "description": "用户明确选择的分支 ID"},
                "limit": {"type": "integer"},
                "branches": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "premise": {"type": "string"},
                            "beats": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "offset": {
                                            "type": "integer",
                                            "minimum": 1,
                                            "maximum": 10,
                                        },
                                        "chapter_id": {"type": "string"},
                                        "summary": {"type": "string"},
                                    },
                                    "required": ["offset", "summary"],
                                },
                            },
                            "character_decisions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "character": {"type": "string"},
                                        "decision": {"type": "string"},
                                    },
                                    "required": ["character", "decision"],
                                },
                            },
                            "projected_changes": {
                                "type": "object",
                                "properties": {
                                    "characters": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "relationships": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "world": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "foreshadowing": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": [
                                    "characters",
                                    "relationships",
                                    "world",
                                    "foreshadowing",
                                ],
                            },
                            "risks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "kind": {
                                            "type": "string",
                                            "enum": [
                                                "continuity",
                                                "causality",
                                                "character",
                                            ],
                                        },
                                        "description": {"type": "string"},
                                    },
                                    "required": ["kind", "description"],
                                },
                            },
                            "uncertainties": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "intent_alignment": {
                                "type": "object",
                                "properties": {
                                    "score": {
                                        "type": "integer",
                                        "minimum": 0,
                                        "maximum": 100,
                                    },
                                    "rationale": {"type": "string"},
                                },
                                "required": ["score", "rationale"],
                            },
                        },
                        "required": [
                            "title",
                            "premise",
                            "beats",
                            "character_decisions",
                            "projected_changes",
                            "risks",
                            "uncertainties",
                            "intent_alignment",
                        ],
                    },
                },
            },
            "required": ["action"],
        },
        required=["action"],
    ),
    ToolDefinition(
        name="manage_manuscript_versions",
        description=(
            "列出、读取或创建正文 checkpoint；restore 会先保存当前正文，且必须携带"
            "当前 revision、confirm=true 和用户当轮的明确恢复指令。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "checkpoint", "restore"],
                },
                "chapter_id": {"type": "string"},
                "version_id": {"type": "string"},
                "revision": {"type": "string"},
                "label": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["action", "chapter_id"],
        },
        required=["action", "chapter_id"],
    ),
    ToolDefinition(
        name="manage_annotations",
        description=(
            "列出、创建或完成正文批注。创建时必须携带来源 revision、原文 quote 与"
            "Python 字符位置；revision 优先使用 read_project_document 返回的 "
            "source_revision，兼容其 16 位 revision；正文变化后锚点会明确标为 "
            "relocated 或 detached。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "create", "resolve"]},
                "chapter_id": {"type": "string"},
                "revision": {"type": "string"},
                "quote": {"type": "string"},
                "start_hint": {"type": "integer"},
                "end_hint": {"type": "integer"},
                "note": {"type": "string"},
                "annotation_id": {"type": "string"},
            },
            "required": ["action", "chapter_id"],
        },
        required=["action", "chapter_id"],
    ),
    ToolDefinition(
        name="get_runtime_state",
        description=(
            "只读获取完整结构化 runtime state、状态 revision、来源章节、开放线索、"
            "人物/资源/关系/时间线和 proposed entities；旧 Markdown 仅返回清单与哈希。"
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="get_chapter_review",
        description=(
            "只读获取指定章节最近审稿结果、问题详情、分数、来源 revision，"
            "并判断正文变化后审稿是否 stale。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节 ID"},
            },
            "required": ["chapter_id"],
        },
        required=["chapter_id"],
    ),
    ToolDefinition(
        name="get_task_activity",
        description=(
            "只读列出持久化任务摘要；提供 task_id 时返回该任务快照和追加式事件。"
            "凭据字段始终脱敏。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "可选任务 ID"},
                "statuses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "列出任务时的可选状态筛选",
                },
                "limit": {"type": "integer", "description": "任务或事件数量，默认 20"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="get_goethe_handoff",
        description=(
            "只读获取最新 Goethe -> Dante 交接 manifest、Markdown、文件路径和 revision。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "max_chars": {"type": "integer", "description": "Markdown 最大字符数"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="query_library",
        description=(
            "按与 Studio 相同的资料分类列出作品核心、角色和设定；返回子分类、"
            "结构化编辑能力与源文件路径。适合先浏览资料目录，再按需读取原文。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["all", "core", "characters", "settings"],
                    "description": "资料范围，默认 all",
                },
                "category": {
                    "type": "string",
                    "description": "可选子分类 ID，可从首次查询结果的 categories 获取",
                },
                "query": {"type": "string", "description": "可选关键词"},
                "limit": {"type": "integer", "description": "返回数量，默认 80"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="search_project",
        description=(
            "使用 LightRAG 与精确文本搜索大纲、作品核心、角色、设定、"
            "连续性资料和正文；结果包含统一资料子分类与源文件行号。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "scope": {
                    "type": "string",
                    "enum": [
                        "all",
                        "outline",
                        "core",
                        "characters",
                        "settings",
                        "continuity",
                        "chapters",
                        "sources",
                    ],
                    "description": (
                        "范围：all/outline/core/characters/settings/continuity/chapters/sources；"
                        "旧 story/world/assets 调用仍由运行时兼容"
                    ),
                },
                "limit": {"type": "integer", "description": "返回数量，默认 20"},
            },
            "required": ["query"],
        },
        required=["query"],
    ),
    ToolDefinition(
        name="read_project_document",
        description=(
            "读取小说项目内的源资产或正文文档，返回短 revision、完整 source_revision 与内容。"
            "支持 src、data/manuscript、data/foreshadowing 下的文件。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对小说根目录路径，如 src/characters/hero.md",
                },
                "max_chars": {"type": "integer", "description": "最大返回字符数"},
            },
            "required": ["path"],
        },
        required=["path"],
    ),
    ToolDefinition(
        name="edit_project_document",
        description=(
            "安全修改小说文档：长范围优先使用唯一的 start_text/end_text/new_text，"
            "短句才使用精确 old_text/new_text。默认只预览 diff；"
            "预览需传 path/edits，并返回不可变 preview_token；"
            "用户明确确认后仅传 preview_token 并设置 confirm=true 才写入。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "read_project_document 返回的 path"},
                "revision": {
                    "type": "string",
                    "description": "兼容旧确认流程；新流程使用 preview_token",
                },
                "preview_token": {
                    "type": "string",
                    "description": "预览返回的一次性凭据；确认时原样传回",
                },
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {
                                "type": "string",
                                "description": "仅改单句或短段时使用的精确原文",
                            },
                            "start_text": {
                                "type": "string",
                                "description": "长范围替换的唯一开头锚点",
                            },
                            "end_text": {
                                "type": "string",
                                "description": "长范围替换的唯一结尾锚点",
                            },
                            "new_text": {"type": "string", "description": "替换后的内容"},
                            "replace_all": {
                                "type": "boolean",
                                "description": "是否替换所有匹配；默认 false",
                            },
                        },
                        "required": ["new_text"],
                    },
                },
                "confirm": {"type": "boolean", "description": "默认 false 只预览 diff"},
            },
        },
    ),
    ToolDefinition(
        name="list_chapters",
        description=(
            "列出所有章节及其小说项目相对路径。读取正文时必须把返回的 path 原样传给"
            " read_project_document，不要根据 chapter_id 猜测目录。"
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="create_outline",
        description="按系统提示中的大纲写入契约创建大纲；已有大纲应优先使用增量编辑工具。",
        parameters={
            "type": "object",
            "properties": {
                "outline_content": {"type": "string", "description": "大纲内容（Markdown）"},
            },
            "required": ["outline_content"],
        },
    ),
    ToolDefinition(
        name="get_outline_structure",
        description="读取与 Studio 同源的卷/幕/节/章树，并推荐下一章；只读，不修改大纲或正文。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {
                    "type": "string",
                    "description": "可选的指定章纲 ID；留空时推荐最早尚未生成正文的章节",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="edit_outline_structure",
        description=(
            "按 revision 增量编辑 Studio 同源的卷/幕/节/章树；支持重命名、"
            "修改节点内容、新增同级/下级和删除。修改内容只替换当前标题下、"
            "新增或补全的节点内容必须遵守系统提示中的大纲写入契约。"
            "子标题前的正文块。删除会让后续卷/幕/节/章连续补位并在 diff 中"
            "完整预览。默认只返回 "
            "diff，用户确认后设置 confirm=true 才写入；若补位会改变已有正文的章节号或 "
            "revision 陈旧则拒绝。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["rename", "update_summary", "add_child", "add_after", "delete"],
                    "description": (
                        "结构编辑动作；update_summary 修改节点内容，delete 会删除子树"
                        "并连续重编号后续同类节点"
                    ),
                },
                "revision": {
                    "type": "string",
                    "description": "get_outline_structure 返回的 revision",
                },
                "node_id": {"type": "string", "description": "目标节点 ID；根新增卷时可留空"},
                "kind": {
                    "type": "string",
                    "enum": ["volume", "act", "section", "chapter"],
                    "description": "新增节点层级",
                },
                "title": {"type": "string", "description": "新标题；删除时留空"},
                "summary": {
                    "type": "string",
                    "description": "update_summary 使用的新节点内容；不能包含 Markdown 标题",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "默认 false 只预览 diff；用户明确确认后才设为 true",
                },
            },
        },
        required=["operation", "revision"],
    ),
    ToolDefinition(
        name="create_character",
        description="创建角色；content 可传入完整的 TOML front matter + Markdown 角色文档。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "角色名"},
                "description": {"type": "string", "description": "角色描述"},
                "content": {
                    "type": "string",
                    "description": "可选的完整角色文档；提供时会保留并规范化其结构",
                },
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="get_truth_files",
        description=(
            "完整读取 runtime-delta-v1 的运行态投影：current_state、ledger、relationships，"
            "并返回后续增量更新所需的 revision。"
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="get_character_state",
        description=(
            "按人物名查询内联状态批注。当前写作章节由系统自动推断；当前状态会追溯"
            "全书，lookback 只限制返回的近期变化历史，不会截断仍然有效的旧状态。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "人物名"},
                "field": {
                    "type": "string",
                    "description": "可选状态维度，如位置、伤势、与某人的关系",
                },
                "lookback": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 50,
                    "description": "返回最近多少章的变化历史；默认 50",
                },
            },
            "required": ["name"],
        },
        required=["name"],
    ),
    ToolDefinition(
        name="update_truth_file",
        description=(
            "向一个真相文件追加本章新增事实，不覆盖整份文件。默认仅预览 diff；"
            "先用 get_truth_files 取得 source_revision，只有用户确认后才能设置 confirm=true 应用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "文件名（current_state/ledger/relationships）",
                },
                "content": {
                    "type": "string",
                    "description": "只含新增客观事实的追加内容，不得传入整份文件",
                },
                "chapter_id": {
                    "type": "string",
                    "description": "事实来源章节；省略时使用当前章节，无法推断时记为 manual",
                },
                "source_revision": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "get_truth_files 返回的 revision",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "是否应用；默认 false，仅预览 diff",
                },
            },
            "required": ["file_name", "content", "source_revision"],
        },
        required=["file_name", "content", "source_revision"],
    ),
    # 伏笔管理
    ToolDefinition(
        name="create_foreshadowing",
        description="创建伏笔节点。",
        parameters={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "伏笔ID（如 f001）"},
                "content": {"type": "string", "description": "伏笔内容描述"},
                "weight": {"type": "integer", "description": "权重 1-10，默认5"},
                "layer": {"type": "string", "description": "层级（主线/支线/彩蛋）"},
                "created_at": {"type": "string", "description": "埋设章节（如 ch_001）"},
                "target_chapter": {"type": "string", "description": "预期回收章节（如 ch_015）"},
            },
            "required": ["node_id", "content"],
        },
    ),
    ToolDefinition(
        name="list_foreshadowing",
        description="列出伏笔节点。可按状态/权重/层级过滤。",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "状态过滤（埋伏/待收/已收/废弃）"},
                "min_weight": {"type": "integer", "description": "最小权重过滤"},
                "layer": {"type": "string", "description": "层级过滤（主线/支线）"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="update_foreshadowing",
        description="更新伏笔状态。",
        parameters={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "伏笔ID"},
                "status": {"type": "string", "description": "新状态（埋伏/待收/已收/废弃）"},
            },
            "required": ["node_id", "status"],
        },
    ),
    ToolDefinition(
        name="validate_foreshadowing",
        description="验证伏笔DAG，检查环和引用错误。",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    # 状态验证
    ToolDefinition(
        name="validate_truth",
        description="验证真相文件与章节内容的一致性。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "要验证的章节ID（默认最新章节）"},
            },
            "required": [],
        },
    ),
    # 设定查询（工具名保留 world 以兼容既有调用）
    ToolDefinition(
        name="query_world",
        description=(
            "查询设定实体（兼容工具名）。不传 entity_id 时列出实体摘要；"
            "传入 entity_id 时返回该实体的完整描述、规则、特征、关系和扩展段落。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "实体ID（不填则列出所有）"},
                "type": {
                    "type": "string",
                    "description": "类型过滤（location/person/technique/item等）",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="get_world_relations",
        description=(
            "获取与 Studio 同源的关系图谱；包含 front matter、关联段落和人物关系段落。"
            "返回全部节点和关系，不静默截断；需要按名称、ID 或关系文字定位时，"
            "先读取完整图谱再在结果中搜索。"
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="search_relation_targets",
        description=(
            "搜索可连入关系图的人物、地点、组织、能力、物品或概念候选。"
            "适合把人物与出身地点、能力体系、阵营、物品等设定联系起来。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，如人物名、地点、能力"},
                "type": {"type": "string", "description": "可选类型过滤，如 人物/地点/能力"},
                "limit": {"type": "integer", "description": "返回数量，默认 20"},
            },
            "required": ["query"],
        },
        required=["query"],
    ),
    ToolDefinition(
        name="edit_world_relation",
        description=(
            "增量维护一个正式关系。默认仅预览 diff；只有用户确认后才能携带 "
            "base_revision 和 confirm=true 写入。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "关系源实体 ID 或名称"},
                "target_id": {"type": "string", "description": "关系目标实体 ID 或名称"},
                "description": {"type": "string", "description": "关系说明"},
                "action": {
                    "type": "string",
                    "enum": ["upsert", "remove"],
                    "description": "upsert（新增/更新）或 remove（删除）",
                },
                "base_revision": {
                    "type": "string",
                    "description": "预览返回的源文件 revision；确认写入时必填",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "默认 false 仅预览；用户明确确认后才设为 true",
                },
            },
            "required": ["source_id", "target_id"],
        },
        required=["source_id", "target_id"],
    ),
    ToolDefinition(
        name="edit_world_relations",
        description=(
            "批量新增、更新或删除正式关系。默认只预览所有源文件 diff；"
            "预览会返回不可变 preview_token，用户确认后仅传该 token 并设置 confirm=true 才写入。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_id": {
                                "type": "string",
                                "description": "源实体正式 ID；使用查询结果，不要凭名称转写",
                            },
                            "target_id": {
                                "type": "string",
                                "description": "目标实体正式 ID；使用查询结果，不要凭名称转写",
                            },
                            "description": {"type": "string", "description": "关系说明"},
                            "action": {
                                "type": "string",
                                "enum": ["upsert", "remove"],
                                "description": "默认 upsert；删除用 remove",
                            },
                            "base_revision": {
                                "type": "string",
                                "description": "可选；预览返回的源文件 revision",
                            },
                        },
                        "required": ["source_id", "target_id"],
                    },
                },
                "base_revisions": {
                    "type": "object",
                    "description": "兼容旧调用；新确认流程使用 preview_token",
                },
                "preview_token": {
                    "type": "string",
                    "description": "预览返回的不可变凭据；确认时与 confirm=true 一起传入",
                },
                "preview_tokens": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "同一轮产生多批预览时的不可变凭据列表",
                },
                "confirm": {"type": "boolean", "description": "默认 false 只预览 diff"},
            },
            "required": [],
        },
        required=[],
    ),
    # 对话质量
    ToolDefinition(
        name="extract_dialogue_fingerprint",
        description="提取角色对话风格指纹，分析口头禅、用词习惯等。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节ID（默认最新）"},
                "character_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要分析的角色名列表",
                },
            },
            "required": [],
        },
    ),
    # 后置验证
    ToolDefinition(
        name="validate_post_write",
        description="零成本规则检测，检查禁止句式、AI味、敏感词等。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节ID（默认最新）"},
            },
            "required": [],
        },
    ),
    # 工作流
    ToolDefinition(
        name="get_workflow_status",
        description="获取工作流状态，查看写作流程进度。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节ID（不填则列出所有）"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="start_workflow",
        description="为指定章节启动写作工作流。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节ID"},
            },
            "required": ["chapter_id"],
        },
    ),
    ToolDefinition(
        name="advance_workflow",
        description="推进工作流到下一阶段。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节ID"},
                "stage_name": {"type": "string", "description": "目标阶段（可选）"},
            },
            "required": ["chapter_id"],
        },
    ),
    # 文本处理
    ToolDefinition(
        name="chunk_text",
        description="将大文本文件按章节边界切割为chunk。",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "chunk_size": {"type": "integer", "description": "chunk大小（默认30000）"},
            },
            "required": ["file_path"],
        },
    ),
    ToolDefinition(
        name="compress_section",
        description="压缩节/篇的章节摘要。",
        parameters={
            "type": "object",
            "properties": {
                "arc_id": {"type": "string", "description": "篇ID"},
                "section_id": {"type": "string", "description": "节ID（不填则压缩整篇）"},
            },
            "required": [],
        },
    ),
]


OPENWRITE_SYSTEM_PROMPT = f"""你是 OpenWrite 小说创作引擎的 Agent。

你的职责是帮用户完成小说创作任务，包括：
- 写章节、审查章节
- 管理作品核心、角色、设定与连续性资料
- 跟踪伏笔和真相文件
- 回答创作相关问题

## 可用工具

| 工具 | 作用 |
|------|------|
| write_chapter | 写一章草稿 |
| review_chapter | 审查章节 |
| get_status | 查看项目状态 |
| get_context | 获取写作上下文 |
| inspect_agent_context | 审计指定 Agent 的首轮模型输入 |
| list_chapter_runs | 查看章节运行清单与阶段 usage |
| get_runtime_state | 查看规范结构化运行态 |
| get_chapter_review | 查看审稿结果并判断是否过期 |
| get_task_activity | 查看任务快照和事件 |
| get_goethe_handoff | 查看 Goethe 到 Dante 的交接产物 |
| query_library | 按作品核心、角色、设定浏览资料目录 |
| search_project | 搜索作品资料 |
| read_project_document | 读取作品资料文档 |
| edit_project_document | 预览或确认修改作品资料文档 |
| list_chapters | 列出章节 |
| create_outline | 仅在不存在大纲时创建符合四级契约的首版大纲 |
| get_outline_structure | 读取卷/幕/节/章树并推荐下一章 |
| edit_outline_structure | 按 revision 增量改名、增删卷幕节章 |
| create_character | 创建角色 |
| get_truth_files | 完整读取真相文件及 runtime revision |
| get_character_state | 按人物名查询当前状态和近期变化，章节由系统推断 |
| update_truth_file | 按 revision 预览或确认追加运行态事实 |
| create_foreshadowing | 创建伏笔 |
| list_foreshadowing | 列出伏笔 |
| update_foreshadowing | 更新伏笔状态 |
| validate_foreshadowing | 验证伏笔DAG |
| query_world | 列出设定摘要或读取单个设定的完整详情 |
| get_world_relations | 获取完整关系图谱 |
| search_relation_targets | 搜索关系图候选节点 |
| edit_world_relation | 预览或确认一个增量关系修改 |
| edit_world_relations | 批量预览或确认关系修改 |
| validate_truth | 验证真相文件一致性 |
| extract_dialogue_fingerprint | 提取对话风格指纹 |
| validate_post_write | 后置规则验证 |
| get_workflow_status | 查看工作流进度 |
| start_workflow | 启动工作流 |
| advance_workflow | 推进工作流 |
| chunk_text | 切割大文本 |
| compress_section | 压缩摘要 |

## 工作流程

1. 用户给出指令后，先了解当前状态
2. 根据需要调用工具
3. 向用户汇报进展

模型选择和凭据由用户通过 Studio“模型设置”或启动环境配置；OpenAI / Anthropic
在该页面表示接口格式，Base URL 与模型名由用户填写。Agent 不得索取、读取、
回显或保存 API Key；ReAct 工具层不提供模型凭据操作。
面向用户的回复可使用 CommonMark 标题、列表、引用、链接和代码块；Studio 会安全渲染。
4. 直到任务完成

## 规则

- 每完成一步，简要汇报
- 如果缺少必要信息，先询问用户
- 遵循项目的大纲和设定
- 修改已有大纲树时先读取 revision，并以 edit_outline_structure(confirm=false)
  预览 diff；只有用户明确确认后才以相同 revision 和 confirm=true 写入
- 修改人物、故事、世界实体、正文等文档时先 read_project_document，再
  edit_project_document(confirm=false) 预览 diff；长范围使用唯一的 start_text/end_text，
  短句才使用 old_text；只有用户明确确认后才仅使用预览返回的
  preview_token 和 confirm=true 写入，不得重新生成 path/edits
- 连接人物、出身地点、能力设定、组织或物品时先 search_relation_targets /
  get_world_relations 定位候选，再 edit_world_relations(confirm=false) 预览 diff；
  relations 使用查询返回的正式实体 ID；只有用户明确确认后才使用预览返回的
  preview_token/preview_tokens 和 confirm=true 写入，不得重新生成 relations
- 维护运行态真相时先 get_truth_files 读取完整投影和 revision；update_truth_file 的 content
  只能包含新增客观事实，先 confirm=false 预览追加 diff，只有用户明确确认后才使用相同
  source_revision 和 confirm=true 写入；禁止整份覆盖 current_state、ledger 或 relationships

{OUTLINE_MARKDOWN_CONTRACT}

{CHARACTER_MARKDOWN_CONTRACT}
"""
