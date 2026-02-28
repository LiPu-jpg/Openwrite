# Workflow-Based Director System — Implementation Plan v3

## 概述

将 Director 升级为**工作流驱动的统一助手**，支持多种预定义工作流。用户可以根据当前任务选择或自动匹配工作流，每个工作流包含明确的阶段、工具配置和上下文需求。

---

## 1. 核心概念

### 1.1 工作流 (Workflow)

工作流是完成特定任务的**结构化步骤序列**。每个工作流定义：
- **触发条件**：什么情况下启动此工作流
- **阶段序列**：需要经过哪些步骤
- **工具配置**：每个阶段使用哪些工具
- **上下文需求**：需要加载什么数据
- **退出条件**：何时工作流完成

### 1.2 内置工作流

| 工作流 ID | 名称 | 触发意图 | 描述 |
|-----------|------|----------|------|
| `outline_creation` | 大纲创作 | OUTLINE_ASSIST (新建) | 总纲→篇纲→节纲→章纲 逐级扩展 |
| `outline_modification` | 大纲修改 | OUTLINE_ASSIST (修改) | 识别变更→评估影响→执行→同步 |
| `style_selection` | 文风选择 | STYLE_COMPOSE | 选择风格→合成→审核 |
| `chapter_writing` | 章节写作 | WRITE_CHAPTER | 现有 Pipeline V2 |
| `project_setup` | 项目初始化 | PROJECT_INIT | 创建项目结构 |
| `lore_query` | 世界观查询 | LORE_QUERY | 查询设定信息 |
| `character_management` | 角色管理 | CHARACTER_* | 创建/修改/查询角色 |
| `foreshadowing_management` | 伏笔管理 | FORESHADOW_* | 埋设/回收/查询伏笔 |

---

## 2. 数据模型

### 2.1 WorkflowDefinition (`tools/models/workflow.py`)

```python
"""Workflow definition models."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkflowPhase(BaseModel):
    """工作流阶段。"""
    
    phase_id: str = Field(..., description="阶段ID")
    name: str = Field(..., description="阶段名称")
    description: str = Field(default="", description="阶段描述")
    
    # 工具配置
    available_tools: List[str] = Field(default_factory=list, description="可用工具列表")
    required_tools: List[str] = Field(default_factory=list, description="必需工具列表")
    
    # 上下文需求
    context_keys: List[str] = Field(default_factory=list, description="需要加载的上下文键")
    
    # 用户交互
    user_prompt: str = Field(default="", description="向用户展示的提示")
    questions: List[str] = Field(default_factory=list, description="需要用户回答的问题")
    
    # 阶段转换
    auto_advance: bool = Field(default=False, description="是否自动进入下一阶段")
    next_phase: Optional[str] = Field(default=None, description="下一阶段ID")
    conditions: Dict[str, str] = Field(default_factory=dict, description="条件转换规则")


class WorkflowDefinition(BaseModel):
    """工作流定义。"""
    
    workflow_id: str = Field(..., description="工作流ID")
    name: str = Field(..., description="工作流名称")
    description: str = Field(default="", description="工作流描述")
    category: str = Field(default="general", description="工作流类别")
    
    # 触发配置
    trigger_intents: List[str] = Field(default_factory=list, description="触发意图列表")
    trigger_keywords: List[str] = Field(default_factory=list, description="触发关键词")
    priority: int = Field(default=0, description="优先级（高优先）")
    
    # 阶段定义
    phases: List[WorkflowPhase] = Field(default_factory=list, description="阶段列表")
    entry_phase: str = Field(default="", description="入口阶段ID")
    
    # 上下文需求
    requires_novel_id: bool = Field(default=True, description="是否需要小说ID")
    requires_outline: bool = Field(default=False, description="是否需要大纲存在")
    
    # 元数据
    version: str = Field(default="1.0", description="版本号")
    author: str = Field(default="system", description="作者")


class WorkflowState(BaseModel):
    """工作流运行时状态。"""
    
    workflow_id: str = Field(..., description="当前工作流ID")
    current_phase: str = Field(..., description="当前阶段ID")
    phase_history: List[str] = Field(default_factory=list, description="已完成的阶段")
    
    # 阶段数据
    phase_data: Dict[str, Any] = Field(default_factory=dict, description="各阶段积累的数据")
    
    # 状态
    status: str = Field(default="active", description="active/paused/completed/failed")
    started_at: str = Field(default="", description="启动时间")
    updated_at: str = Field(default="", description="更新时间")
    
    def advance_to(self, phase_id: str) -> None:
        """进入下一阶段。"""
        if self.current_phase:
            self.phase_history.append(self.current_phase)
        self.current_phase = phase_id
    
    def is_complete(self) -> bool:
        """检查是否完成。"""
        return self.status == "completed"
```

