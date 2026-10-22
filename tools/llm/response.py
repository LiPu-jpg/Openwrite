"""Provider-neutral response classification and structured-output parsing."""

from __future__ import annotations

import json
import re
from typing import Any

import yaml


class ProviderResponseError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.details = details or {}
        super().__init__(message)


def redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    patterns = (
        r"\bsk-[A-Za-z0-9_-]{8,}\b",
        r"(?i)\bauthorization\s*[:=]\s*(?:bearer\s+)?[^\s,;\"']+",
        r"(?i)(api[_-]?key|authorization|bearer)(\s*[:=]\s*|\s+)[^\s,;]+",
        r"(?i)([?&](?:api[_-]?key|access_token|key)=)[^&\s]+",
    )
    for pattern in patterns:
        text = re.sub(pattern, "[redacted]", text)
    return text


def classify_response(
    content: Any,
    *,
    finish_reason: str = "",
    reasoning: Any = "",
    require_content: bool = True,
) -> str:
    text = str(content or "").strip()
    finish = str(finish_reason or "").lower()
    if finish in {"length", "max_tokens", "incomplete"}:
        error = ProviderResponseError(
            "MODEL_OUTPUT_TRUNCATED", "Model output was truncated or the stream was interrupted"
        )
        error.partial_content = str(content or "")
        raise error
    if not text and str(reasoning or "").strip():
        raise ProviderResponseError("MODEL_REASONING_ONLY", "模型只返回了推理内容，没有最终答案")
    if require_content and not text:
        raise ProviderResponseError("MODEL_EMPTY_RESPONSE", "模型返回了空内容")
    return "content" if text else "empty_allowed"


def load_tool_arguments(
    call: dict[str, Any],
    *,
    index: int = 0,
) -> dict[str, Any]:
    arguments = call.get("arguments", {})
    if isinstance(arguments, dict):
        return arguments
    raw = str(arguments or "{}")
    tool_name = str(call.get("name") or "未知工具")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        hint = _json_error_hint(exc)
        start = max(0, exc.pos - 80)
        end = min(len(raw), exc.pos + 80)
        context = redact_sensitive_text(raw[start:end]).replace("\n", "\\n")
        likely_truncated = (
            exc.msg == "Unterminated string starting at"
            or raw.rstrip().endswith(("{", "[", ",", ":"))
            or not raw.rstrip().endswith("}")
        )
        raise ProviderResponseError(
            "MALFORMED_TOOL_ARGUMENTS",
            (
                f"工具 {tool_name} 的参数不是有效 JSON：第 {exc.lineno} 行"
                f"第 {exc.colno} 列，{hint}"
            ),
            details={
                "tool_index": index + 1,
                "tool_name": tool_name,
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
                "parser_message": exc.msg,
                "hint": hint,
                "likely_truncated": likely_truncated,
                "context": context,
            },
        ) from exc
    if not isinstance(parsed, dict):
        raise ProviderResponseError(
            "MALFORMED_TOOL_ARGUMENTS",
            f"工具 {tool_name} 的参数必须是 JSON 对象，不能是 {type(parsed).__name__}",
            details={
                "tool_index": index + 1,
                "tool_name": tool_name,
                "hint": "最外层必须使用 { ... }，并以字段名传递参数",
                "likely_truncated": False,
            },
        )
    return parsed


def validate_tool_arguments(tool_calls: list[dict[str, Any]]) -> None:
    for index, call in enumerate(tool_calls):
        load_tool_arguments(call, index=index)


def _json_error_hint(exc: json.JSONDecodeError) -> str:
    hints = {
        "Unterminated string starting at": "字符串没有闭合，可能是输出被截断或引号未转义",
        "Expecting ',' delimiter": "字段或数组项之间缺少逗号，也可能是正文中的引号未转义",
        "Expecting property name enclosed in double quotes": "对象字段名必须使用英文双引号",
        "Expecting value": "字段、数组项或冒号后缺少值",
        "Extra data": "JSON 对象结束后还有多余内容",
    }
    return hints.get(exc.msg, f"JSON 解析器报告：{exc.msg}")


def load_structured_mapping(content: Any, *, required_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        raise ProviderResponseError("MODEL_EMPTY_RESPONSE", "模型返回了空内容")
    candidates = [
        match.group(1).strip()
        for match in re.finditer(
            r"```(?:yaml|yml|json)?\s*\r?\n(.*?)\r?\n```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
    ]
    candidates.append(text)
    if required_keys:
        keys = "|".join(re.escape(key) for key in required_keys)
        block = re.search(rf"(?ms)^(?:{keys})\s*:\s*\n?.*$", text)
        if block:
            candidates.append(block.group(0).strip())
    for candidate in candidates:
        try:
            payload = yaml.safe_load(candidate) or {}
        except yaml.YAMLError:
            continue
        if isinstance(payload, dict) and (
            not required_keys or any(key in payload for key in required_keys)
        ):
            return payload
    raise ProviderResponseError("MALFORMED_STRUCTURED_OUTPUT", "模型返回的结构化内容无法解析")
