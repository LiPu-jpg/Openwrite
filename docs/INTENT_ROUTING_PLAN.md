# Director as Unified Assistant — Implementation Plan v3

## Overview

Transform Director into a **unified conversational assistant** with **Workflow-aware** operation. Director not only coordinates tools but also recognizes and guides users through predefined **Workflows** (multi-step processes like outline creation, style selection, chapter writing).

## Key Concepts

### Workflows vs. Intents vs. Tools

| Concept | Scope | Example |
|---------|-------|---------|
| **Intent** | Single user request classification | "我想修改大纲" → OUTLINE_ASSIST |
| **Tool** | Atomic operation | `outline_assist`, `lore_query` |
| **Workflow** | Multi-step process with phases | "大纲创建流程" → Master→Arc→Section→Chapter |

### Workflow Lifecycle

```
1. detect_workflow() → Identify which workflow user wants
2. get_current_phase() → Determine current step in workflow
3. execute_phase_tools() → Run tools for current phase
4. advance_phase() → Move to next phase when conditions met
5. is_workflow_complete() → Check if all phases done
```

---

## 1. Workflow Data Models

### 1.1 Workflow Definition Models (`tools/models/workflow.py`)

```python
"""Workflow definition models for multi-step processes."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class PhaseTransitionType(str, Enum):
    """Phase transition types."""
    AUTO = "auto"          # Automatically advance when conditions met
    MANUAL = "manual"      # User must confirm to advance
    CONDITIONAL = "conditional"  # Based on condition evaluation


class PhaseCondition(BaseModel):
    """Condition for phase transitions."""
    
    type: str = Field(..., description="Condition type: has_data, tool_success, user_confirm, custom")
    key: str = Field(default="", description="Data key to check")
    value: Any = Field(default=None, description="Expected value")
    expression: str = Field(default="", description="Custom expression for evaluation")


class WorkflowPhase(BaseModel):
    """A single phase within a workflow."""
    
    phase_id: str = Field(..., description="Unique phase identifier")
    name: str = Field(..., description="Display name")
    description: str = Field(default="", description="Phase description")
    order: int = Field(default=0, description="Phase order in workflow")
    
    # Tools available in this phase
    tools: List[str] = Field(default_factory=list, description="Tools available in this phase")
    primary_tool: str = Field(default="", description="Main tool for this phase")
    
    # Context requirements
    context_keys: List[str] = Field(default_factory=list, description="Context keys to load")
    
    # User interaction
    user_prompts: List[str] = Field(default_factory=list, description="Questions to ask user")
    help_text: str = Field(default="", description="Help text for this phase")
    
    # Phase completion
    completion_conditions: List[PhaseCondition] = Field(
        default_factory=list, 
        description="Conditions to complete this phase"
    )
    
    # Transition
    transition_type: PhaseTransitionType = Field(
        default=PhaseTransitionType.MANUAL,
        description="How to transition to next phase"
    )
    next_phase: str = Field(default="", description="Next phase ID (empty for last phase)")


class WorkflowDefinition(BaseModel):
    """Complete workflow definition."""
    
    workflow_id: str = Field(..., description="Unique workflow identifier")
    name: str = Field(..., description="Display name")
    description: str = Field(default="", description="Workflow description")
    category: str = Field(default="general", description="Workflow category")
    version: str = Field(default="1.0", description="Workflow version")
    
    # Triggering
    trigger_intents: List[str] = Field(
        default_factory=list,
        description="Intents that can trigger this workflow"
    )
    trigger_keywords: List[str] = Field(
        default_factory=list,
        description="Keywords that suggest this workflow"
    )
    trigger_conditions: List[PhaseCondition] = Field(
        default_factory=list,
        description="Additional conditions to start workflow"
    )
    
    # Phases
    phases: List[WorkflowPhase] = Field(default_factory=list, description="Ordered phases")
    entry_phase: str = Field(default="", description="First phase ID")
    exit_phase: str = Field(default="", description="Final phase ID")
    
    # Context
    required_context: List[str] = Field(
        default_factory=list,
        description="Context keys required before starting"
    )
    produced_context: List[str] = Field(
        default_factory=list,
        description="Context keys produced by this workflow"
    )
    
    # Metadata
    estimated_steps: int = Field(default=5, description="Estimated number of interactions")
    is_destructive: bool = Field(default=False, description="Whether workflow makes destructive changes")


class WorkflowState(BaseModel):
    """Runtime state of a workflow execution."""
    
    workflow_id: str = Field(..., description="Workflow being executed")
    session_id: str = Field(..., description="Associated session")
    novel_id: str = Field(default="", description="Novel ID")
    
    # Current position
    current_phase: str = Field(..., description="Current phase ID")
    current_phase_index: int = Field(default=0, description="Current phase index")
    
    # Phase history
    completed_phases: List[str] = Field(default_factory=list, description="Completed phase IDs")
    phase_data: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Data collected per phase"
    )
    
    # State
    status: str = Field(default="active", description="active/paused/completed/failed")
    started_at: str = Field(default="", description="Start timestamp")
    updated_at: str = Field(default="", description="Last update timestamp")
    
    # Context accumulated
    workflow_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context accumulated during workflow"
    )
    
    def is_complete(self) -> bool:
        """Check if workflow is complete."""
        return self.status == "completed"
    
    def get_progress(self) -> float:
        """Get completion progress (0.0 - 1.0)."""
        if not self.completed_phases:
            return 0.0
        total = len(self.completed_phases) + 1  # +1 for current phase
        return len(self.completed_phases) / total


class WorkflowStepResult(BaseModel):
    """Result of executing a workflow step."""
    
    success: bool = Field(default=True, description="Whether step succeeded")
    phase_id: str = Field(..., description="Phase that was executed")
    tool_used: str = Field(default="", description="Tool that was called")
    tool_result: Optional[Dict[str, Any]] = Field(default=None, description="Tool result")
    
    # User interaction
    message: str = Field(default="", description="Message to user")
    follow_up_questions: List[str] = Field(default_factory=list, description="Questions for user")
    
    # Phase transition
    phase_complete: bool = Field(default=False, description="Whether phase is complete")
    can_advance: bool = Field(default=False, description="Whether can advance to next phase")
    next_phase: Optional[str] = Field(default=None, description="Next phase if advancing")
    
    # Workflow state
    workflow_complete: bool = Field(default=False, description="Whether workflow is complete")
    workflow_context_updates: Dict[str, Any] = Field(
        default_factory=dict,
        description="Updates to workflow context"
    )
```

