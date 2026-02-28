# OpenWrite — AI 辅助小说创作系统

## 项目概述

CLI + Web 驱动的多 Agent 协作小说创作系统。Python + Pydantic + FastAPI + Typer + Rich。

## 技术栈

- Python 3.14+
- Pydantic v2（数据模型）
- FastAPI + Jinja2（Web 应用）
- Typer（CLI 框架）
- Rich（终端输出）
- NetworkX（图结构）
- PyYAML（配置/数据）
- LiteLLM（多模型 LLM 网关，opt-in）

---

## 构建与测试命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行全部测试（230 tests expected）
python3 -m pytest -q

# 运行单个测试文件
python3 -m pytest tests/test_style_system.py -v

# 运行单个测试函数
python3 -m pytest tests/test_llm.py::test_router_get_routes -v

# 运行带覆盖率报告
python3 -m pytest --cov=tools --cov-report=term-missing

# CLI 入口
python3 -m tools.cli --help

# 启动 Web 应用
python3 -m tools.web
# 访问 http://localhost:8000
```

---

## 项目结构约定

```
tools/              # Python 源码
  agents/           # Agent 实现（Director, Librarian, LoreChecker, Stylist, Reader, StyleDirector, Simulator, Initializer）
  models/           # Pydantic 数据模型（outline, character, style, context_package）
  utils/            # 工具函数（StyleComposer, ProgressiveCompressor, OutlineMdSerializer）
  parsers/          # Markdown 解析器（OutlineMdParser）
  graph/            # 图结构（ForeshadowingDAG, WorldGraph）
  checks/           # 逻辑检查
  queries/          # 查询接口
  cli.py            # CLI 入口（Typer app）
  llm/              # LLM 集成层（LiteLLM 封装、多模型路由、Prompt 模板）
  web/              # Web 应用（FastAPI + Jinja2 模板）
tests/              # pytest 测试
craft/              # 通用写作技法（跨作品）
styles/{作品名}/    # 作者/作品风格指纹
novels/{作品名}/    # 作品设定（硬性约束）
data/novels/{id}/   # 运行时数据（outline/, characters/, manuscript/, world/, foreshadowing/）
docs/               # 文档
```

---

## 编码规范

### 类型注解
- 所有函数签名**必须**有 type hints
- 使用 `Optional[T]` 而非 `T | None`（兼容 Python 3.9）
- 使用 `list[T]` 而非 `List[T]`（Python 3.9+）

### 数据模型
- 使用 Pydantic `BaseModel`，不用 `dataclass`
- 字段必须有类型注解和默认值或 `Field()`
- 使用 `Field(default_factory=list)` 处理可变默认值

### 错误处理
- **禁止**空 catch 块：`except Exception: pass`
- **禁止**类型抑制：`# type: ignore`
- **禁止**任意类型：`as any`
- 使用具体异常类型，提供有意义的错误消息

### 导入顺序
```python
# 1. 标准库
from pathlib import Path
from typing import Dict, List, Optional

# 2. 第三方库
import yaml
from pydantic import BaseModel, Field

# 3. 本地模块
from tools.models.outline import OutlineHierarchy
```

### 文档字符串
- 中文，Google style
- 模块级文档在文件开头
- 类和公共方法必须有 docstring

```python
def generate_chapter(self, chapter_id: str, context: Dict[str, str]) -> str:
    """生成章节草稿。
    
    Args:
        chapter_id: 章节标识符
        context: 上下文信息字典
    
    Returns:
        生成的章节文本
    """
```

### 命名约定
- 文件名：snake_case（`outline_md_parser.py`）
- 类名：PascalCase（`OutlineHierarchy`）
- 函数/方法：snake_case（`parse_outline_md`）
- 常量：UPPER_SNAKE_CASE（`RECENT_TEXT_MAX = 1000`）
- 私有方法：_leading_underscore（`_extract_yaml_block`）