### 2.2 Enhanced DirectorResponse (`tools/models/intent.py`)

```python
class DirectorResponse(BaseModel):
    """Director 统一响应格式（增强版）。"""
    
    # 基础信息
    success: bool = Field(default=True, description="是否成功")
    message: str = Field(default="", description="主要响应消息")
    
    # 意图与工作流
    detected_intent: TaskIntent = Field(default=TaskIntent.UNKNOWN)
    detected_workflow: str = Field(default="", description="匹配的工作流ID")
    confidence: float = Field(default=0.0)
    
    # 工作流状态
    workflow_state: Optional[WorkflowState] = Field(default=None)
    current_phase: str = Field(default="", description="当前阶段名称")
    phase_progress: float = Field(default=0.0, description="阶段进度 0-1")
    
    # 执行结果
    tool_used: str = Field(default="")
    tool_result: Optional[Dict[str, Any]] = Field(default=None)
    
    # 交互支持
    follow_up_questions: List[str] = Field(default_factory=list)
    suggested_actions: List[Dict[str, str]] = Field(default_factory=list)
    
    # 阶段特定选项
    phase_options: List[Dict[str, str]] = Field(default_factory=list, description="当前阶段可选操作")
    
    # 会话
    session_id: str = Field(default="")
    session_state: str = Field(default="active")
    
    # 元数据
    reasoning: str = Field(default="")
```

---

## 3. WorkflowRegistry

### 3.1 New File: `tools/workflow_registry.py`

```python
"""Workflow Registry — 工作流注册表。

管理工作流定义，支持从 YAML 文件加载。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from tools.models.workflow import WorkflowDefinition, WorkflowPhase
from tools.models.intent import TaskIntent

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """工作流注册表。"""
    
    _instance: Optional["WorkflowRegistry"] = None
    
    def __new__(cls) -> "WorkflowRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._workflows: Dict[str, WorkflowDefinition] = {}
            cls._instance._intent_map: Dict[TaskIntent, List[str]] = {}
        return cls._instance
    
    def register(self, workflow: WorkflowDefinition) -> None:
        """注册工作流。"""
        self._workflows[workflow.workflow_id] = workflow
        
        # 建立意图映射
        for intent_str in workflow.trigger_intents:
            try:
                intent = TaskIntent(intent_str)
                if intent not in self._intent_map:
                    self._intent_map[intent] = []
                self._intent_map[intent].append(workflow.workflow_id)
            except ValueError:
                logger.warning("Unknown intent in workflow %s: %s", 
                             workflow.workflow_id, intent_str)
        
        logger.debug("Registered workflow: %s (intents: %s)", 
                    workflow.workflow_id, workflow.trigger_intents)
    
    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """获取工作流定义。"""
        return self._workflows.get(workflow_id)
    
    def get_workflows_for_intent(self, intent: TaskIntent) -> List[WorkflowDefinition]:
        """获取处理某意图的所有工作流。"""
        workflow_ids = self._intent_map.get(intent, [])
        workflows = [self._workflows[wid] for wid in workflow_ids if wid in self._workflows]
        # 按优先级排序
        return sorted(workflows, key=lambda w: -w.priority)
    
    def match_workflow(
        self, 
        intent: TaskIntent, 
        user_message: str,
        context: Dict[str, Any],
    ) -> Optional[WorkflowDefinition]:
        """匹配最适合的工作流。"""
        candidates = self.get_workflows_for_intent(intent)
        
        if not candidates:
            return None
        
        # 如果只有一个候选，直接返回
        if len(candidates) == 1:
            return candidates[0]
        
        # 根据关键词匹配度选择
        best_match = None
        best_score = -1
        
        for workflow in candidates:
            score = 0
            for kw in workflow.trigger_keywords:
                if kw in user_message:
                    score += 1
            
            # 检查前置条件
            if workflow.requires_outline and not context.get("has_outline"):
                continue
            if workflow.requires_novel_id and not context.get("novel_id"):
                continue
            
            if score > best_score:
                best_score = score
                best_match = workflow
        
        return best_match or candidates[0]
    
    def list_workflows(self, category: Optional[str] = None) -> List[WorkflowDefinition]:
        """列出所有工作流。"""
        workflows = list(self._workflows.values())
        if category:
            workflows = [w for w in workflows if w.category == category]
        return workflows
    
    def load_from_yaml(self, path: Path) -> int:
        """从 YAML 文件加载工作流定义。"""
        if not path.exists():
            logger.warning("Workflow config file not found: %s", path)
            return 0
        
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        count = 0
        for workflow_id, workflow_data in data.get("workflows", {}).items():
            try:
                # 解析阶段
                phases = []
                for phase_data in workflow_data.get("phases", []):
                    phases.append(WorkflowPhase(**phase_data))
                
                workflow_data["phases"] = phases
                workflow_data["workflow_id"] = workflow_id
                
                workflow = WorkflowDefinition(**workflow_data)
                self.register(workflow)
                count += 1
            except Exception as e:
                logger.error("Failed to load workflow %s: %s", workflow_id, e)
        
        logger.info("Loaded %d workflows from %s", count, path)
        return count


# 全局注册表实例
workflow_registry = WorkflowRegistry()
```