---

## 2. Workflow Registry

### 2.1 New File: `tools/workflow_registry.py`

```python
"""Workflow Registry — 管理和发现可用的工作流。

工作流是预定义的多步骤流程，Director 根据用户意图选择合适的工作流。
工作流配置从 YAML 文件加载，支持动态扩展。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from tools.models.workflow import (
    WorkflowDefinition,
    WorkflowPhase,
    WorkflowState,
    WorkflowStepResult,
    PhaseCondition,
)
from tools.models.intent import TaskIntent

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """工作流注册表 — 管理所有可用工作流。"""
    
    _instance: Optional["WorkflowRegistry"] = None
    
    def __new__(cls) -> "WorkflowRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._workflows: Dict[str, WorkflowDefinition] = {}
            cls._instance._intent_map: Dict[str, List[str]] = {}
            cls._instance._loaded = False
        return cls._instance
    
    def load_from_directory(self, workflows_dir: Path) -> int:
        """从目录加载所有工作流配置。"""
        if not workflows_dir.exists():
            logger.warning("Workflows directory not found: %s", workflows_dir)
            return 0
        
        loaded = 0
        for yaml_file in workflows_dir.glob("*.yaml"):
            try:
                with yaml_file.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                
                workflow = WorkflowDefinition(**data)
                self.register(workflow)
                loaded += 1
                logger.info("Loaded workflow: %s from %s", workflow.workflow_id, yaml_file)
            except Exception as e:
                logger.error("Failed to load workflow from %s: %s", yaml_file, e)
        
        self._loaded = True
        return loaded
    
    def register(self, workflow: WorkflowDefinition) -> None:
        """注册工作流。"""
        self._workflows[workflow.workflow_id] = workflow
        
        # 建立意图到工作流的映射
        for intent in workflow.trigger_intents:
            if intent not in self._intent_map:
                self._intent_map[intent] = []
            if workflow.workflow_id not in self._intent_map[intent]:
                self._intent_map[intent].append(workflow.workflow_id)
    
    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """获取工作流定义。"""
        return self._workflows.get(workflow_id)
    
    def get_workflows_for_intent(self, intent: TaskIntent) -> List[WorkflowDefinition]:
        """获取处理某意图的所有工作流。"""
        workflow_ids = self._intent_map.get(intent.value, [])
        return [self._workflows[wid] for wid in workflow_ids if wid in self._workflows]
    
    def list_workflows(self, category: Optional[str] = None) -> List[WorkflowDefinition]:
        """列出所有工作流。"""
        workflows = list(self._workflows.values())
        if category:
            workflows = [w for w in workflows if w.category == category]
        return workflows
    
    def detect_workflow(
        self,
        intent: TaskIntent,
        user_message: str,
        context: Dict[str, Any],
    ) -> Optional[WorkflowDefinition]:
        """检测最适合的工作流。
        
        优先级：
        1. 意图匹配 + 关键词匹配
        2. 关键词匹配
        3. 上下文条件匹配
        """
        candidates = []
        
        # 1. 意图匹配
        intent_workflows = self.get_workflows_for_intent(intent)
        for wf in intent_workflows:
            score = 1.0
            # 关键词加成
            keyword_matches = sum(1 for kw in wf.trigger_keywords if kw in user_message)
            score += keyword_matches * 0.2
            candidates.append((wf, score))
        
        # 2. 纯关键词匹配
        for wf in self._workflows.values():
            if wf in [c[0] for c in candidates]:
                continue
            keyword_matches = sum(1 for kw in wf.trigger_keywords if kw in user_message)
            if keyword_matches > 0:
                score = keyword_matches * 0.3
                candidates.append((wf, score))
        
        # 3. 按分数排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        return candidates[0][0] if candidates else None
    
    def create_state(
        self,
        workflow_id: str,
        session_id: str,
        novel_id: str = "",
    ) -> WorkflowState:
        """创建工作流执行状态。"""
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow not found: {workflow_id}")
        
        from datetime import datetime
        now = datetime.now().isoformat()
        
        return WorkflowState(
            workflow_id=workflow_id,
            session_id=session_id,
            novel_id=novel_id,
            current_phase=workflow.entry_phase or (workflow.phases[0].phase_id if workflow.phases else ""),
            current_phase_index=0,
            started_at=now,
            updated_at=now,
        )
    
    def get_phase(self, workflow_id: str, phase_id: str) -> Optional[WorkflowPhase]:
        """获取工作流中的阶段。"""
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            return None
        for phase in workflow.phases:
            if phase.phase_id == phase_id:
                return phase
        return None
    
    def get_next_phase(self, workflow_id: str, current_phase_id: str) -> Optional[str]:
        """获取下一阶段ID。"""
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            return None
        
        for i, phase in enumerate(workflow.phases):
            if phase.phase_id == current_phase_id:
                if i + 1 < len(workflow.phases):
                    return workflow.phases[i + 1].phase_id
                return None
        return None
    
    def is_last_phase(self, workflow_id: str, phase_id: str) -> bool:
        """检查是否是最后阶段。"""
        workflow = self.get_workflow(workflow_id)
        if not workflow or not workflow.phases:
            return True
        return workflow.phases[-1].phase_id == phase_id


# 全局注册表实例
workflow_registry = WorkflowRegistry()


def load_workflows(project_dir: Path) -> None:
    """加载项目工作流配置。"""
    workflows_dir = project_dir / "workflows"
    workflow_registry.load_from_directory(workflows_dir)
```

---

## 3. Built-in Workflow Definitions

### 3.1 `workflows/outline_creation.yaml`

