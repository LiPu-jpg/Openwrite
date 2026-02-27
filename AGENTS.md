# OpenWrite — AI 辅助小说创作系统

## 项目概述

CLI 驱动的多 Agent 协作小说创作系统。Python + Pydantic + Typer + Rich。

## 技术栈

- Python 3.10+
- Pydantic v2（数据模型）
- Typer（CLI 框架）
- Rich（终端输出）
- NetworkX（图结构）
- PyYAML（配置/数据）
- LiteLLM（多模型 LLM 网关，opt-in）

## 构建与测试

```bash
# 安装依赖
pip install -r requirements.txt

# 运行全部测试（84 tests expected）
python3 -m pytest -q

# 运行单个测试文件
python3 -m pytest tests/test_style_system.py -v

# CLI 入口
python3 -m tools.cli --help
```

## 项目结构约定

```
tools/              # Python 源码
  agents/           # Agent 实现（Director, Librarian, LoreChecker, Stylist, Reader, StyleDirector, Simulator）
  models/           # Pydantic 数据模型
  utils/            # 工具函数（StyleComposer, ContextCompressor）
  parsers/          # Markdown 解析器
  graph/            # 图结构（伏笔 DAG）
  checks/           # 逻辑检查
  queries/          # 查询接口
  cli.py            # CLI 入口（Typer app）
  llm/              # LLM 集成层（LiteLLM 封装、多模型路由、Prompt 模板）
tests/              # pytest 测试
craft/              # 通用写作技法（跨作品）
styles/{作品名}/    # 作者/作品风格指纹
novels/{作品名}/    # 作品设定（硬性约束）
composed/           # 风格合成输出
data/               # 运行时数据
docs/               # 文档
```

## 编码规范

- 类型注解：所有函数签名必须有 type hints
- 数据模型：使用 Pydantic BaseModel，不用 dataclass
- 错误处理：不允许空 catch 块，不允许 `# type: ignore`
- 导入顺序：stdlib → third-party → local
- 文档字符串：中文，Google style
- 测试：pytest，文件名 `test_*.py`，函数名 `test_*`

## Agent 架构

管线流程：`Director.plan()` → `Librarian.generate_chapter()` → `LoreChecker.check_draft()` → `Stylist.polish()`（可选）→ `Reader + StyleDirector`（可选后分析）

所有 Agent 支持 opt-in LLM 模式：传入 `llm_client` + `router` 时使用 LLM，否则保持规则模拟。
LLM 调用失败时自动 fallback 到规则引擎，保证管线不中断。

## 三层风格架构

优先级：`用户偏好覆盖 > 作品设定（硬性约束）> 作品风格（核心约束）> 通用技法（可选参考）`

| 层级 | 目录 | 约束力 |
|------|------|--------|
| 通用技法 | `craft/` | 可选参考 |
| 作品风格 | `styles/{作品}/` | 应当遵循 |
| 作品设定 | `novels/{作品}/` | 不可违反 |

## 关键文件速查

| 文件 | 职责 | 行数 |
|------|------|------|
| `tools/cli.py` | CLI 入口，所有命令 | ~745 |
| `tools/agents/simulator.py` | 全流程编排 | 403 |
| `tools/agents/director.py` | 上下文压缩 + 路由 | 231 |
| `tools/agents/librarian.py` | 节拍生成 + 草稿 | 565 |
| `tools/agents/lore_checker.py` | 逻辑审查 + 跨章节 | 330+ |
| `tools/agents/stylist.py` | AI 痕迹检测 + 评分 | 418 |
| `tools/agents/reader.py` | 批量阅读 + 抽取 | 668 |
| `tools/agents/style_director.py` | 差异分析 + 收敛 | 705 |
| `tools/models/style.py` | StyleProfile 模型 | 353 |
| `tools/utils/style_composer.py` | 三层合成器 | 288 |
| `tools/utils/context_compressor.py` | 上下文压缩 | 228 |
| `tools/llm/client.py` | LiteLLM 封装 + 重试/fallback | 194 |
| `tools/llm/router.py` | 任务类型路由器 | 97 |
| `tools/llm/config.py` | LLM 配置模型 + YAML 加载 | 135 |
| `tools/llm/prompts.py` | Agent Prompt 模板 | 241 |

## 注意事项

- 修改 Agent 后必须运行 `python3 -m pytest -q` 确认 84 tests 全部通过
- 风格相关修改请先阅读 `.agents/skills/style-system/SKILL.md`
- 不要删除或修改 `craft/`、`styles/`、`novels/` 下的 `.md` 数据文件，除非明确要求
- CLI 命令注册在 `tools/cli.py` 的 Typer sub-app 中
- LLM 集成采用 Strangler Fig 模式：所有 Agent 保留规则引擎 fallback
- LLM 配置文件：`llm_config.yaml`，API key 通过环境变量注入
- CLI 使用 `--use-llm` 启用 LLM 模式，`--llm-config` 指定配置路径

## LLM 模型路由

| 任务类型 | 首选模型 | 备选模型 | 兜底 |
|----------|----------|----------|------|
| reasoning（Director 决策） | Claude Opus 4.6 | GLM-4.7 | DeepSeek |
| generation（Librarian 写作） | Kimi K2.5 | MiniMax M2.5 | DeepSeek |
| review（LoreChecker 审查） | Claude Opus 4.6 | GLM-4.7 | DeepSeek |
| style（Stylist 润色） | Kimi K2.5 | MiniMax M2.5 | DeepSeek |
