# OpenWrite 架构重构规划文档

> 创建时间: 2026-03-01
> 最后更新: 2026-03-01
> 状态: 规划中

---

## 一、用户确认的决策

### 1. 迁移策略
- **决定**: 完全重构
- **要求**: 设计好施工流程，避免重复施工与忘记施工

### 2. 向后兼容
- **决定**: 功能不丢失即可，接口可以变化

### 3. 主 AI 提示词格式
- **决定**: 选择可扩展性高的方案（多文件组合 + 模板系统）

---

## 二、Agent 分组方案

### 已确认的分组

| Skill | 包含 Agent | 说明 |
|-------|-----------|------|
| `writing/` | Librarian + LoreChecker + Stylist | 章节写作 |
| `outline/` | Director（大纲相关路由） | 大纲编辑 |
| `style/` | Reader + StyleDirector + Stylist | 风格系统 |
| `project/` | Initializer + Director（项目管理） | 项目管理 |

---

## 三、风格系统设计（关键决策）

### 3.1 用户的核心理念

> "不能直接用某个小说的风格，应该设计提示词工程，在初始化项目之后在小说前期工程（大纲+世界观构建）的时候通过问询，根据作者的喜好与现有的提取好的风格进行初始化，这样每个作品都有专属的风格"

### 3.2 风格文件分类

#### 共享层（跨作品通用）

| 文件类型 | 说明 | 示例内容 |
|----------|------|----------|
| **文本人化文件** | 去 AI 味规则 | 禁用词库、自然不完美规则 |
| **套路文件** | 通用叙事套路 | "巨人逼近"、"先甜后打脸"等 |
| **技法文件** | 写作技法 | 对话格式、节奏控制、动作穿插 |

#### 作品专属层（每部作品独立生成）

| 文件类型 | 说明 | 生成方式 |
|----------|------|----------|
| **风格指纹** | 核心风格 DNA | 初始化时通过问询生成 |
| **声音设定** | 叙述者声音 | 基于作者喜好选择 |
| **节奏偏好** | 段落/章节长度 | 从参考作品或问答确定 |

### 3.3 风格初始化流程

```
┌─────────────────────────────────────────────────────────┐
│                   风格初始化流程                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Step 1: 项目初始化                                      │
│  ├─ 用户创建新项目                                        │
│  └─ 系统加载共享层（人化文件 + 套路 + 技法）               │
│                                                         │
│  Step 2: 风格问询                                        │
│  ├─ Q1: 叙述风格偏好？（轻松/严肃/幽默/悬疑）              │
│  ├─ Q2: 节奏偏好？（快节奏/慢节奏/混合）                   │
│  ├─ Q3: 对话风格？（多对话/多描写/平衡）                   │
│  ├─ Q4: 参考作品？（可选，从 styles/ 选择或跳过）          │
│  └─ Q5: 特殊要求？（自定义约束）                          │
│                                                         │
│  Step 3: 风格合成                                        │
│  ├─ 基于问询结果选择模板                                  │
│  ├─ 如有参考作品，提取风格特征                             │
│  ├─ 合并共享层 + 专属设定                                 │
│  └─ 生成 novels/{id}/style/fingerprint.md               │
│                                                         │
│  Step 4: 验证与调整                                      │
│  ├─ 生成测试段落                                         │
│  ├─ 用户确认或调整                                        │
│  └─ 保存最终风格配置                                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 3.4 风格文件格式（基于研究结果）

**推荐格式**: YAML（准确率最高 62.1%）

```yaml
# novels/{novel_id}/style/fingerprint.yaml

meta:
  name: "作品专属风格"
  created_at: "2026-03-01"
  source: "问询生成 + 参考《术师手册》"

# 核心风格（从问询生成）
core:
  tone: "轻松幽默"           # 从问询 Q1
  pacing: "快节奏"           # 从问询 Q2
  dialogue_ratio: 0.45       # 从问询 Q3
  
# 参考作品特征（如有）
reference_style:
  source: "术师手册"
  adopted_features:
    - "吐槽密度高"
    - "现代感语言"
    - "表里不一角色塑造"
    
# 共享层引用
shared_craft:
  humanization: "@craft/humanization.yaml"
  tropes: "@craft/tropes/narrative.yaml"
  dialogue: "@craft/dialogue_craft.yaml"
```

---

## 四、工具执行系统（Executor）设计

### 4.1 现状分析

根据代码搜索结果：
- `Director._execute_tool()` 是**占位符**，返回 `{"status": "simulated"}`
- Agent 可以**自由读取文件**（通过 `tools/queries/` 或直接 `Path.read_text()`）
- 没有统一的**工具注册机制**

### 4.2 用户需求

> "话说现在本项目有 excutor 类似的东西吗，agent 能不能自由的查询文件？（我希望有）"

### 4.3 设计方案

```python
# skills/tools/executor.py