```yaml
# 大纲创建工作流 — 从零开始创建完整大纲
# 流程：总纲构思 → 篇纲规划 → 节纲细化 → 章纲编写

workflow_id: outline_creation
name: 大纲创建流程
description: 从零开始创建完整的四级大纲结构
category: outline
version: "1.0"

trigger_intents:
  - outline_assist
  - project_init

trigger_keywords:
  - 创建大纲
  - 新建大纲
  - 从零开始
  - 构思大纲
  - 规划大纲
  - 开始新小说

required_context:
  - novel_id

produced_context:
  - master_outline
  - arc_outlines
  - section_outlines
  - chapter_outlines

estimated_steps: 12
is_destructive: false

phases:
  - phase_id: master
    name: 总纲构思
    description: 确定全书的核心框架、主题、结局
    order: 0
    tools:
      - outline_assist
    primary_tool: outline_assist
    context_keys:
      - novel_id
    user_prompts:
      - 您的书名叫什么？
      - 核心主题是什么？（一句话概括）
      - 期望的结局走向是什么？（开放式/悲剧/喜剧/反转）
    help_text: |
      总纲是全书的顶层规划，需要确定：
      - 书名和主题
      - 世界观前提
      - 整体基调
      - 关键转折点（3-7个）
    completion_conditions:
      - type: has_data
        key: master_outline.title
      - type: has_data
        key: master_outline.core_theme
    transition_type: manual
    next_phase: arcs

  - phase_id: arcs
    name: 篇纲规划
    description: 将全书划分为3-5个大剧情弧
    order: 1
    tools:
      - outline_assist
    primary_tool: outline_assist
    context_keys:
      - novel_id
      - master_outline
    user_prompts:
      - 根据关键转折点，您计划分几个大篇？（建议3-5个）
      - 每篇的主要矛盾是什么？
    help_text: |
      篇纲是大剧情弧，每个篇纲对应一个完整的矛盾-发展-收束周期。
      需要为每个篇确定：篇名、主要矛盾、收束方向。
    completion_conditions:
      - type: has_data
        key: arc_outlines
      - type: custom
        expression: "len(arc_outlines) >= 2"
    transition_type: manual
    next_phase: sections

  - phase_id: sections
    name: 节纲细化
    description: 将每个篇纲细分为2-4个情节单元
    order: 2
    tools:
      - outline_assist
    primary_tool: outline_assist
    context_keys:
      - novel_id
      - master_outline
      - arc_outlines
    user_prompts:
      - 为每个篇划分2-4个节，每个节包含一个完整的情节单元。
      - 每个节的关键事件有哪些？
    help_text: |
      节纲是情节单元，包含若干关键事件。
      需要为每个节确定：节名、情节概要、关键事件列表。
    completion_conditions:
      - type: has_data
        key: section_outlines
    transition_type: manual
    next_phase: chapters

  - phase_id: chapters
    name: 章纲编写
    description: 为每个节纲下的章节编写详细的写作目标
    order: 3
    tools:
      - outline_assist
    primary_tool: outline_assist
    context_keys:
      - novel_id
      - master_outline
      - arc_outlines
      - section_outlines
    user_prompts:
      - 为每个节生成3-8个章节。
      - 每章的写作目标是什么？
      - 涉及哪些人物和场景？
    help_text: |
      章纲是最小生成单元，对应具体的写作任务。
      需要为每章确定：章名、写作目标、关键场景、涉及人物。
    completion_conditions:
      - type: has_data
        key: chapter_outlines
    transition_type: manual
    next_phase: review

  - phase_id: review
    name: 最终审核
    description: 检查大纲完整性，确认伏笔和人物分布
    order: 4
    tools:
      - outline_assist
      - foreshadow_query
      - character_query
    primary_tool: outline_assist
    context_keys:
      - novel_id
      - master_outline
      - arc_outlines
      - section_outlines
      - chapter_outlines
    user_prompts:
      - 请确认大纲是否符合预期？
      - 是否需要调整章节顺序或内容？
    help_text: |
      最终检查清单：
      - 总纲字段完整
      - 篇纲数量合理（3-5个）
      - 节纲数量合理（每篇2-4个）
      - 章纲数量合理（每节3-8个）
      - 关键转折点在篇纲中有体现
      - 伏笔埋设/回收点已标记
    completion_conditions:
      - type: user_confirm
        key: outline_approved
    transition_type: manual

entry_phase: master
exit_phase: review
```

### 3.2 `workflows/outline_modification.yaml`

```yaml
# 大纲修改工作流 — 调整已有大纲
# 流程：识别修改点 → 评估影响 → 执行修改 → 同步更新

workflow_id: outline_modification
name: 大纲修改流程
description: 调整已有大纲的结构或内容
category: outline
version: "1.0"

trigger_intents:
  - outline_assist

trigger_keywords:
  - 修改大纲
  - 调整大纲
  - 改篇纲
  - 改节纲
  - 改章纲
  - 删除
  - 移动
  - 合并
  - 拆分

required_context:
  - novel_id
  - current_hierarchy

produced_context:
  - modified_hierarchy
  - impact_report

estimated_steps: 6
is_destructive: true

phases:
  - phase_id: identify
    name: 识别修改点
    description: 确定要修改的具体内容和位置
    order: 0
    tools:
      - outline_assist
    primary_tool: outline_assist
    context_keys:
      - novel_id
      - current_hierarchy
    user_prompts:
      - 您想修改哪个层级？（总纲/篇/节/章）
      - 具体想修改什么？（结构调整/内容修改/伏笔调整）
    help_text: |
      常见修改类型：
      - 结构调整：增删篇/节/章，调整顺序
      - 内容修改：修改矛盾、目标、场景
      - 伏笔调整：新增/删除/移动伏笔
    completion_conditions:
      - type: has_data
        key: modification_target
      - type: has_data
        key: modification_type
    transition_type: manual
    next_phase: assess

  - phase_id: assess
    name: 评估影响范围
    description: 检查修改对上下级大纲和伏笔链的影响
    order: 1
    tools:
      - outline_assist
      - foreshadow_query
      - character_query
    primary_tool: outline_assist
    context_keys:
      - novel_id
      - current_hierarchy
      - modification_target
    user_prompts:
      - 正在检查修改影响范围...
    help_text: |
      影响检查项：
      - 修改是否影响上下级大纲？
      - 修改是否影响伏笔链？
      - 修改是否影响人物时间线？
    completion_conditions:
      - type: has_data
        key: impact_report
    transition_type: auto
    next_phase: execute

  - phase_id: execute
    name: 执行修改
    description: 应用修改到大纲
    order: 2
    tools:
      - outline_assist
    primary_tool: outline_assist
    context_keys:
      - novel_id
      - current_hierarchy
      - modification_target
      - modification_type
    user_prompts:
      - 确认执行以下修改？
    completion_conditions:
      - type: tool_success
        key: modification_applied
    transition_type: manual
    next_phase: sync

  - phase_id: sync
    name: 同步更新
    description: 更新相关联的数据和同步Markdown文件
    order: 3
    tools:
      - outline_assist
      - lore_query
    primary_tool: outline_assist
    context_keys:
      - novel_id
      - modified_hierarchy
    user_prompts:
      - 正在同步更新相关数据...
    help_text: |
      同步检查：
      - 更新 hierarchy.yaml
      - 导出 outline.md
      - 检查伏笔 DAG 是否有环或断裂
      - 检查人物时间线是否连续
    completion_conditions:
      - type: has_data
        key: sync_complete
    transition_type: auto

entry_phase: identify
exit_phase: sync
```