---

## Agent 架构

### 协作关系图

```
用户请求
    │
    ▼
Director ──────► 路由决策 + 上下文组装
    │
    ▼
Librarian ─────► 节拍生成 + 草稿写作
    │
    ▼
LoreChecker ───► 逻辑审查 + 跨章节一致性
    │
    ▼
User Review ───► 人工审核确认（Pipeline V2）
    │
    ▼
Stylist ───────► 风格润色（可选）
```

### Agent 职责

| Agent | 职责 | 文件 |
|-------|------|------|
| Director | 调度决策、路由、风格感知指令 | `director.py` |
| Librarian | 节拍生成、草稿写作 | `librarian.py` |
| LoreChecker | 逻辑审查、跨章节一致性 | `lore_checker.py` |
| Stylist | AI 痕迹检测、风格评分 | `stylist.py` |
| Reader | 批量阅读、风格抽取 | `reader.py` |
| StyleDirector | 差异分析、收敛追踪 | `style_director.py` |
| Initializer | 项目初始化 | `initializer.py` |
| Pipeline V2 | 带人工审核的完整流程 | `pipeline_v2.py` |

---

## Web 应用路由

| 路由 | 功能 | 模板 |
|------|------|------|
| `/` | 仪表盘 | `dashboard.html` |
| `/novels/new` | 新建项目 | `novel_new.html` |
| `/outline` | 大纲编辑器 | `outline_editor.html` |
| `/editor` | 章节编辑器 + AI 助手 | `editor.html` |
| `/characters` | 人物管理 | `characters.html` |
| `/world` | 世界观图谱 | `world.html` |
| `/foreshadowing` | 伏笔 DAG | `foreshadowing.html` |
| `/style` | 风格分析 | `style.html` |
| `/timeline` | 叙事时间线 | `timeline.html` |
| `/settings` | LLM 配置 | `settings.html` |

---

## 三层风格架构

优先级：`用户偏好覆盖 > 作品设定（硬性约束）> 作品风格（核心约束）> 通用技法（可选参考）`

| 层级 | 目录 | 约束力 |
|------|------|--------|
| 通用技法 | `craft/` | 可选参考 |
| 作品风格 | `styles/{作品}/` | 应当遵循 |
| 作品设定 | `novels/{作品}/` | 不可违反 |

---

## LLM 配置

### 多模型池配置（`llm_config.yaml`）

```yaml
enabled: true
models:
  Claude-Opus-4.6:
    model: claude-opus-4-6
    api_base: https://aws.d68.fun/v1/messages
    api_key_env: CLAUDE_API_KEY
    max_tokens: 80000
  Kimi-K2.5:
    model: kimi-k2.5
    api_base: https://api.moonshot.cn/v1/chat/completions
    api_key_env: KIMI_API_KEY
    max_tokens: 16000

routes:
  reasoning:    # Director 决策
    models: [Claude-Opus-4.6, GLM-4.7, DeepSeek]
    primary_index: 0
  generation:   # Writer 生成
    models: [Kimi-K2.5, MiniMax-M2.5, ChatGPT-5.3]
    primary_index: 0
```

### 环境变量设置

```bash
export KIMI_API_KEY=sk-xxx
export CLAUDE_API_KEY=sk-xxx
# ... 其他模型
```

---

## 注意事项

- 修改 Agent 后**必须**运行 `python3 -m pytest -q` 确认 230 tests 全部通过
- 不要删除或修改 `craft/`、`styles/`、`novels/` 下的 `.md` 数据文件
- CLI 命令注册在 `tools/cli.py` 的 Typer sub-app 中
- Web API 端点在 `tools/web/__init__.py`
- LLM 集成采用 Strangler Fig 模式：所有 Agent 保留规则引擎 fallback
- API key 通过环境变量注入，不存储在配置文件中
- `.env` 文件已添加到 `.gitignore`，不会泄露 API keys