class ToolExecutor:
    """统一的工具执行器"""
    
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = project_root
        self.novel_id = novel_id
        self._tools: Dict[str, Callable] = {}
        self._register_builtin_tools()
    
    def _register_builtin_tools(self):
        """注册内置工具"""
        self.register("read_file", self._read_file)
        self.register("write_file", self._write_file)
        self.register("list_files", self._list_files)
        self.register("search_content", self._search_content)
        self.register("query_outline", self._query_outline)
        self.register("query_characters", self._query_characters)
        self.register("query_world", self._query_world)
        self.register("query_foreshadowing", self._query_foreshadowing)
    
    def register(self, name: str, handler: Callable):
        """注册工具"""
        self._tools[name] = handler
    
    def execute(self, tool_name: str, parameters: dict) -> dict:
        """执行工具"""
        if tool_name not in self._tools:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
        
        try:
            result = self._tools[tool_name](**parameters)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # --- 内置工具实现 ---
    
    def _read_file(self, path: str) -> str:
        """读取文件"""
        # 安全检查：只允许访问项目目录
        full_path = self._resolve_path(path)
        if not self._is_safe_path(full_path):
            raise PermissionError(f"Access denied: {path}")
        return full_path.read_text(encoding="utf-8")
    
    def _list_files(self, directory: str, pattern: str = "*") -> list:
        """列出文件"""
        full_path = self._resolve_path(directory)
        return [str(p.relative_to(self.project_root)) for p in full_path.glob(pattern)]
    
    def _search_content(self, query: str, scope: str = "all") -> list:
        """搜索内容"""
        # 实现内容搜索
        pass