### 3.3 `workflows/style_selection.yaml`

```yaml
# 风格选择工作流 — 选择和应用风格
# 流程：选择风格来源 → 合成风格 → 预览确认

workflow_id: style_selection
name: 风格选择流程
description: 为作品选择和应用风格配置
category: style
version: "1.0"

trigger_intents:
  - style_analyze
  - style_compose

trigger_keywords:
  - 选择风格
  - 应用风格
  - 设置风格
  - 风格配置
  - 合成风格

required_context:
  - novel_id

produced_context:
  - style_id
  - composed_style

estimated_steps: 5
is_destructive: false

phases:
  - phase_id: choose_source
    name: 选择风格来源
    description: 决定风格来源（提取自原著/选择预设/自定义）
    order: 0
    tools:
      - style_list
      - style_read_batch
    primary_tool: style_list
    context_keys:
      - novel_id
    user_prompts:
      - 您希望如何获取风格？
      - A. 从参考原著提取
      - B. 选择已有风格模板
      - C. 自定义风格配置
    help_text: |
      风格来源选项：
      - 从原著提取：使用 Reader Agent 从参考文本中提取风格特征
      - 选择模板：使用已有的风格配置（如《术师手册》风格）
      - 自定义：手动配置风格参数
    completion_conditions:
      - type: has_data
        key: style_source_type
    transition_type: manual
    next_phase: extract_or_select

  - phase_id: extract_or_select
    name: 提取或选择风格
    description: 根据来源类型执行相应操作
    order: 1
    tools:
      - style_read_batch
      - style_list
    primary_tool: style_read_batch
    context_keys:
      - novel_id
      - style_source_type
    user_prompts:
      - 如果从原著提取，请提供原著文本路径
      - 如果选择模板，请从列表中选择
    completion_conditions:
      - type: has_data
        key: style_id
    transition_type: manual
    next_phase: compose

  - phase_id: compose
    name: 合成风格文档
    description: 将三层风格合成为最终生成指令
    order: 2
    tools:
      - style_compose
    primary_tool: style_compose
    context_keys:
      - novel_id
      - style_id
    user_prompts:
      - 正在合成风格文档...
    help_text: |
      三层风格合成：
      1. 通用技法 (craft/) - 可选参考
      2. 作品风格 (styles/{作品}/) - 应当遵循
      3. 作品设定 (novels/{作品}/) - 不可违反
    completion_conditions:
      - type: has_data
        key: composed_style
    transition_type: auto
    next_phase: preview

  - phase_id: preview
    name: 预览确认
    description: 预览合成后的风格文档，确认应用
    order: 3
    tools:
      - style_profile
    primary_tool: style_profile
    context_keys:
      - novel_id
      - style_id
      - composed_style
    user_prompts:
      - 请确认风格配置是否符合预期？
    completion_conditions:
      - type: user_confirm
        key: style_confirmed
    transition_type: manual

entry_phase: choose_source
exit_phase: preview
```

### 3.4 `workflows/chapter_writing.yaml`

```yaml
# 章节写作工作流 — 完整的章节生成流程
# 流程：准备上下文 → 生成草稿 → 逻辑审查 → 用户确认 → 风格润色

workflow_id: chapter_writing
name: 章节写作流程
description: 完整的章节生成流程（Pipeline V2）
category: writing
version: "1.0"

trigger_intents:
  - write_chapter

trigger_keywords:
  - 写章节
  - 生成章节
  - 写第
  - 生成第
  - 续写
  - 草稿

required_context:
  - novel_id
  - chapter_id

produced_context:
  - draft_text
  - polished_text
  - review_result

estimated_steps: 8
is_destructive: false

phases:
  - phase_id: prepare
    name: 准备上下文
    description: 组装生成所需的完整上下文
    order: 0
    tools:
      - start_chapter_pipeline
    primary_tool: start_chapter_pipeline
    context_keys:
      - novel_id
      - chapter_id
    user_prompts:
      - 请确认章节ID
      - 本章的写作目标是什么？
    completion_conditions:
      - type: has_data
        key: generation_context
    transition_type: manual
    next_phase: generate

  - phase_id: generate
    name: 生成草稿
    description: 使用 Writer Agent 生成章节草稿
    order: 1
    tools:
      - start_chapter_pipeline
    primary_tool: start_chapter_pipeline
    context_keys:
      - novel_id
      - chapter_id
      - generation_context
    user_prompts:
      - 正在生成草稿...
    completion_conditions:
      - type: has_data
        key: draft_text
    transition_type: auto
    next_phase: review

  - phase_id: review
    name: 逻辑审查
    description: LoreChecker 检查逻辑一致性
    order: 2
    tools:
      - start_chapter_pipeline
    primary_tool: start_chapter_pipeline
    context_keys:
      - novel_id
      - chapter_id
      - draft_text
    user_prompts:
      - 正在进行逻辑审查...
    help_text: |
      审查内容包括：
      - 关键词/场景/人物一致性
      - 跨章节位置连续性
      - 物品库存一致性
      - 伏笔状态检查
    completion_conditions:
      - type: has_data
        key: review_result
    transition_type: auto
    next_phase: user_confirm

  - phase_id: user_confirm
    name: 用户确认
    description: 用户审核草稿并决定是否继续
    order: 3
    tools: []
    context_keys:
      - draft_text
      - review_result
    user_prompts:
      - 请审核草稿内容
      - 是否需要修改？是否继续风格润色？
    completion_conditions:
      - type: user_confirm
        key: user_approved
    transition_type: manual
    next_phase: polish

  - phase_id: polish
    name: 风格润色
    description: Stylist 进行最终润色（可选）
    order: 4
    tools:
      - start_chapter_pipeline
    primary_tool: start_chapter_pipeline
    context_keys:
      - novel_id
      - chapter_id
      - draft_text
      - style_id
    user_prompts:
      - 正在进行风格润色...
    completion_conditions:
      - type: has_data
        key: polished_text
    transition_type: auto

entry_phase: prepare
exit_phase: polish
```

