#!/usr/bin/env bash
# 集成验证：dsh web + OpenWrite 领域后端 + 原生工作台。用法：scripts/verify.sh
# Workspace 模型下，/studio-panel/api|events|invalidation.json 都需要受信的
# dsh Workspace context（X-Dsh-Workspace-Id / ?workspace=），本脚本会先通过
# dsh RPC 发现（或按需 adopt）一个 Workspace 再验证代理路径。
set -uo pipefail

export NO_PROXY="127.0.0.1,localhost"
DSH="${DSH_URL:-http://127.0.0.1:3080}"
STUDIO="${STUDIO_URL:-http://127.0.0.1:4567}"
PROJECT="${OPENWRITE_PROJECT:-$HOME/my_novel}"
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
check "dsh web 首页"           "window.__DSH_BOOT__"     "$(curl -s -m 5 "$DSH/" | head -c 3000)"
check "boot 图含 panel"        "studio-panel/client.js"  "$(curl -s -m 5 "$DSH/" | grep -o 'studio-panel/client.js?rev=[a-z0-9]*')"

bundle="$(curl -s -m 10 "$DSH/plugins/@dsh-novel/studio-panel/client.js")"
check "client bundle"         "window.__ModuleLoader__" "$bundle"
check "三个原生工作台"        "view.creation"           "$bundle"
check_absent "默认路径无 iframe" 'createElement("iframe")' "$bundle"

check "领域配置路由"          '"studioUrl"'             "$(curl -s -m 5 "$DSH/studio-panel/config.json")"

# --- 发现（或 adopt）dsh Workspace -------------------------------------------
rpc() { # $1=method $2=payload
  curl -s -m 8 -X POST "$DSH/api/$1" -H 'content-type: application/json' \
    -d "{\"type\":\"client-request\",\"rpcId\":\"rpc_verify_$$\",\"method\":\"$1\",\"payload\":$2}"
}
ws_list="$(rpc workspace.list '{}')"
ws_id="$(WS_LIST="$ws_list" WS_PATH="$(realpath "$PROJECT" 2>/dev/null || echo "$PROJECT")" node -e '
  const data = JSON.parse(process.env.WS_LIST);
  const items = data?.result?.value?.items ?? [];
  const want = process.env.WS_PATH;
  // 只接受与目标项目 canonical path 匹配的 Workspace；否则交给下方 adopt 分支，
  // 绝不能退化成“注册表里恰好排在第一个”的别的项目。
  const hit = items.find((w) => w.path === want);
  if (hit) process.stdout.write(hit.workspaceId);
')"
if [[ -z "$ws_id" ]]; then
  echo "==> dsh 中尚无 Workspace，adopt ${PROJECT}（幂等，不创建目录）"
  ws_created="$(rpc workspace.create "{\"path\":\"$PROJECT\"}")"
  ws_id="$(WS_JSON="$ws_created" node -e '
    const data = JSON.parse(process.env.WS_JSON);
    process.stdout.write(data?.result?.value?.workspace?.workspaceId ?? "");
  ')"
fi
ws_root="$(WS_LIST="$(rpc workspace.list '{}')" WS_ID="$ws_id" node -e '
  const data = JSON.parse(process.env.WS_LIST);
  const hit = (data?.result?.value?.items ?? []).find((w) => w.workspaceId === process.env.WS_ID);
  process.stdout.write(hit?.path ?? "");
')"
if [[ -z "$ws_id" || -z "$ws_root" ]]; then
  echo "FAIL  无法解析 dsh Workspace（workspace.list/create RPC 失败）"; exit 1
fi
echo "==> 验证用 Workspace: $ws_id ($ws_root)"

# --- context 反例：缺失/未知身份必须 fail closed ------------------------------
check "代理缺 context 拒绝"   "WORKSPACE_CONTEXT_MISSING" "$(curl -s -m 5 "$DSH/studio-panel/api/workspace")"
check "代理未知 id 拒绝"      "WORKSPACE_UNKNOWN"         "$(curl -s -m 5 -H 'X-Dsh-Workspace-Id: 00000000-0000-0000-0000-000000000000' "$DSH/studio-panel/api/workspace")"

# --- context 正例：代理/SSE/失效快照 ------------------------------------------
auth=(-H "X-Dsh-Workspace-Id: $ws_id")
check "代理 workspace"        '"initialized": true'     "$(curl -s -m 30 "${auth[@]}" "$DSH/studio-panel/api/workspace" | head -c 600)"
check "代理 document"         '"path"'                  "$(curl -s -m 5 "${auth[@]}" "$DSH/studio-panel/api/document?path=data%2Fmanuscript%2Farc_001%2Fch_001.md" | head -c 400)"
check "代理 tasks"            '"tasks"'                 "$(curl -s -m 30 "${auth[@]}" "$DSH/studio-panel/api/tasks?limit=3" | head -c 500)"
check "轻量失效快照"          '"revision"'              "$(curl -s -m 5 "$DSH/studio-panel/invalidation.json?workspace=$ws_id")"
check "SSE 失效流"            "event: ready"            "$(curl -sN -m 1 "$DSH/studio-panel/events?workspace=$ws_id")"

# --- Studio 直连诊断接口 -------------------------------------------------------
check "诊断 legacy 模式"      '"mode": "legacy"'        "$(curl -s -m 5 "$STUDIO/api/workspace/context" | head -c 400)"
check "诊断 workspace 模式"   '"mode": "workspace"'     "$(curl -s -m 5 -H "X-OpenWrite-Workspace-Root: $ws_root" "$STUDIO/api/workspace/context" | head -c 400)"
check "诊断非法 root 拒绝"    "WORKSPACE_ROOT_INVALID"  "$(curl -s -m 5 -H 'X-OpenWrite-Workspace-Root: relative/path' "$STUDIO/api/workspace/context")"

check "本地 Vditor CSS"       "Vditor v"                "$(curl -s -m 5 "$DSH/studio-panel/vendor/vditor/dist/index.css" | head -c 500)"
check "本地 Vditor runtime"   "Vditor"                  "$(curl -s -m 5 "$DSH/studio-panel/vendor/vditor/dist/index.min.js" | head -c 500)"

echo
[[ $fail -eq 0 ]] && echo "全部通过" || { echo "存在失败项"; exit 1; }
