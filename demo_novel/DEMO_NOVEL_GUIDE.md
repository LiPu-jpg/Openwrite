# 势力小说示例说明

示例根目录：`demo_novel/data/novels/my_novel/`

## 文件结构（当前标准）

- `metadata.yaml`：小说元信息
- `outline/`：总纲、卷纲、章纲（含标注）
- `characters/`：人物卡、时间线日志、快照
- `foreshadowing/dag.yaml`：伏笔 DAG 数据
- `world/`：势力、地点、境界、事件
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

## 快速测试

在仓库根目录执行：

```bash
PYTHONPATH=/Users/jiaoziang/Openwrite python3 -m tools.cli simulate chapter \
  --id ch_003 --novel-id my_novel
```

如果在 `demo_novel/` 目录执行，命令相同，`PYTHONPATH` 仍指向仓库根目录。