### 3.5 `workflows/project_setup.yaml`

```yaml
# 项目初始化工作流 — 创建新小说项目
# 流程：基本信息 → 初始角色 → 世界观设定 → 风格选择

workflow_id: project_setup
name: 项目初始化流程
description: 创建并配置新的小说项目
category: project
version: "1.0"

trigger_intents:
  - project_init

trigger_keywords:
  - 新建项目
  - 初始化
  - 创建小说
  - 开始新项目
  - 新项目

required_context: []

produced_context:
  - novel_id
  - master_outline
  - initial_characters
  - world_settings

estimated_steps: 10
is_destructive: false

phases:
  - phase_id: basic_info
    name: 基本信息
    description: 设置项目基本信息
    order: 0
    tools:
      - project_init
    primary_tool: project_init
    context_keys: []
    user_prompts:
      - 小说ID（英文、数字、下划线）
      - 书名
      - 作者
      - 目标字数
    completion_conditions:
      - type: has_data
        key: novel_id
      - type: has_data
        key: title
    transition_type: manual
    next_phase: theme

  - phase_id: theme
    name: 主题设定
    description: 确定核心主题和世界观
    order: 1
    tools:
      - project_init
    primary_tool: project_init
    context_keys:
      - novel_id
    user_prompts:
      - 核心主题是什么？
      - 世界观前提？
      - 整体基调？（轻松/严肃/黑暗/热血）
      - 结局走向？
    completion_conditions:
      - type: has_data
        key: core_theme
    transition_type: manual
    next_phase: characters

  - phase_id: characters
    name: 初始角色
    description: 创建主要角色
    order: 2
    tools:
      - character_create
    primary_tool: character_create
    context_keys:
      - novel_id
    user_prompts:
      - 请添加主要角色（主角、重要配角）
      - 角色名、类型、简介
    help_text: |
      角色类型：
      - 主角：故事核心人物
      - 重要配角：有独立剧情线的角色
      - 普通配角：参与主要事件的角色
      - 龙套：功能性角色
    completion_conditions:
      - type: has_data
        key: initial_characters
      - type: custom
        expression: "len(initial_characters) >= 1"
    transition_type: manual
    next_phase: world

  - phase_id: world
    name: 世界观设定
    description: 建立基础世界观
    order: 3
    tools:
      - lore_create
    primary_tool: lore_create
    context_keys:
      - novel_id
    user_prompts:
      - 是否需要添加世界观设定？（地点、势力、规则等）
    help_text: |
      可选的世界观设定：
      - 地点：故事发生的主要场所
      - 势力：主要势力和组织
      - 规则：世界观的核心规则
    completion_conditions:
      - type: user_confirm
        key: world_setup_complete
    transition_type: manual
    next_phase: style

  - phase_id: style
    name: 风格选择
    description: 选择或配置风格
    order: 4
    tools:
      - style_list
      - style_compose
    primary_tool: style_list
    context_keys:
      - novel_id
    user_prompts:
      - 是否现在配置风格？
      - 可以稍后在风格设置中配置
    completion_conditions:
      - type: user_confirm
        key: style_setup_skipped_or_done
    transition_type: manual

entry_phase: basic_info
exit_phase: style
```

---

## 4. Enhanced Director with Workflow Support

### 4.1 Updated DirectorAgent

