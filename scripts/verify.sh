#!/usr/bin/env bash
# 集成验证：dsh web + Studio + 插件装载 + 面板路由的一键检查。
# 前提：scripts/dev.sh 已启动（或两个服务各自在跑）。用法：scripts/verify.sh
set -uo pipefail

export NO_PROXY="127.0.0.1,localhost"
DSH="${DSH_URL:-http://127.0.0.1:3080}"
STUDIO="${STUDIO_URL:-http://127.0.0.1:4567}"
fail=0

check() { # $1=name $2=expected-substring $3=actual
  if [[ "$3" == *"$2"* ]]; then
    echo "PASS  $1"
  else
    echo "FAIL  $1 (期望含: $2; 实际: ${3:0:120})"
    fail=1
  fi
}

check "Studio health"      '"ok": true'                "$(curl -s -m 5 "$STUDIO/api/health")"
check "dsh web 首页"       "__ModuleLoader__"          "$(curl -s -m 5 "$DSH/" | head -c 2000)"

check "boot 图含 panel"    "studio-panel/client.js"    "$(curl -s -m 5 "$DSH/" | grep -o 'studio-panel/client.js?rev=[a-z0-9]*')"
check "client bundle"      "window.__ModuleLoader__"   "$(curl -s -m 5 "$DSH/plugins/@dsh-novel/studio-panel/client.js" | head -c 200)"
check "config 路由"        '"studioUrl"'               "$(curl -s -m 5 "$DSH/studio-panel/config.json")"

check "代理 outline"       '"roots"'                   "$(curl -s -m 5 "$DSH/studio-panel/api/outline" | head -c 400)"
check "代理 assets"        '"assets"'                  "$(curl -s -m 5 "$DSH/studio-panel/api/assets" | head -c 400)"

check "index 引用皮肤"     "embed-dsh.css"             "$(curl -s -m 5 "$STUDIO/" | grep -o 'embed-dsh.css')"
check "皮肤文件可访"       "data-embed"                "$(curl -s -m 5 "$STUDIO/embed-dsh.css" | head -c 400)"
check "frame-ancestors"    "frame-ancestors http://127.0.0.1:3080" "$(curl -s -D - -o /dev/null -m 5 "$STUDIO/api/health" | grep -i 'content-security')"

echo
[[ $fail -eq 0 ]] && echo "全部通过" || { echo "存在失败项"; exit 1; }