```

### 4.4 工具能力清单

| 工具名 | 功能 | 权限 |
|--------|------|------|
| `read_file` | 读取任意文件 | 项目目录内 |
| `write_file` | 写入文件 | data/novels/{id}/ 内 |
| `list_files` | 列出目录 | 项目目录内 |
| `search_content` | 搜索内容 | 项目目录内 |
| `query_outline` | 查询大纲 | 只读 |
| `query_characters` | 查询角色 | 只读 |
| `query_world` | 查询世界观 | 只读 |
| `query_foreshadowing` | 查询伏笔 | 只读 |

---

## 五、新架构目录结构

```
openwrite/
├── skills/                          # 功能模块目录
│   ├── __init__.py
│   ├── skill.py                     # Skill 数据模型
│   ├── skill_registry.py            # 功能注册表
│   ├── skill_loader.py              # 功能加载器
│   │
│   ├── tools/                       # 共享工具层
│   │   ├── __init__.py
│   │   ├── executor.py              # 工具执行器
│   │   ├── file_ops.py              # 文件操作
│   │   └── queries.py               # 查询接口
│   │
│   ├── outline/                     # 大纲编辑功能
│   │   ├── SKILL.md
│   │   ├── prompts/
│   │   ├── tools/
│   │   └── workflows/
│   │
│   ├── writing/                     # 章节写作功能
│   │   ├── SKILL.md
│   │   ├── prompts/
│   │   ├── tools/
│   │   ├── workflows/
│   │   └── templates/
│   │       ├── beat_templates.yaml
│   │       └── section_markers.yaml
│   │
│   ├── character/                   # 角色管理
│   ├── world/                       # 世界观
│   ├── foreshadowing/               # 伏笔管理
│   │
│   └── style/                       # 风格系统（重点）
│       ├── SKILL.md
│       ├── prompts/
│       │   ├── extract_style.md     # 风格提取
│       │   ├── initialize_style.md  # 风格初始化问询
│       │   └── compose_style.md     # 风格合成
│       ├── tools/
│       │   ├── style_initializer.py # 风格初始化器
│       │   ├── style_extractor.py   # 风格提取器
│       │   └── style_composer.py    # 风格合成器
│       └── workflows/
│           ├── initialize.yaml      # 初始化工作流
│           └── iterate.yaml         # 迭代工作流
│
├── craft/                           # 共享技法层（只读参考）
│   ├── humanization.yaml            # 文本人化规则（去AI味）
│   ├── tropes/                      # 叙事套路
│   │   ├── conflict.yaml
│   │   ├── revelation.yaml
│   │   └── transformation.yaml
│   ├── dialogue_craft.md            # 对话技法
│   ├── language_craft.md            # 语言风格
│   └── ...
│
├── styles/                          # 作者/作品风格（只读参考）
│   └── {style_id}/
│       ├── fingerprint.md
│       └── ...
│
├── core/                            # 核心系统
│   ├── director.py                  # 主控 Agent
│   ├── llm/
│   ├── models/
│   └── utils/
│
├── data/                            # 数据目录
│   └── novels/{novel_id}/
│       ├── outline/
│       ├── characters/
│       ├── world/
│       ├── foreshadowing/
│       ├── manuscript/
│       └── style/                   # 作品专属风格
│           ├── fingerprint.yaml     # 风格指纹
│           ├── voice.yaml           # 声音设定
│           └── constraints.yaml     # 硬性约束
│
├── config/
│   ├── main_prompt.md               # 主 AI 提示词模板
│   ├── style_questions.yaml         # 风格初始化问询问题
│   └── llm_config.yaml
│
└── web/
```

---

## 六、分阶段施工计划

### Phase 1: 基础设施（1-2天）

**目标**: 建立骨架，不破坏现有功能

**任务清单**:
- [ ] 创建 `skills/` 目录结构
- [ ] 实现 `Skill`, `SkillRegistry`, `SkillLoader`
- [ ] 实现 `ToolExecutor`（核心需求）
- [ ] 创建 `config/main_prompt.md` 模板
- [ ] 创建 `config/style_questions.yaml`（风格问询问题）
- [ ] 测试：工具执行器能正常工作

**验证命令**:
```bash
python3 -c "from skills import SkillLoader; r = SkillLoader().load_all(); print(len(r.list_all()))"
python3 -c "from skills.tools import ToolExecutor; e = ToolExecutor(); print(e.execute('read_file', {'path': 'test.md'}))"
```

### Phase 2: 风格系统（2-3天）

**目标**: 实现用户核心需求——风格初始化

**任务清单**:
- [ ] 创建 `skills/style/` 完整结构
- [ ] 实现 `StyleInitializer`（问询 + 生成）
- [ ] 实现 `StyleExtractor`（从参考作品提取）
- [ ] 实现 `StyleComposer`（合成共享层 + 专属层）
- [ ] 创建 `craft/humanization.yaml`（去AI味规则）
- [ ] 创建 `craft/tropes/` 套路库
- [ ] 测试：风格初始化流程能完整执行

**验证命令**:
```bash
python3 -c "from skills.style import StyleInitializer; ..."
```

### Phase 3: 大纲功能迁移（2天）

**任务清单**:
- [ ] 迁移 `parsers/outline_md_parser.py`
- [ ] 迁移 `utils/outline_md_serializer.py`
- [ ] 创建大纲相关 prompts
- [ ] 迁移工作流 YAML
- [ ] 测试：现有大纲测试通过

### Phase 4: 写作功能迁移（2-3天）

**任务清单**:
- [ ] 迁移节拍生成逻辑
- [ ] 外部化 `BEAT_TEMPLATES` → YAML
- [ ] 外部化 `SECTION_MARKERS` → YAML
- [ ] 创建写作相关 prompts
- [ ] 测试：Pipeline V2 测试通过

### Phase 5: Director 重构（2天）

**任务清单**:
- [ ] 重写意图识别使用 SkillRegistry
- [ ] 重写工具调用使用 ToolExecutor
- [ ] 更新主 AI 提示词加载
- [ ] 测试：Director 测试通过

### Phase 6: 其他功能 + 清理（2-3天）

**任务清单**:
- [ ] 迁移角色、世界观、伏笔功能
- [ ] 删除旧代码（保留 fallback）
- [ ] 更新文档
- [ ] 全量测试

---

## 七、关键文件引用

### 现有风格系统文件
- `/Users/jiaoziang/Openwrite/styles/术师手册/fingerprint.md` - 风格指纹示例
- `/Users/jiaoziang/Openwrite/craft/dialogue_craft.md` - 对话技法
- `/Users/jiaoziang/Openwrite/craft/language_craft.md` - 语言风格
- `/Users/jiaoziang/Openwrite/docs/prompts/COMPOSE_RULES.md` - 合成规则

### 现有代码文件
- `/Users/jiaoziang/Openwrite/tools/agents/director.py` - 主控 Agent
- `/Users/jiaoziang/Openwrite/tools/agents/librarian.py` - 写手 Agent
- `/Users/jiaoziang/Openwrite/tools/agents/reader.py` - 风格提取
- `/Users/jiaoziang/Openwrite/tools/agents/style_director.py` - 风格迭代

---

## 八、待确认问题

1. **风格问询问题数量**: 5 个问题是否足够？是否需要更细的维度？
2. **共享技法库来源**: 直接使用现有的 `craft/` 还是重新整理？
3. **Web 界面集成**: 风格初始化是否需要 Web UI？

---

## 九、变更日志

| 日期 | 变更内容 |
|------|----------|
| 2026-03-01 | 初始创建，记录用户决策和架构设计 |