```python
"""Enhanced Director Agent with Workflow support."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from tools.models.intent import TaskIntent, IntentDecision, DirectorResponse
from tools.models.workflow import (
    WorkflowDefinition,
    WorkflowState,
    WorkflowStepResult,
    WorkflowPhase,
)
from tools.models.tool_registry import ToolResult
from tools.conversation_manager import ConversationManager
from tools.tool_registry import registry
from tools.workflow_registry import workflow_registry, load_workflows

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

logger = logging.getLogger(__name__)


class DirectorAgent:
    """统一助手 — 支持工作流的多步骤对话助手。"""
    
    INTENT_KEYWORDS: Dict[TaskIntent, List[str]] = {
        # ... (same as before)
    }
    
    def __init__(
        self,
        project_dir: Optional[Path] = None,
        novel_id: str = "",
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        self.project_dir = project_dir or Path.cwd()
        self.novel_id = novel_id
        self._llm_client = llm_client
        self._router = router
        
        # 对话管理
        self._conversation_mgr = ConversationManager(self.project_dir)
        
        # 工作流管理
        self._workflow_states: Dict[str, WorkflowState] = {}
        
        # 加载工作流
        load_workflows(self.project_dir)
        
        # 注册内置工具
        self._register_builtin_tools()
    
    # ── 主要入口 ──────────────────────────────────────────────────
    
    def process_request(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> DirectorResponse:
        """处理用户请求 — 统一入口。"""
        # 获取或创建会话
        session = self._get_or_create_session(session_id, context)
        
        # 记录用户消息
        self._conversation_mgr.update_session(
            session.session_id,
            user_message=user_message,
        )
        
        # 获取对话上下文
        conversation_context = self._conversation_mgr.get_conversation_context(
            session.session_id,
            max_turns=10,
        )
        
        # 1. 检查是否在执行中的工作流
        workflow_state = self._get_active_workflow(session.session_id)
        
        if workflow_state:
            # 继续工作流
            return self._continue_workflow(
                workflow_state,
                user_message,
                conversation_context,
                session.context_data,
            )
        
        # 2. 意图识别
        intent_decision = self._classify_intent(
            user_message,
            conversation_context,
            session.context_data,
        )
        
        # 3. 检测是否需要启动工作流
        workflow = workflow_registry.detect_workflow(
            intent_decision.intent,
            user_message,
            session.context_data,
        )
        
        if workflow:
            # 启动新工作流
            return self._start_workflow(
                workflow,
                session.session_id,
                user_message,
                intent_decision,
                session.context_data,
            )
        
        # 4. 单步操作（无工作流）
        return self._execute_single_step(
            session.session_id,
            intent_decision,
            session.context_data,
        )
    
    # ── 工作流管理 ──────────────────────────────────────────────────
    
    def _get_active_workflow(self, session_id: str) -> Optional[WorkflowState]:
        """获取会话中活跃的工作流。"""
        return self._workflow_states.get(session_id)
    
    def _start_workflow(
        self,
        workflow: WorkflowDefinition,
        session_id: str,
        user_message: str,
        intent: IntentDecision,
        context: Dict[str, Any],
    ) -> DirectorResponse:
        """启动新工作流。"""
        # 创建工作流状态
        state = workflow_registry.create_state(
            workflow.workflow_id,
            session_id,
            self.novel_id,
        )
        
        self._workflow_states[session_id] = state
        
        # 获取第一阶段
        phase = workflow_registry.get_phase(
            workflow.workflow_id,
            state.current_phase,
        )
        
        if not phase:
            return DirectorResponse(
                success=False,
                message="工作流配置错误：找不到初始阶段",
                detected_intent=intent.intent,
            )
        
        # 构建响应
        message = f"开始「{workflow.name}」流程\n\n"
        message += f"**当前阶段**：{phase.name}\n"
        message += f"{phase.description}\n\n"
        
        if phase.user_prompts:
            message += "**请回答以下问题**：\n"
            for i, prompt in enumerate(phase.user_prompts, 1):
                message += f"{i}. {prompt}\n"
        
        if phase.help_text:
            message += f"\n**帮助**：\n{phase.help_text}"
        
        # 更新会话
        self._conversation_mgr.update_session(
            session_id,
            assistant_response=message,
            metadata={
                "workflow_id": workflow.workflow_id,
                "current_phase": phase.phase_id,
            },
        )
        
        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            confidence=intent.confidence,
            follow_up_questions=phase.user_prompts,
            context_updates={
                "workflow_id": workflow.workflow_id,
                "workflow_phase": phase.phase_id,
            },
            reasoning=f"启动工作流: {workflow.name}",
        )
    
    def _continue_workflow(
        self,
        state: WorkflowState,
        user_message: str,
        conversation_context: str,
        session_context: Dict[str, Any],
    ) -> DirectorResponse:
        """继续执行工作流。"""
        workflow = workflow_registry.get_workflow(state.workflow_id)
        if not workflow:
            del self._workflow_states[state.session_id]
            return DirectorResponse(
                success=False,
                message="工作流已失效，请重新开始",
            )
        
        # 获取当前阶段
        phase = workflow_registry.get_phase(
            state.workflow_id,
            state.current_phase,
        )
        
        if not phase:
            return DirectorResponse(
                success=False,
                message="工作流阶段配置错误",
            )
        
        # 执行当前阶段的工具
        step_result = self._execute_phase(
            state,
            phase,
            user_message,
            session_context,
        )
        
        # 检查是否可以进入下一阶段
        if step_result.can_advance and step_result.next_phase:
            # 更新状态
            state.completed_phases.append(state.current_phase)
            state.current_phase = step_result.next_phase
            state.updated_at = datetime.now().isoformat()
            
            # 获取下一阶段信息
            next_phase = workflow_registry.get_phase(
                state.workflow_id,
                step_result.next_phase,
            )
            
            if next_phase:
                step_result.message += f"\n\n---\n\n**进入下一阶段**：{next_phase.name}\n"
                step_result.follow_up_questions = next_phase.user_prompts
        
        # 检查工作流是否完成
        if step_result.workflow_complete or workflow_registry.is_last_phase(
            state.workflow_id, state.current_phase
        ):
            if step_result.phase_complete:
                state.status = "completed"
                step_result.workflow_complete = True
                step_result.message += f"\n\n✅ 「{workflow.name}」流程已完成！"
                del self._workflow_states[state.session_id]
        
        # 更新会话
        self._conversation_mgr.update_session(
            state.session_id,
            assistant_response=step_result.message,
            metadata={
                "workflow_id": state.workflow_id,
                "current_phase": state.current_phase,
                "workflow_status": state.status,
            },
        )
        
        return DirectorResponse(
            success=step_result.success,
            message=step_result.message,
            detected_intent=TaskIntent(state.workflow_id.split("_")[0].upper())
            if "_" in state.workflow_id else TaskIntent.UNKNOWN,
            tool_used=step_result.tool_used,
            tool_result=step_result.tool_result,
            follow_up_questions=step_result.follow_up_questions,
            context_updates=step_result.workflow_context_updates,
            session_state="completed" if step_result.workflow_complete else "active",
            reasoning=f"工作流 {workflow.name} - 阶段 {phase.name}",
        )
    
    def _execute_phase(
        self,
        state: WorkflowState,
        phase: WorkflowPhase,
        user_message: str,
        context: Dict[str, Any],
    ) -> WorkflowStepResult:
        """执行工作流阶段。"""
        # 收集阶段数据
        phase_data = state.phase_data.get(phase.phase_id, {})
        
        # 更新阶段数据（从用户消息提取）
        updates = self._extract_phase_data(user_message, phase)
        phase_data.update(updates)
        state.phase_data[phase.phase_id] = phase_data
        
        # 执行主要工具
        tool_result = None
        if phase.primary_tool:
            tool_params = self._build_tool_params(phase, phase_data, context)
            tool_result = registry.execute(
                phase.primary_tool,
                tool_params,
                {**context, **state.workflow_context, "novel_id": self.novel_id},
            )
        
        # 检查阶段完成条件
        phase_complete = self._check_phase_completion(phase, phase_data, tool_result)
        
        # 确定下一阶段
        next_phase = None
        can_advance = False
        
        if phase_complete:
            can_advance = True
            next_phase = workflow_registry.get_next_phase(
                state.workflow_id,
                phase.phase_id,
            )
        
        # 更新工作流上下文
        workflow_context_updates = {}
        if tool_result and tool_result.success:
            workflow_context_updates = tool_result.data
        
        return WorkflowStepResult(
            success=tool_result.success if tool_result else True,
            phase_id=phase.phase_id,
            tool_used=phase.primary_tool,
            tool_result=tool_result.data if tool_result else None,
            message=self._generate_phase_message(phase, phase_data, tool_result, phase_complete),
            follow_up_questions=[] if phase_complete else self._get_remaining_prompts(phase, phase_data),
            phase_complete=phase_complete,
            can_advance=can_advance,
            next_phase=next_phase,
            workflow_context_updates=workflow_context_updates,
        )
    
    def _extract_phase_data(
        self,
        message: str,
        phase: WorkflowPhase,
    ) -> Dict[str, Any]:
        """从用户消息提取阶段数据。"""
        import re
        data = {}
        
        # 简单的键值提取（可扩展为更复杂的 NLU）
        # 检测确认/否定
        if any(kw in message for kw in ["确认", "是", "好", "可以", "继续"]):
            data["user_confirmed"] = True
        elif any(kw in message for kw in ["取消", "否", "不", "返回"]):
            data["user_confirmed"] = False
        
        # 检测 ID
        id_match = re.search(r"(?:novel_|arc_|sec_|ch_)([a-zA-Z0-9_]+)", message)
        if id_match:
            data["target_id"] = id_match.group(0)
        
        # 检测引号内容（标题、名称）
        quoted = re.findall(r"[「『\"'](.+?)[」』\"']", message)
        if quoted:
            data["title"] = quoted[0]
        
        # 存储原始消息
        data["user_message"] = message
        
        return data
    
    def _build_tool_params(
        self,
        phase: WorkflowPhase,
        phase_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建工具调用参数。"""
        params = {}
        
        # 从阶段数据映射到工具参数
        if "title" in phase_data:
            params["title"] = phase_data["title"]
        if "target_id" in phase_data:
            params["target_id"] = phase_data["target_id"]
        if "user_message" in phase_data:
            params["content"] = phase_data["user_message"]
        
        return params
    
    def _check_phase_completion(
        self,
        phase: WorkflowPhase,
        phase_data: Dict[str, Any],
        tool_result: Optional[ToolResult],
    ) -> bool:
        """检查阶段是否完成。"""
        for condition in phase.completion_conditions:
            if condition.type == "has_data":
                # 检查数据键是否存在
                key = condition.key
                parts = key.split(".")
                value = phase_data
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = None
                        break
                if value is None:
                    return False
            
            elif condition.type == "user_confirm":
                if not phase_data.get("user_confirmed", False):
                    return False
            
            elif condition.type == "tool_success":
                if not tool_result or not tool_result.success:
                    return False
        
        return True
    
    def _get_remaining_prompts(
        self,
        phase: WorkflowPhase,
        phase_data: Dict[str, Any],
    ) -> List[str]:
        """获取尚未回答的提示问题。"""
        # 简化实现：返回所有提示
        return phase.user_prompts
    
    def _generate_phase_message(
        self,
        phase: WorkflowPhase,
        phase_data: Dict[str, Any],
        tool_result: Optional[ToolResult],
        phase_complete: bool,
    ) -> str:
        """生成阶段响应消息。"""
        message = f"**{phase.name}**\n\n"
        
        if tool_result:
            message += tool_result.message + "\n\n"
        
        if phase_complete:
            message += "✅ 此阶段已完成。\n"
            if phase.next_phase:
                message += "准备进入下一阶段..."
        else:
            message += "请继续提供信息以完成此阶段。\n"
        
        return message
    
    def _execute_single_step(
        self,
        session_id: str,
        intent: IntentDecision,
        context: Dict[str, Any],
    ) -> DirectorResponse:
        """执行单步操作（无工作流）。"""
        # (原有的单步执行逻辑)
        pass
    
    # ... (其他方法保持不变)
```

