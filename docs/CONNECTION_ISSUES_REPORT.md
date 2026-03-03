# OpenWrite Agent 衔接问题分析报告

## 执行时间
2026-03-02

## 测试方法
通过模拟 Director Agent 运行完整小说创作流程，测试各组件间的衔接。

---

## 发现的问题

### 🔴 严重问题 (必须修复)

#### 问题 1: 无 LLM 配置时系统完全无法工作

**位置**: `tools/agents/director_v2.py` 第 1018-1030 行

**现状**:
```python
# 2. 直接使用 LLM 处理所有请求，不做任何工作流拦截
if self._llm_client and self._router:
    response = self._generate_llm_response(user_message, session, context)
else:
    # 无 LLM 时返回提示
    response = DirectorResponse(
        success=True,
        message="LLM 未配置。请在 /settings 页面配置 API Key 后重试。",
        detected_intent=TaskIntent.GENERAL_CHAT,
        confidence=0.0,
        ...
    )
```

**问题**:
- `process_request` 完全依赖 LLM，当没有配置 LLM 时直接返回错误
- 即使有完整的 Skill 系统和规则引擎，无 LLM 也无法使用任何功能
- 注释说"不做任何工作流拦截"，这意味着 Skill 匹配逻辑被完全跳过

**影响**: 
- 用户必须配置 LLM 才能使用系统
- 与 AGENTS.md 中描述的"LLM 集成采用 Strangler Fig 模式：所有 Agent 保留规则引擎 fallback"不符

**修复建议**:
```python
def process_request(self, user_message, session_id=None, context=None):
    # 1. 获取/创建会话
    session = self._get_or_create_session(session_id, context)
    session.add_message("user", user_message)
    
    # 2. 尝试 Skill 匹配（规则引擎 fallback）
    matched_skill = self.skill_registry.match_trigger(user_message)
    
    if matched_skill:
        # 有匹配的 Skill，执行工作流
        intent = IntentDecision(
            intent=self._map_skill_to_intent(matched_skill.name),
            tool_parameters={"skill": matched_skill.name},
        )
        workflow_info = self._detect_workflow(intent, user_message, context)
        if workflow_info:
            response = self._execute_workflow(workflow_info, user_message, session, intent, context)
        else:
            response = self._execute_skill_fallback(matched_skill, user_message, session, context)
    elif self._llm_client and self._router:
        # 无 Skill 匹配，使用 LLM
        response = self._generate_llm_response(user_message, session, context)
    else:
        # 无 LLM 也无 Skill 匹配
        response = DirectorResponse(
            success=True,
            message="无法识别您的请求。请尝试使用特定指令，如「写第1章」「创建大纲」「初始化项目」等。",
            detected_intent=TaskIntent.UNKNOWN,
            ...
        )
```

---

#### 问题 2: ToolExecutor 代码损坏（已修复）

**位置**: `skills/tools/executor.py` 第 564-605 行

**现状**: 文件中有重复的、不完整的函数定义片段，导致语法错误

**修复**: 已删除重复代码

---

### 🟡 中等问题

#### 问题 3: 部分 Skill 缺少 trigger 命令

**位置**: 各 Skill 的 SKILL.md

**现状**:
| Skill | trigger | 匹配测试 |
|-------|---------|---------|
| outline | `/outline` | ✅ 匹配 |
| writing | `/write` | ✅ 匹配 |
| style | `/style` | ✅ 匹配 |
| project | `/project` | ✅ 匹配 |
| character | `None` | ❌ `/character` 不匹配 |
| world | `None` | ❌ `/world` 不匹配 |
| foreshadowing | `None` | ❌ `/foreshadowing` 不匹配 |

**修复建议**: 为 character、world、foreshadowing 添加 trigger 命令

```yaml
# skills/character/SKILL.md
trigger: /character

# skills/world/SKILL.md
trigger: /world

# skills/foreshadowing/SKILL.md
trigger: /foreshadowing
```

---

#### 问题 4: Skill 触发词覆盖不全

**位置**: 各 Skill 的 `triggers` 字段

**测试结果**:
| 用户输入 | 期望匹配 | 实际匹配 |
|---------|---------|---------|
| "新建角色 艾伦" | character | ❌ 未匹配 |
| "创建一个魔法师角色" | character | ❌ 未匹配 |
| "/character" | character | ❌ 未匹配 |

**修复建议**: 扩展 triggers 列表

```yaml
# skills/character/SKILL.md
triggers:
  - "创建角色"
  - "添加角色"
  - "新建角色"  # 已有
  - "新建人物"
  - "创建人物"  # 新增
  - "添加人物"  # 新增
  - "角色"      # 新增（单关键词）
```

---

#### 问题 5: 多数 Skill 缺少工作流定义

**位置**: `skills/*/workflows/` 目录

**现状**:
| Skill | 工作流 | 状态 |
|-------|--------|------|
| outline | `create.yaml` | ✅ 有 |
| writing | `chapter_writing.yaml` | ✅ 有 |
| character | 无 | ❌ 缺失 |
| world | 无 | ❌ 缺失 |
| foreshadowing | 无 | ❌ 缺失 |
| style | 无 | ❌ 缺失 |
| project | 无 | ❌ 缺失 |

