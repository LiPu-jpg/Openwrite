"""Editable publication metadata, separate from project identity and paths."""

import re


def normalize_project_metadata(payload: dict) -> dict[str, str]:
    result = {}
    for key, limit in (("title", 120), ("author", 120), ("language", 35)):
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, str):
            raise ValueError(f"{key} 必须是文本")
        value = value.strip()
        if len(value) > limit or any(ord(char) < 32 for char in value):
            raise ValueError(f"{key} 不能包含控制字符，且不能超过 {limit} 字")
        if key == "language" and value and not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
            raise ValueError("语言请使用 zh-CN、en 等语言标签")
        result[key] = value
    return result