---

## 5. Test Cases

### 5.1 `tests/test_workflow_system.py`

```python
"""Tests for workflow system."""

import pytest
from pathlib import Path

from tools.models.workflow import (
    WorkflowDefinition,
    WorkflowPhase,
    WorkflowState,
    PhaseCondition,
    PhaseTransitionType,
)
from tools.workflow_registry import WorkflowRegistry, workflow_registry


class TestWorkflowModels:
    """Test workflow data models."""
    
    def test_workflow_phase_creation(self):
        """Test WorkflowPhase creation."""
        phase = WorkflowPhase(
            phase_id="test_phase",
            name="Test Phase",
            description="A test phase",
            order=0,
            tools=["tool1"],
            user_prompts=["Question 1"],
        )
        
        assert phase.phase_id == "test_phase"
        assert phase.order == 0
        assert len(phase.tools) == 1
    
    def test_workflow_definition_creation(self):
        """Test WorkflowDefinition creation."""
        workflow = WorkflowDefinition(
            workflow_id="test_workflow",
            name="Test Workflow",
            trigger_intents=["outline_assist"],
            phases=[
                WorkflowPhase(phase_id="phase1", name="Phase 1", order=0),
                WorkflowPhase(phase_id="phase2", name="Phase 2", order=1),
            ],
        )
        
        assert workflow.workflow_id == "test_workflow"
        assert len(workflow.phases) == 2
    
    def test_workflow_state_progress(self):
        """Test WorkflowState progress calculation."""
        state = WorkflowState(
            workflow_id="test",
            session_id="sess_001",
            current_phase="phase2",
            completed_phases=["phase1"],
        )
        
        progress = state.get_progress()
        assert 0 < progress < 1


class TestWorkflowRegistry:
    """Test WorkflowRegistry."""
    
    @pytest.fixture
    def registry(self, tmp_path):
        """Create fresh registry for each test."""
        WorkflowRegistry._instance = None
        reg = WorkflowRegistry()
        return reg
    
    def test_register_workflow(self, registry):
        """Test workflow registration."""
        workflow = WorkflowDefinition(
            workflow_id="test_wf",
            name="Test",
            trigger_intents=["outline_assist"],
            phases=[],
        )
        
        registry.register(workflow)
        
        assert registry.get_workflow("test_wf") is not None
    
    def test_get_workflows_for_intent(self, registry):
        """Test getting workflows by intent."""
        workflow = WorkflowDefinition(
            workflow_id="test_wf",
            name="Test",
            trigger_intents=["outline_assist"],
            phases=[],
        )
        registry.register(workflow)
        
        from tools.models.intent import TaskIntent
        workflows = registry.get_workflows_for_intent(TaskIntent.OUTLINE_ASSIST)
        
        assert len(workflows) == 1
        assert workflows[0].workflow_id == "test_wf"
    
    def test_create_state(self, registry):
        """Test creating workflow state."""
        workflow = WorkflowDefinition(
            workflow_id="test_wf",
            name="Test",
            phases=[
                WorkflowPhase(phase_id="phase1", name="Phase 1", order=0),
            ],
            entry_phase="phase1",
        )
        registry.register(workflow)
        
        state = registry.create_state("test_wf", "sess_001", "novel_001")
        
        assert state.workflow_id == "test_wf"
        assert state.current_phase == "phase1"
    
    def test_detect_workflow(self, registry):
        """Test workflow detection."""
        workflow = WorkflowDefinition(
            workflow_id="outline_creation",
            name="Outline Creation",
            trigger_intents=["outline_assist"],
            trigger_keywords=["创建大纲", "新建大纲"],
            phases=[],
        )
        registry.register(workflow)
        
        from tools.models.intent import TaskIntent
        
        # Test with matching keyword
        detected = registry.detect_workflow(
            TaskIntent.OUTLINE_ASSIST,
            "我想创建大纲",
            {},
        )
        
        assert detected is not None
        assert detected.workflow_id == "outline_creation"
    
    def test_load_from_yaml(self, registry, tmp_path):
        """Test loading workflow from YAML."""
        yaml_content = """
workflow_id: test_yaml
name: Test YAML Workflow
trigger_intents:
  - outline_assist
phases:
  - phase_id: step1
    name: Step 1
    order: 0
    tools:
      - outline_assist
"""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content)
        
        loaded = registry.load_from_directory(tmp_path)
        
        assert loaded == 1
        assert registry.get_workflow("test_yaml") is not None


class TestDirectorWithWorkflow:
    """Test Director with workflow support."""
    
    @pytest.fixture
    def director(self, tmp_path):
        from tools.agents.director import DirectorAgent
        return DirectorAgent(project_dir=tmp_path, novel_id="test")
    
    def test_workflow_detection_in_process(self, director):
        """Test that Director detects and starts workflows."""
        # This would require setting up workflow files
        pass
    
    def test_workflow_state_persistence(self, director):
        """Test workflow state is maintained across turns."""
        pass
```

