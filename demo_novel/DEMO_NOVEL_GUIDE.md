# 势力小说示例说明

示例根目录：`demo_novel/data/novels/my_novel/`

## 文件结构（当前标准）

- `metadata.yaml`：小说元信息
- `outline/`：总纲、卷纲、章纲（含标注）
- `characters/`：人物简卡、动态主档、时间线日志、快照
- `foreshadowing/dag.yaml`：伏笔 DAG 数据
- `world/`：势力、地点、境界、事件 + `world_graph.yaml`
- `style/style_profile.yaml`：文风占位配置
- `manuscript/drafts/`：模拟流程产出的草稿

## 本示例设定

- 类型：仙侠势力争霸
- 标题：九盟裂天
- 首卷：雨城盟约（ch_001-ch_003）
- 主角：韩策（char_001）

## 标注示例

- 伏笔：`<!--fs id=f001 weight=10 layer=主线 target=ch_006--> ... <!--/fs-->`
- 回收：`<!--fs-recover ref=f002--> ... <!--/fs-recover-->`
- 人物变更：`<!--char id=char_001 mutation="acquire:残损盟印"--> ... <!--/char-->`
- 场景标记：`<!--scene id=s_001 tension=6 emotion=压抑--> ... <!--/scene-->`

## 人物时间线格式（文本优先）

- 推荐：`mutation` 只记录 `chapter + note`
- 可选：需要可回放时再加 `action/payload`
- 默认不再写入冗长的 `before_state/after_state`

示例：

```yaml
mutations:
  - mutation_id: char_001_0001
    chapter_id: ch_001
    timestamp: '2026-02-27T03:20:00'
    note: 初到雨城，确认主线目标是找出盟印来历
  - mutation_id: char_001_0002
    chapter_id: ch_001
    timestamp: '2026-02-27T03:22:00'
    action: acquire
    payload:
      raw: 残损盟印
      item: 残损盟印
      action: acquire
    note: 父亲遗物入手
```

## 人物档案双层结构（推荐）

- 简卡：`characters/cards/char_xxx.yaml`
- 主档：`characters/profiles/char_xxx.md`
- 规则：简卡维护“可快速检索的摘要”，主档维护“完整设定与自由书写”

`cards/char_001.yaml` 示例（简化）：

```yaml
summary:
  realm: 归元后期
  location: 未知
  statuses: [轻伤]
  items: [残损盟印, 回气丹, 雨城旧档案]
dynamic_profile: profiles/char_001.md
```

`profiles/char_001.md` 示例（自由文本）：

```md
【姓名：韩策】
【境界：归元后期】
【状态：轻伤，疑心渐重，盟约压力】
...（此处可写任意长度与格式）
```

## 世界观图谱（基础版）

- 文件：`world/world_graph.yaml`
- 结构：`entities + relations`
- 用途：`simulate chapter` 会自动注入图谱摘要

示例命令：

```bash
PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli world-entity-add faction_shushan 蜀山派 \
  --type faction --novel-id my_novel

PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli world-entity-add loc_qingyun 青云镇 \
  --type location --novel-id my_novel

PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli world-relation-add \
  --source faction_shushan --target loc_qingyun --relation protects --novel-id my_novel

PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli world-check --novel-id my_novel
```

## 快速测试

在仓库根目录执行：

```bash
PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli character mutate 韩策 \
  --chapter ch_001 --note "本章对黑旗盟动机产生误判" --novel-id my_novel

PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli character mutate 韩策 \
  --chapter ch_001 --change acquire:残损盟印 --note "关键道具入手" --novel-id my_novel

PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli character profile 韩策 \
  --novel-id my_novel

PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli simulate chapter \
  --id ch_003 --novel-id my_novel

PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli simulate chapter \
  --id ch_003 --forbidden 冲突 --max-rewrites 1 --novel-id my_novel
```

如果在 `demo_novel/` 目录执行，命令相同，`PYTHONPATH` 仍指向仓库根目录。