---

## 4. 内置工作流定义

### 4.1 `workflows/outline_creation.yaml`

```yaml
# 大纲创作工作流
workflows:
  outline_creation:
    name: 大纲创作
    description: 从零开始创建四级大纲（总纲→篇纲→节纲→章纲）
    category: outline
    priority: 10
    
    trigger_intents:
      - outline_assist
    trigger_keywords:
      - 创建大纲
      - 新建大纲
      - 从零开始
      - 构思
    
    requires_novel_id: true
    requires_outline: false
    
    entry_phase: master
    phases:
      - phase_id: master
        name: 总纲构思
        description: 确定全书核心框架
        available_tools:
          - outline_assist
        required_tools: []
        context_keys:
          - novel_id
        user_prompt: |
          让我们开始创建大纲。首先需要确定全书的核心框架：
        questions:
          - "书名是什么？"
          - "核心主题是什么？（一句话概括）"
          - "结局走向是怎样的？"
          - "有哪些关键转折点？"
        auto_advance: false
        next_phase: arcs
        
      - phase_id: arcs
        name: 篇纲规划
        description: 划分大剧情弧
        available_tools:
          - outline_assist
        context_keys:
          - novel_id
          - master_outline
        user_prompt: |
          总纲已确定。现在根据关键转折点划分篇纲：
        questions:
          - "全书计划分为几篇？"
          - "每篇的主要矛盾是什么？"
        auto_advance: false
        next_phase: sections
        
      - phase_id: sections
        name: 节纲细化
        description: 将篇纲细分为情节单元
        available_tools:
          - outline_assist
        context_keys:
          - novel_id
          - arcs
        user_prompt: |
          篇纲已规划。现在细化每个篇纲下的节纲：
        questions:
          - "每篇计划分为几节？"
          - "每节的关键事件是什么？"
        auto_advance: false
        next_phase: chapters
        
      - phase_id: chapters
        name: 章纲编写
        description: 为每节编写章节目标
        available_tools:
          - outline_assist
        context_keys:
          - novel_id
          - sections
          - characters
        user_prompt: |
          节纲已细化。现在为每节编写章纲：
        questions:
          - "每节计划几章？"
          - "每章的写作目标是什么？"
        auto_advance: false
        next_phase: review
        
      - phase_id: review
        name: 最终审核
        description: 检查大纲完整性
        available_tools:
          - outline_assist
          - lore_checker
        context_keys:
          - full_hierarchy
        user_prompt: |
          大纲已完成。进行最终审核：
        questions:
          - "关键转折点是否都有对应的章节？"
          - "伏笔埋设和回收点是否合理？"
          - "人物在各章节的分布是否合理？"
        auto_advance: true
        next_phase: null
```

