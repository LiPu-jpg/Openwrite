from __future__ import annotations

from pathlib import Path

from tools.language import load_language_prompt
from tools.agent.writer import WriterAgent


def test_vi_language_pack_loads_vietnamese_prompt(tmp_path: Path) -> None:
    prompt = load_language_prompt("vi", "writer", workspace=tmp_path)

    assert "tiếng Việt" in prompt
    assert "tiếng Trung" in prompt


def test_hosted_writer_prompt_does_not_use_chinese_role_prompt(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENWRITE_LANGUAGE", "vi")
    writer = object.__new__(WriterAgent)
    writer.ctx = type("Ctx", (), {"project_root": str(tmp_path)})()

    prompt = writer._build_creative_system_prompt({})

    assert "tiểu thuyết tiếng Việt" in prompt
    assert "你是一位" not in prompt
    assert "中文网络小说惯例" not in prompt
