#!/usr/bin/env bash
# 开发启动：OpenWrite Studio（编辑后端）+ dsh web（agent 控制台）。
# 用法：scripts/dev.sh [--project <OpenWrite 项目根>]（默认 ~/my_novel）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PROJECT="${OPENWRITE_PROJECT:-$HOME/my_novel}"
STUDIO_PORT="${STUDIO_PORT:-4567}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# OpenWrite 运行时（Python >= 3.10，用 uv 隔离在仓库内 .venv）
export NO_PROXY="127.0.0.1,localhost"
if [[ ! -x "$VENV/bin/openwrite" ]]; then
  echo "==> 首次运行，创建 OpenWrite 运行时（uv venv + editable install）"
  uv venv "$VENV" --python 3.12
  uv pip install --python "$VENV/bin/python" -e /Users/jiaoziang/OpenWrite
fi

echo "==> 启动 OpenWrite Studio: http://127.0.0.1:$STUDIO_PORT (project: $PROJECT)"
# 允许 dsh web (3080) 把 Studio 嵌入 iframe 面板
export OPENWRITE_FRAME_ANCESTORS="${OPENWRITE_FRAME_ANCESTORS:-http://127.0.0.1:3080}"
"$VENV/bin/openwrite" studio --project "$PROJECT" --port "$STUDIO_PORT" --no-open &
STUDIO_PID=$!
trap 'kill $STUDIO_PID 2>/dev/null || true' EXIT

# 等 Studio 就绪
for _ in $(seq 1 30); do
  curl -sf -m 2 "http://127.0.0.1:$STUDIO_PORT/api/health" >/dev/null && break
  sleep 1
done

echo "==> 启动 dsh web: http://127.0.0.1:3080"
exec "$ROOT/node_modules/.bin/dsh" web