### 4.2 `workflows/outline_modification.yaml`

```yaml
# 大纲修改工作流
workflows:
  outline_modification:
    name: 大纲修改
    description: 修改现有大纲
    category: outline
    priority: 5
    
    trigger_intents:
      - outline_assist
    trigger_keywords:
      - 修改大纲
      - 调整大纲
      - 删除
      - 移动
      - 合并
    
    requires_novel_id: true
    requires_outline: true
    
    entry_phase: identify
    phases:
      - phase_id: identify
        name: 识别修改点
        description: 确定要修改的内容
        available_tools:
          - outline_assist
        context_keys:
          - novel_id
          - current_hierarchy
        user_prompt: |
          请描述您想修改的大纲内容：
        questions:
          - "要修改哪个层级？（总纲/篇纲/节纲/章纲）"
          - "具体要修改什么内容？"
        auto_advance: false
        next_phase: assess
        
      - phase_id: assess
        name: 评估影响
        description: 分析修改的影响范围
        available_tools:
          - outline_assist
          - lore_checker
        context_keys:
          - novel_id
          - modification_plan
        user_prompt: |
          正在评估修改影响：
        questions:
          - "是否需要同步更新其他层级？"
          - "是否影响伏笔链？"
        auto_advance: true
        next_phase: execute
        
      - phase_id: execute
        name: 执行修改
        description: 应用修改
        available_tools:
          - outline_assist
        context_keys:
          - novel_id
          - impact_assessment
        user_prompt: |
          准备执行修改：
        questions:
          - "确认执行这些修改吗？"
        auto_advance: false
        next_phase: sync
        
      - phase_id: sync
        name: 同步更新
        description: 同步相关数据
        available_tools:
          - lore_checker
          - foreshadowing_manager
        context_keys:
          - novel_id
          - modifications
        user_prompt: |
          正在同步更新相关数据...
        auto_advance: true
        next_phase: null
```

### 4.3 `workflows/chapter_writing.yaml`

```yaml
# 章节写作工作流
workflows:
  chapter_writing:
    name: 章节写作
    description: 使用 Pipeline V2 生成章节
    category: writing
    priority: 10
    
    trigger_intents:
      - write_chapter
    trigger_keywords:
      - 写章节
      - 生成章节
      - 续写
      - 草稿
    
    requires_novel_id: true
    requires_outline: true
    
    entry_phase: prepare
    phases:
      - phase_id: prepare
        name: 准备上下文
        description: 组装生成上下文
        available_tools:
          - start_chapter_pipeline
        context_keys:
          - novel_id
          - chapter_outline
          - characters
          - foreshadowing
          - world
        user_prompt: |
          正在准备章节生成...
        questions:
          - "要生成哪个章节？"
          - "有什么特殊的写作目标吗？"
        auto_advance: false
        next_phase: generate
        
      - phase_id: generate
        name: 生成草稿
        description: Librarian 生成草稿
        available_tools:
          - librarian
        context_keys:
          - generation_context
        user_prompt: |
          正在生成章节草稿...
        auto_advance: true
        next_phase: review
        
      - phase_id: review
        name: 逻辑审查
        description: LoreChecker 检查一致性
        available_tools:
          - lore_checker
        context_keys:
          - draft
          - context
        user_prompt: |
          正在进行逻辑审查...
        auto_advance: true
        next_phase: user_confirm
        
      - phase_id: user_confirm
        name: 用户确认
        description: 等待用户审核
        available_tools: []
        context_keys:
          - draft
          - review_result
        user_prompt: |
          草稿已生成，请审核：
        questions:
          - "草稿是否符合预期？"
          - "需要进行修改吗？"
        auto_advance: false
        next_phase: polish
        
      - phase_id: polish
        name: 风格润色
        description: Stylist 润色（可选）
        available_tools:
          - stylist
        context_keys:
          - approved_draft
          - style_guide
        user_prompt: |
          是否进行风格润色？
        questions:
          - "是否启用文风处理？"
        auto_advance: false
        next_phase: null
```

### 4.4 `workflows/style_selection.yaml`

