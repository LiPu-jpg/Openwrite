#!/usr/bin/env bash
# 集成验证：dsh web + OpenWrite 领域后端 + 原生工作台。用法：scripts/verify.sh
set -uo pipefail

export NO_PROXY="127.0.0.1,localhost"
DSH="${DSH_URL:-http://127.0.0.1:3080}"
STUDIO="${STUDIO_URL:-http://127.0.0.1:4567}"
fail=0

check() {
  if [[ "$3" == *"$2"* ]]; then echo "PASS  $1"; else
    echo "FAIL  $1 (期望含: $2; 实际: ${3:0:120})"; fail=1
  fi
}

check_absent() {
  if [[ "$3" != *"$2"* ]]; then echo "PASS  $1"; else
    echo "FAIL  $1 (不应含: $2)"; fail=1
  fi
}

check "OpenWrite health"      '"ok": true'              "$(curl -s -m 5 "$STUDIO/api/health")"
check "dsh web 首页"           "__ModuleLoader__"        "$(curl -s -m 5 "$DSH/" | head -c 3000)"
check "boot 图含 panel"        "studio-panel/client.js"  "$(curl -s -m 5 "$DSH/" | grep -o 'studio-panel/client.js?rev=[a-z0-9]*')"

bundle="$(curl -s -m 10 "$DSH/plugins/@dsh-novel/studio-panel/client.js")"
check "client bundle"         "window.__ModuleLoader__" "$bundle"
check "三个原生工作台"        "view.creation"           "$bundle"
check_absent "默认路径无 iframe" 'createElement("iframe")' "$bundle"

check "领域配置路由"          '"studioUrl"'             "$(curl -s -m 5 "$DSH/studio-panel/config.json")"
check "代理 workspace"        '"initialized": true'     "$(curl -s -m 5 "$DSH/studio-panel/api/workspace" | head -c 600)"
check "代理 document"         '"path"'                  "$(curl -s -m 5 "$DSH/studio-panel/api/document?path=data%2Fmanuscript%2Farc_001%2Fch_001.md" | head -c 400)"
check "代理 tasks"            '"tasks"'                 "$(curl -s -m 5 "$DSH/studio-panel/api/tasks?limit=3" | head -c 500)"
check "轻量失效快照"          '"revision"'              "$(curl -s -m 5 "$DSH/studio-panel/invalidation.json")"
check "SSE 失效流"            "event: ready"            "$(curl -sN -m 1 "$DSH/studio-panel/events")"
check "本地 Vditor CSS"       "Vditor v"                "$(curl -s -m 5 "$DSH/studio-panel/vendor/vditor/dist/index.css" | head -c 500)"
check "本地 Vditor runtime"   "Vditor"                  "$(curl -s -m 5 "$DSH/studio-panel/vendor/vditor/dist/index.min.js" | head -c 500)"

echo
[[ $fail -eq 0 ]] && echo "全部通过" || { echo "存在失败项"; exit 1; }
