#!/usr/bin/env bash
# 开发启动：OpenWrite Studio（编辑后端）+ dsh web（agent 控制台）。
# 用法：scripts/dev.sh [--project <OpenWrite 项目根>]（默认 ~/my_novel）
# 注意：--project 只决定 Studio 的 legacy 默认项目（无 Workspace context 的直连/CLI
# 请求）。dsh 集成路径下每个请求都按当前 dsh Workspace 的 canonical root 路由到
# 独立的 per-root 应用实例，见 docs/WORKSPACE_CONTEXT_CONTRACT.md。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
OPENWRITE_DIR="${OPENWRITE_DIR:-$ROOT/../OpenWrite}"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
PROJECT="${OPENWRITE_PROJECT:-$HOME/my_novel}"
STUDIO_PORT="${STUDIO_PORT:-4567}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      [[ $# -ge 2 && -n "$2" ]] || { echo "--project 需要项目路径" >&2; exit 2; }
      PROJECT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# OpenWrite 运行时（Python >= 3.10，用 uv 隔离在仓库内 .venv）
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"
if [[ ! -x "$ROOT/node_modules/.bin/dsh" ]]; then
  echo "未找到项目内 dsh CLI，请先运行 scripts/install.sh" >&2
  exit 2
fi
if [[ ! -x "$VENV/bin/openwrite" ]]; then
  if [[ ! -f "$OPENWRITE_DIR/pyproject.toml" ]]; then
    echo "未找到 OpenWrite 源码，请设置 OPENWRITE_DIR=/path/to/OpenWrite: $OPENWRITE_DIR" >&2
    exit 2
  fi
  echo "==> 首次运行，创建 OpenWrite 运行时（uv venv + editable install）"
  uv venv "$VENV" --python 3.12
  uv pip install --python "$VENV/bin/python" -e "$OPENWRITE_DIR"
fi

# The supervisor owns both process groups and cleans them up on exit or signals.
export OPENWRITE_FRAME_ANCESTORS="${OPENWRITE_FRAME_ANCESTORS:-http://127.0.0.1:3080}"
exec node "$ROOT/scripts/dev-supervisor.mjs" "$PROJECT" "$STUDIO_PORT"