**影响**: Director 的 `_detect_workflow` 和 `_execute_workflow` 方法需要工作流定义才能正确执行

**修复建议**: 为每个 Skill 创建基础工作流定义

---

#### 问题 6: ToolExecutor 查询返回格式不一致

**位置**: `skills/tools/executor.py` 各 `_query_*` 方法

**现状**:
```python
# 有时返回友好消息
return {"message": "暂无大纲，可以创建新大纲..."}

# 有时返回错误
return {"error": "Characters directory not found"}

# 有时返回 None
return {"success": True, "result": None}
```

**问题**: 前端和其他 Agent 无法统一处理这些不同格式的响应

**修复建议**: 统一返回格式
```python
def _query_outline(self, chapter_id=None, arc_id=None):
    if not self.novel_id:
        return {
            "success": False,
            "error": "novel_id_not_set",
            "message": "请先设置项目"
        }
    
    if not outline_path.exists():
        return {
            "success": True,
            "data": None,
            "message": "暂无大纲"
        }
    
    return {
        "success": True,
        "data": data
    }
```

---

### 🟢 轻微问题

#### 问题 7: _novel_data_path 返回类型不一致

**位置**: `skills/tools/executor.py` 第 175-194 行

**现状**: 
```python
def _novel_data_path(self, *parts: str) -> Path:
    if not self.novel_id:
        return {"error": "..."}  # 返回 dict
        return {"message": "..."}  # 返回 dict
    
    path = self.project_root / "data" / "novels" / self.novel_id  # 返回 Path
    return path
```

**问题**: 函数签名说返回 `Path`，但实际可能返回 `dict`

**修复建议**:
```python
def _novel_data_path(self, *parts: str) -> Path:
    if not self.novel_id:
        raise ValueError("novel_id 未设置，请先初始化项目")
    
    path = self.project_root / "data" / "novels" / self.novel_id
    for part in parts:
        path = path / part
    return path
```

---

#### 问题 8: DirectorResponse 的 detected_intent 序列化问题

**位置**: `tools/models/intent.py`

**现状**: 
```python
detected_intent: TaskIntent = Field(default=TaskIntent.UNKNOWN)
```

**问题**: `TaskIntent` 是 Enum，序列化后是 `<TaskIntent.WRITE_CHAPTER: 'write_chapter'>` 而非简单的字符串

**修复建议**:
```python
detected_intent: str = Field(default="unknown")

# 或者在 model_dump 时处理
def model_dump(self, **kwargs):
    data = super().model_dump(**kwargs)
    data["detected_intent"] = self.detected_intent.value
    return data
```

---

## WebUI 与后端衔接分析

### 前端期望的响应格式

从 `chat.html` 分析，前端期望：

```javascript
// 第 277-291 行
api.post('/api/chat', {...}).then(function(response) {
    if (response.session_id) sessionId = response.session_id;
    
    updateWorkflowUI(response);  // 需要 detected_workflow, workflow_state, current_phase, phase_progress
    
    addMessage('agent', response.message, response);  // 需要 message
    
    if (response.tool_result && response.tool_result.content) {
        editorArea.value = response.tool_result.content;  // 需要 tool_result.content
    }
    
    showSuggestions(response.suggested_actions);  // 需要 suggested_actions 数组
});
```

### 衔接问题

1. **workflow_state 始终为 None**: 因为 Director 跳过了工作流执行路径
2. **tool_result 未填充**: 因为 `_execute_xxx_workflow` 方法未被调用
3. **suggested_actions 为空**: 同上

---

## 修复优先级

| 优先级 | 问题 | 预计工作量 |
|--------|------|-----------|
| P0 | 问题 1: 无 LLM 时系统无法工作 | 2-3 小时 |
| P1 | 问题 3: 部分 Skill 缺少 trigger | 30 分钟 |
| P1 | 问题 4: 触发词覆盖不全 | 1 小时 |
| P2 | 问题 5: 缺少工作流定义 | 3-4 小时 |
| P2 | 问题 6: 查询返回格式不一致 | 1-2 小时 |
| P3 | 问题 7: 返回类型不一致 | 30 分钟 |
| P3 | 问题 8: Enum 序列化 | 30 分钟 |

---

## 建议的修复顺序

1. **先修复问题 1**（核心）：修改 `process_request` 使其支持规则引擎 fallback
2. **修复问题 3 和 4**：完善 Skill 触发器定义
3. **修复问题 5**：为关键 Skill 添加工作流定义
4. **修复问题 6**：统一 ToolExecutor 返回格式
5. **修复问题 7 和 8**：代码质量改进

---

## 测试验证

修复后应运行以下测试：

```bash
# 1. 运行单元测试
python3 -m pytest -q

# 2. 运行衔接测试
python3 test_director_flow.py

# 3. 启动 Web 服务测试
python3 -m tools.web
# 然后在浏览器中测试完整流程
```

---

*报告生成时间: 2026-03-02*
