"""Render author-facing context reference from the pinned Core without importing it."""

import argparse
import ast
import json
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--core", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((args.plugin / "release/runtime-manifest.json").read_text(encoding="utf-8"))

    def read(name):
        if args.core:
            return (args.core / name).read_text(encoding="utf-8")
        with zipfile.ZipFile(args.plugin / "release" / manifest["wheel"]["file"]) as wheel:
            return wheel.read(name).decode("utf-8")

    def constant(filename, name):
        for node in ast.walk(ast.parse(read(filename))):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                return ast.literal_eval(node.value)
        raise ValueError(f"Missing source constant: {filename}:{name}")

    sections = constant("tools/context_manifest.py", "SECTION_SOURCES")
    protection = constant("tools/context_protection.py", "PROTECTION_REASONS")
    shares = constant("tools/chapter_assembler.py", "shares")
    budgets = {
        "historical_arc_summaries": "historical_outline", "current_arc_sections": "current_outline",
        "previous_chapter_content": "previous_chapter", "protagonist_state": "protagonist_state",
        "character_documents": "characters", "concept_documents": "settings",
        "setting_documents": "settings", "style_documents": "style",
    }
    policies = {
        "author_intent": "作者意图；完整保留硬约束",
        "creative_focus": "创作罗盘；完整保留硬约束",
        "story_background": "兼容别名；有 core_documents 时 manifest 隐藏重复项",
        "core_documents": "故事背景与基础正典；完整保留",
        "historical_arc_summaries": "已结束篇摘要；按摘要文档分配，截取开头",
        "current_arc_sections": "当前篇各节摘要；按摘要文档分配，截取开头",
        "chapter_requirements": "当前章目标、节拍、悬念、章节承诺 promise/payoff_of 与登记的扩展字段；完整保留",
        "scene_context": "仅当前正文版本匹配的场景结构；过期时排除并诊断",
        "previous_chapter_content": "默认上一章全文；可选 tail/有效 summary；预算压力下保留结尾",
        "character_states": "ContextBuilder 提取本章涉及人物的行内状态；受该装配器预算约束",
        "semantic_references": "ContextBuilder 语义检索的远距离正文/资料；需可用的独立 Embedding 档案；受检索与装配预算约束",
        "protagonist_state": "本章涉及人物的当前状态；可选区按配额截取",
        "current_state": "兼容连续性字段；有 continuity_documents 时隐藏重复项",
        "ledger": "兼容粒子台账；有 continuity_documents 时隐藏重复项",
        "relationships": "兼容人物关系；有 continuity_documents 时隐藏重复项",
        "character_documents": "只选本章涉及人物；按文档容量分配、保留开头",
        "concept_documents": "setting_documents 的兼容别名；不重复计算",
        "setting_documents": "世界规则/术语/时间线 + 本章涉及实体 + 全部 YAML 进阶体系；按文档容量分配、保留开头",
        "continuity_documents": "运行态正典 current_state/ledger/relationships；完整保留",
        "style_documents": "作品风格与 craft；优先 work.composed/manifest/fingerprint/craft，再按文档容量分配",
    }
    if set(policies) != set(sections):
        raise ValueError("Context slots changed; update the author-facing selection policies")
    lines = [
        "# 写手上下文槽位参考", "",
        f"本表对应候选 Core {manifest['core_version']}，来源提交 `{manifest['sources']['core']['commit']}`。由捆绑 wheel 的 SECTION_SOURCES、保护规则和 shares 生成，共 {len(sections)} 个来源条目，包含兼容别名；不是每次写作都会装满这些槽位。", "",
        "## 看本章实际用了什么", "",
        "先用 `novel_context_preview {\"chapter\":\"ch_001\",\"include_agent_payload\":true}`；要看所选 writer 档案、guidance 与 target_words 的最终输入，使用 `novel_write_chapter {\"chapter_id\":\"ch_001\",\"dry_run\":true}`。这些预览不发起写作模型请求。", "",
        "`context_manifest.items` 提供实际槽位、来源指纹、字符数、估算 token、保护/压缩状态；`documents` 列出 character/setting/style 每份文档原始与装配字符数、compressed/excluded。`missing_items` 与 `excluded_items` 解释缺失/排除。来源目录是候选来源，不能把目录中所有文件都当成实际已送给模型的文档。", "",
        "## 预算怎样分配", "",
        "没有固定的每槽字符上限。先按模型上下文窗、输出预留和安全余量计算输入预算；未超预算保持原文。受保护硬约束先占预算，装不下就明确失败；不会静默删掉它们。其余容量换算为字符后，按以下 shares 归一化分配（这不是整窗百分比）：", "",
        "| 配额组 | 默认权重 |", "| --- | --- |",
        *[f"| {name} | {value:g} |" for name, value in shares.items()], "",
        "style 权重可用 novel_config.yaml 的 context_style_share 调整，限制在 0.01–0.5。风格容量还会优先保留最多 4000 字符的已有风格（不超过可选总容量的一半），其余组随剩余容量缩放。最终仍检查 token 总量。", "",
        "多文档按各自容量占比分配；同优先级按名称排序，剩余字符依次补给。设置/角色通常截取开头，上一章正文保留结尾；配额为零的文档排除。风格优先顺序见下表。目录表里的 level 是来源层级，不是逐层删除顺序。", "",
        "## 来源、选择和消费者", "",
        "| 槽位 | 层级 | 作品根目录内来源 | 预算 | 选择/压缩规则 | 谁读 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, (level, sources) in sections.items():
        budget = "受保护，不截断" if name in protection else budgets.get(name, "由 ContextBuilder/检索预算决定")
        reader = "ContextBuilder → writer" if name in {"character_states", "semantic_references", "scene_context"} else "章节装配/兼容输入 → writer"
        lines.append(f"| `{name}` | {level} | {'、'.join('`'+s+'`' for s in sources)} | {budget} | {policies[name]} | {reader}；manifest 展示 |")
    section_target = constant("tools/progressive_compressor.py", "SECTION_COMPRESS_TARGET")
    arc_target = constant("tools/progressive_compressor.py", "ARC_COMPRESS_TARGET")
    lines += ["", "## 渐进摘要与进阶体系", "",
        f"`progressive_compressor` 是较早的分节/分篇摘要组件：节摘要目标约 {section_target} 字符，篇摘要目标约 {arc_target} 字符，优先首尾、关键词和事件，降低对话优先级并在句子边界截断。它不是上表 ChapterAssemblerV2 的逐槽预算器；不要把旧组件的目标长度当成当前每槽固定预算。", "",
        "作者在资产页创建的进阶体系保存于 `src/progression/<id>.yaml`。本候选实际加载 .yaml/.yml 为 `setting_documents[progression.<id>]`，经过同一设置预算进入 writer，并出现在逐文档用量里；即使没有 world/ 目录也可加载。文件存在不保证预算不足时完整送达，写前应核对预览。", "",
        "工具参数与修改方式见 [工具参考](TOOLS.md)。", "",
    ]
    content = "\n".join(lines)
    output = args.plugin / "docs/CONTEXT_SLOTS.md"
    if args.check:
        if output.read_text(encoding="utf-8") != content:
            raise ValueError("docs/CONTEXT_SLOTS.md is stale; run python scripts/gen-context-slots.py")
        print(f"Context reference matches {len(sections)} source slots")
    else:
        output.write_text(content, encoding="utf-8")
        print(f"Generated {output}")


if __name__ == "__main__":
    main()
