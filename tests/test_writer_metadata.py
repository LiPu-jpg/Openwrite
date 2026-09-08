"""Deterministic writer/reader contracts; no model or project-registry access."""

import asyncio
from types import SimpleNamespace

import pytest

from tools.agent.writer import WriterAgent
from tools.character_state_index import (
    mask_character_state_annotations,
    normalize_character_state_annotation_fences,
    parse_character_state_annotations,
    parse_relation_annotations,
    strip_character_state_annotations,
)
from tools.llm.response import ProviderResponseError
from tools.novel_workspace import count_writing_units

STATE = "//**林霁[位置]：旧港 -> 灯塔**"
RELATION = "//**林霁~>周舟:共同调查灯塔**"


@pytest.mark.parametrize("info", ["", "text", "plaintext"])
@pytest.mark.parametrize("marker", ["```", "~~~"])
def test_writer_unwraps_only_metadata_fences_before_indexing(info, marker):
    body = (
        "雨落在旧港。\n\n"
        f"{marker}{info}\n{STATE}\n\n"
        "//**林霁[伤势]：轻伤 -> 恢复**\n"
        "//**林霁[立场]：犹疑 -> 决意**\n"
        f"{RELATION}\n{marker}"
    )
    parsed = WriterAgent.__new__(WriterAgent)._parse_creative_output(
        "# 第四章：灯塔\n\n" + body, chapter_number=4, usage={}
    )
    records, diagnostics = parse_character_state_annotations(
        parsed["content"], source_path="ch_004.md", source_kind="actual",
        default_chapter_id="ch_004",
    )
    relations, relation_diagnostics = parse_relation_annotations(
        parsed["content"], source_path="ch_004.md"
    )

    assert diagnostics == relation_diagnostics == []
    assert [record.field for record in records] == ["位置", "伤势", "立场"]
    assert all(record.chapter_id == "ch_004" for record in records)
    assert len(relations) == 1
    assert marker not in parsed["content"]
    assert parsed["word_count"] == count_writing_units(body) == 5
    assert STATE in parsed["content"] and RELATION in parsed["content"]


@pytest.mark.parametrize(
    "block",
    [
        f"```javascript\n{STATE}\n```",
        f"```python\n{STATE}\n```",
        f"~~~cpp\n{STATE}\n~~~",
        f"```text\n{STATE}\n这行是正文。\n```",
        f"```text\n{STATE}\nconst answer = 42;\n```",
        "```text\n//**林霁[位置]：旧港 -> **\n```",
        "```text\n//**林霁[ ]：旧港 -> 灯塔**\n```",
        "```text\n//**林霁[位置]@ch_000：旧港 -> 灯塔**\n```",
        "```text\n//**林霁[位置]：旧港**\n```",
        f"```text\n{STATE}",
        f"````text\n{STATE}\n```",
        f"```text\n{STATE}\n~~~",
        f"````text\n```text\n{STATE}\n```\n````",
        "```text\n\n```",
        "```python\nprint('Hello 世界')\n```",
    ],
)
def test_normal_mixed_invalid_and_unclosed_code_blocks_remain_intact(block):
    text = "前文。\n\n" + block + "\n"

    assert normalize_character_state_annotation_fences(text) == text
    assert strip_character_state_annotations(text) == text
    assert mask_character_state_annotations(text) == text


def test_reader_hides_entire_metadata_fence_without_leaking_language_label():
    text = f"前文。\r\n```text\r\n{STATE}\r\n````\r\n后文。\r\n"

    assert normalize_character_state_annotation_fences(text) == (
        f"前文。\r\n{STATE}\r\n后文。\r\n"
    )
    assert strip_character_state_annotations(text) == "前文。\r\n后文。\r\n"
    assert mask_character_state_annotations(text) == "前文。\r\n\r\n\r\n\r\n后文。\r\n"
    assert count_writing_units(text) == 4


@pytest.mark.parametrize("indent", ["    ", "\t", "  \t"])
@pytest.mark.parametrize("prefix", ["", "普通正文。\n\n"])
@pytest.mark.parametrize("wrapper", ["none", "closed", "unclosed"])
def test_reader_preserves_indented_code_at_start_and_after_prose(indent, prefix, wrapper):
    code = f"{indent}{STATE}\n"
    if wrapper != "none":
        code = f"{indent}```python\n" + code
    if wrapper == "closed":
        code += f"{indent}```\n"
    text = prefix + code

    assert normalize_character_state_annotation_fences(text) == text
    assert strip_character_state_annotations(text) == text
    assert mask_character_state_annotations(text) == text


@pytest.mark.parametrize("indent", ["    ", "\t"])
def test_pure_metadata_in_real_text_fence_remains_inline_after_unwrapping(indent):
    text = f"正文。\n```text\n{indent}{STATE}\n```\n"
    normalized = normalize_character_state_annotation_fences(text)

    assert normalized == f"正文。\n{STATE}\n"
    assert count_writing_units(text) == count_writing_units(normalized) == 2


@pytest.mark.parametrize("body", ["雨落在旧港。", "雨落下。Hello, world."])
def test_writer_keeps_ordinary_prose_and_uses_reader_facing_length(body):
    parsed = WriterAgent.__new__(WriterAgent)._parse_creative_output(
        "# 第四章：灯塔\n\n" + body, chapter_number=4, usage={}, target_words=5
    )

    assert parsed["content"] == body
    assert parsed["word_count"] == count_writing_units(body) == 5


def test_metadata_cannot_satisfy_writer_minimum_length():
    body = "文" * 79 + f"\n```text\n{STATE}\n```"

    with pytest.raises(ProviderResponseError) as raised:
        WriterAgent.__new__(WriterAgent)._parse_creative_output(
            "# 第一章：标题也不是正文\n\n" + body,
            chapter_number=1, usage={}, target_words=100,
        )

    assert raised.value.code == "CHAPTER_LENGTH_OUT_OF_RANGE"
    assert "79" in str(raised.value)


def test_writer_length_retry_uses_same_reader_count_as_final_parse():
    writer = WriterAgent.__new__(WriterAgent)
    responses = iter([
        SimpleNamespace(
            content="# 第一章：标题也不是正文\n\n" + "文" * 79
            + f"\n```text\n{STATE}\n```",
            usage={"total_tokens": 10},
        ),
        SimpleNamespace(content="文" * 100 + f"\n{STATE}", usage={"total_tokens": 20}),
    ])
    calls = []

    def chat(*, messages, **kwargs):
        calls.append(messages)
        return next(responses)

    writer.chat = chat
    result = asyncio.run(writer._creative_write({}, 1, 0.7, 100))

    assert len(calls) == 2
    assert "79 字（不含标题和内联批注）" in calls[1][-1].content
    assert result["word_count"] == 100
    assert result["usage"]["total_tokens"] == 30


def test_incomplete_unfenced_annotation_remains_reader_visible():
    text = "前文。\n//**林霁[位置]：旧港 -> **\n"

    assert strip_character_state_annotations(text) == text
    assert mask_character_state_annotations(text) == text