```yaml
# 文风选择工作流
workflows:
  style_selection:
    name: 文风选择
    description: 选择和合成风格文档
    category: style
    priority: 10
    
    trigger_intents:
      - style_compose
    trigger_keywords:
      - 选择风格
      - 合成风格
      - 文风设置
    
    requires_novel_id: true
    requires_outline: false
    
    entry_phase: select
    phases:
      - phase_id: select
        name: 选择风格
        description: 选择作者/作品风格
        available_tools:
          - style_query
        context_keys:
          - novel_id
          - available_styles
        user_prompt: |
          可用的风格模板：
        questions:
          - "要使用哪个风格模板？"
          - "是否参考特定作者风格？"
        auto_advance: false
        next_phase: compose
        
      - phase_id: compose
        name: 合成文档
        description: 合成三层风格文档
        available_tools:
          - style_composer
        context_keys:
          - novel_id
          - style_id
        user_prompt: |
          正在合成风格文档...
        auto_advance: true
        next_phase: review
        
      - phase_id: review
        name: 审核结果
        description: 查看合成结果
        available_tools:
          - style_profile
        context_keys:
          - composed_style
        user_prompt: |
          风格文档已合成：
        questions:
          - "风格文档是否符合预期？"
          - "需要调整吗？"
        auto_advance: false
        next_phase: null
```

---

## 5. Director Enhancement

### 5.1 Modified `tools/agents/director.py`

