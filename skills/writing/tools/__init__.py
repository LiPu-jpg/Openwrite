"""Writing Skill Tools - 写作工具集。

提供章节写作所需的核心工具：
- BeatGenerator: 节拍生成器
- DraftGenerator: 草稿生成器
- load_beat_generator: 加载节拍生成器
- load_draft_generator: 加载草稿生成器

使用方式：
    from skills.writing.tools import BeatGenerator, DraftGenerator

    # 使用默认配置
    beat_gen = BeatGenerator()
    beats = beat_gen.generate_beats("ch_001", context)

    # 加载自定义配置
    from skills.writing.tools import load_draft_generator
    draft_gen = load_draft_generator(
        templates_path="skills/writing/templates/beat_templates.yaml",
        markers_path="skills/writing/templates/section_markers.yaml",
    )
"""

from skills.writing.tools.beat_generator import (
    BeatGenerator,
    BeatTemplates,
    SectionMarkers,
    load_beat_generator,
)
from skills.writing.tools.draft_generator import (
    DraftGenerator,
    DraftOutput,
    load_draft_generator,
)

__all__ = [
    # Beat Generator
    "BeatGenerator",
    "BeatTemplates",
    "SectionMarkers",
    "load_beat_generator",
    # Draft Generator
    "DraftGenerator",
    "DraftOutput",
    "load_draft_generator",
]