---

## 6. Implementation Steps (Revised)

### Phase 1: Workflow Models (1 day)
1. Create `tools/models/workflow.py`
2. Define WorkflowDefinition, WorkflowPhase, WorkflowState
3. Define PhaseCondition, PhaseTransitionType
4. Add unit tests

### Phase 2: Workflow Registry (1 day)
1. Create `tools/workflow_registry.py`
2. Implement workflow registration
3. Implement intent-to-workflow mapping
4. Implement YAML loading
5. Add unit tests

### Phase 3: Built-in Workflows (1 day)
1. Create `workflows/` directory
2. Create `outline_creation.yaml`
3. Create `outline_modification.yaml`
4. Create `style_selection.yaml`
5. Create `chapter_writing.yaml`
6. Create `project_setup.yaml`
7. Test loading and validation

### Phase 4: Director Integration (2 days)
1. Add workflow detection to DirectorAgent
2. Implement workflow state management
3. Implement phase execution
4. Implement phase transitions
5. Implement completion checking
6. Add unit tests

### Phase 5: Tool Updates (1 day)
1. Update tools to work with workflow context
2. Add `style_list`, `style_read_batch`, `style_compose`, `style_profile` tools
3. Add `project_init`, `character_create` tools
4. Add `lore_create`, `lore_query` tools

### Phase 6: Web API Updates (0.5 day)
1. Add `/api/workflows` endpoint
2. Add `/api/sessions/{id}/workflow` endpoint
3. Update `/api/chat` to return workflow info

### Phase 7: Testing & Documentation (0.5 day)
1. Integration tests
2. Update workflow documentation
3. Run full test suite

---

## 7. File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `tools/models/workflow.py` | NEW | Workflow definition models |
| `tools/workflow_registry.py` | NEW | Workflow registry and management |
| `tools/agents/director.py` | MAJOR MODIFY | Add workflow support |
| `workflows/outline_creation.yaml` | NEW | Outline creation workflow |
| `workflows/outline_modification.yaml` | NEW | Outline modification workflow |
| `workflows/style_selection.yaml` | NEW | Style selection workflow |
| `workflows/chapter_writing.yaml` | NEW | Chapter writing workflow |
| `workflows/project_setup.yaml` | NEW | Project setup workflow |
| `tools/web/__init__.py` | MODIFY | Add workflow API endpoints |
| `tests/test_workflow_system.py` | NEW | Workflow tests |

---

## 8. Workflow-Tool Mapping

| Workflow | Primary Tools |
|----------|---------------|
| outline_creation | `outline_assist`, `foreshadow_query` |
| outline_modification | `outline_assist`, `lore_query`, `character_query` |
| style_selection | `style_list`, `style_read_batch`, `style_compose`, `style_profile` |
| chapter_writing | `start_chapter_pipeline` |
| project_setup | `project_init`, `character_create`, `lore_create`, `style_list` |

---

## 9. Backward Compatibility

- Existing single-step operations work without workflows
- Workflows are optional; Director falls back to single-step if no workflow matches
- Session-based workflow state is isolated from session conversation
- Workflow YAML files can be added without code changes

---

## 10. Future Extensions

1. **Custom Workflows**: Users can create their own workflow YAML files
2. **Workflow Branching**: Conditional paths within workflows
3. **Workflow Templates**: Pre-built workflows for common genres
4. **Workflow Analytics**: Track completion rates and bottlenecks
5. **Parallel Phases**: Execute multiple phases concurrently