```python
# 新增方法

def detect_workflow(
    self,
    intent: IntentDecision,
    user_message: str,
    context: Dict[str, Any],
) -> Optional[WorkflowDefinition]:
    """检测最适合的工作流。"""
    from tools.workflow_registry import workflow_registry
    
    return workflow_registry.match_workflow(
        intent=intent.intent,
        user_message=user_message,
        context=context,
    )

def get_or_create_workflow_state(
    self,
    session: ConversationSession,
    workflow: WorkflowDefinition,
) -> WorkflowState:
    """获取或创建工作流状态。"""
    # 检查会话中是否已有工作流状态
    existing = session.context_data.get("workflow_state")
    if existing and existing.get("workflow_id") == workflow.workflow_id:
        return WorkflowState(**existing)
    
    # 创建新状态
    state = WorkflowState(
        workflow_id=workflow.workflow_id,
        current_phase=workflow.entry_phase,
        started_at=datetime.now().isoformat(),
    )
    return state

def get_current_phase_definition(
    self,
    workflow: WorkflowDefinition,
    state: WorkflowState,
) -> Optional[WorkflowPhase]:
    """获取当前阶段定义。"""
    for phase in workflow.phases:
        if phase.phase_id == state.current_phase:
            return phase
    return None

def advance_workflow(
    self,
    workflow: WorkflowDefinition,
    state: WorkflowState,
    phase_result: Dict[str, Any],
) -> Optional[str]:
    """推进工作流到下一阶段。"""
    current_phase = self.get_current_phase_definition(workflow, state)
    if not current_phase:
        return None
    
    # 保存阶段数据
    state.phase_data[state.current_phase] = phase_result
    
    # 检查转换条件
    next_phase_id = current_phase.next_phase
    
    # 条件转换
    for condition, target_phase in current_phase.conditions.items():
        if self._evaluate_condition(condition, phase_result):
            next_phase_id = target_phase
            break
    
    if next_phase_id:
        state.advance_to(next_phase_id)
        state.updated_at = datetime.now().isoformat()
        return next_phase_id
    
    # 工作流完成
    state.status = "completed"
    return None

def process_request_with_workflow(
    self,
    user_message: str,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> DirectorResponse:
    """使用工作流处理请求。"""
    # 1. 获取/创建会话
    session = self._get_or_create_session(session_id, context)
    
    # 2. 意图识别
    intent = self._classify_intent(user_message, session)
    
    # 3. 检测工作流
    workflow = self.detect_workflow(intent, user_message, session.context_data)
    
    if not workflow:
        # 无匹配工作流，使用默认处理
        return self._process_without_workflow(user_message, session, intent)
    
    # 4. 获取工作流状态
    workflow_state = self.get_or_create_workflow_state(session, workflow)
    
    # 5. 获取当前阶段
    current_phase = self.get_current_phase_definition(workflow, workflow_state)
    
    if not current_phase:
        return DirectorResponse(
            success=False,
            message="工作流状态异常",
            detected_workflow=workflow.workflow_id,
        )
    
    # 6. 执行阶段工具
    phase_result = self._execute_phase(
        current_phase,
        user_message,
        session.context_data,
        intent.tool_parameters,
    )
    
    # 7. 推进工作流
    next_phase = self.advance_workflow(workflow, workflow_state, phase_result)
    
    # 8. 构建响应
    response = self._build_workflow_response(
        workflow=workflow,
        state=workflow_state,
        current_phase=current_phase,
        phase_result=phase_result,
        next_phase=next_phase,
    )
    
    # 9. 更新会话
    self._update_session_with_workflow(session, workflow_state, response)
    
    return response

def _execute_phase(
    self,
    phase: WorkflowPhase,
    user_message: str,
    context: Dict[str, Any],
    parameters: Dict[str, Any],
) -> Dict[str, Any]:
    """执行阶段。"""
    result = {
        "user_message": user_message,
        "tools_called": [],
        "data": {},
    }
    
    # 加载所需上下文
    for key in phase.context_keys:
        if key not in context:
            context[key] = self._load_context(key, context.get("novel_id"))
    
    # 执行工具
    for tool_name in phase.required_tools:
        tool_result = registry.execute(tool_name, parameters, context)
        result["tools_called"].append(tool_name)
        result["data"][tool_name] = tool_result.model_dump()
    
    for tool_name in phase.available_tools:
        if tool_name not in phase.required_tools:
            # 可选工具，根据用户消息判断是否执行
            if self._should_call_tool(tool_name, user_message):
                tool_result = registry.execute(tool_name, parameters, context)
                result["tools_called"].append(tool_name)
                result["data"][tool_name] = tool_result.model_dump()
    
    return result

def _build_workflow_response(
    self,
    workflow: WorkflowDefinition,
    state: WorkflowState,
    current_phase: WorkflowPhase,
    phase_result: Dict[str, Any],
    next_phase: Optional[str],
) -> DirectorResponse:
    """构建工作流响应。"""
    # 计算进度
    total_phases = len(workflow.phases)
    current_index = next(
        (i for i, p in enumerate(workflow.phases) if p.phase_id == state.current_phase),
        0
    )
    progress = (current_index + 1) / total_phases if total_phases > 0 else 0
    
    # 获取下一个阶段信息
    next_phase_name = ""
    if next_phase:
        next_phase_def = next(
            (p for p in workflow.phases if p.phase_id == next_phase),
            None
        )
        next_phase_name = next_phase_def.name if next_phase_def else ""
    
    # 构建建议操作
    suggested_actions = []
    if next_phase:
        suggested_actions.append({
            "action": "continue",
            "label": f"继续：{next_phase_name}",
            "phase": next_phase,
        })
    else:
        suggested_actions.append({
            "action": "complete",
            "label": "完成工作流",
        })
    
    return DirectorResponse(
        success=True,
        message=current_phase.user_prompt,
        detected_workflow=workflow.workflow_id,
        workflow_state=state,
        current_phase=current_phase.name,
        phase_progress=progress,
        follow_up_questions=current_phase.questions,
        suggested_actions=suggested_actions,
        phase_options=self._build_phase_options(current_phase, phase_result),
        reasoning=f"工作流 {workflow.name}，阶段 {current_phase.name} ({progress:.0%})",
    )
```

---

## 6. Web API

### 6.1 New Endpoints

```python
# tools/web/__init__.py

@app.get("/api/workflows")
async def api_workflows_list():
    """列出所有可用工作流。"""
    from tools.workflow_registry import workflow_registry
    workflows = workflow_registry.list_workflows()
    return {
        "workflows": [
            {
                "id": w.workflow_id,
                "name": w.name,
                "description": w.description,
                "category": w.category,
                "phases": [p.name for p in w.phases],
            }
            for w in workflows
        ]
    }

@app.get("/api/workflows/{workflow_id}")
async def api_workflow_detail(workflow_id: str):
    """获取工作流详情。"""
    from tools.workflow_registry import workflow_registry
    workflow = workflow_registry.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return workflow.model_dump()

@app.post("/api/chat")
async def api_chat(payload: ChatRequest):
    """统一对话入口（支持工作流）。"""
    director = DirectorAgent(
        project_dir=proj,
        novel_id=payload.novel_id or novel_id,
    )
    
    response = director.process_request_with_workflow(
        user_message=payload.message,
        session_id=payload.session_id,
        context=payload.context,
    )
    
    return {
        "session_id": response.session_id,
        "response": response.model_dump(),
    }

@app.post("/api/workflows/{workflow_id}/start")
async def api_workflow_start(workflow_id: str, payload: dict):
    """手动启动特定工作流。"""
    from tools.workflow_registry import workflow_registry
    from tools.models.workflow import WorkflowState
    
    workflow = workflow_registry.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    director = DirectorAgent(
        project_dir=proj,
        novel_id=payload.get("novel_id", novel_id),
    )
    
    # 创建工作流状态
    state = WorkflowState(
        workflow_id=workflow_id,
        current_phase=workflow.entry_phase,
    )
    
    # 获取初始阶段
    first_phase = next(
        (p for p in workflow.phases if p.phase_id == workflow.entry_phase),
        None
    )
    
    return {
        "workflow": workflow.model_dump(),
        "state": state.model_dump(),
        "first_phase": first_phase.model_dump() if first_phase else None,
        "message": first_phase.user_prompt if first_phase else "",
        "questions": first_phase.questions if first_phase else [],
    }
```

---

## 7. 实现步骤

### Phase 1: 工作流模型（1天）
1. 创建 `tools/models/workflow.py`
2. 定义 `WorkflowDefinition`、`WorkflowPhase`、`WorkflowState`
3. 添加单元测试

### Phase 2: WorkflowRegistry（0.5天）
1. 创建 `tools/workflow_registry.py`
2. 实现工作流注册和匹配
3. 实现 YAML 加载

### Phase 3: 内置工作流配置（1天）
1. 创建 `workflows/` 目录
2. 编写 `outline_creation.yaml`
3. 编写 `outline_modification.yaml`
4. 编写 `chapter_writing.yaml`
5. 编写 `style_selection.yaml`

### Phase 4: Director 工作流集成（2天）
1. 添加 `detect_workflow()` 方法
2. 添加 `process_request_with_workflow()` 方法
3. 添加阶段执行逻辑
4. 添加工作流状态管理

### Phase 5: Web API（0.5天）
1. 添加工作流查询端点
2. 更新 `/api/chat` 端点
3. 添加工作流手动启动端点

### Phase 6: 测试与文档（0.5天）
1. 编写工作流集成测试
2. 更新 AGENTS.md
3. 运行完整测试套件

---

## 8. 文件变更汇总

| 文件 | 类型 | 描述 |
|------|------|------|
| `tools/models/workflow.py` | NEW | 工作流数据模型 |
| `tools/workflow_registry.py` | NEW | 工作流注册表 |
| `workflows/outline_creation.yaml` | NEW | 大纲创作工作流配置 |
| `workflows/outline_modification.yaml` | NEW | 大纲修改工作流配置 |
| `workflows/chapter_writing.yaml` | NEW | 章节写作工作流配置 |
| `workflows/style_selection.yaml` | NEW | 文风选择工作流配置 |
| `tools/agents/director.py` | MAJOR | 添加工作流支持 |
| `tools/web/__init__.py` | MODIFY | 添加工作流 API |
| `tests/test_workflow.py` | NEW | 工作流测试 |

---

## 9. 向后兼容性

- 现有 `DirectorAgent.plan()` 保持不变
- 现有 Pipeline V2 保持不变
- `/api/simulate/chapter` 端点保持不变
- 工作流是**可选**的增强功能
- 无工作流匹配时，回退到原有处理逻辑

---

## 10. 未来扩展

1. **自定义工作流**：用户可通过 YAML 创建自己的工作流
2. **工作流嵌套**：工作流可以调用其他工作流
3. **并行阶段**：支持同时执行多个阶段
4. **条件分支**：根据阶段结果选择不同的后续路径
5. **工作流模板市场**：分享和下载工作流模板
