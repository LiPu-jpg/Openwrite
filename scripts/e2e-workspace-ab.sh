#!/usr/bin/env bash
# Live A/B Workspace 隔离证据：两个临时真实目录 -> 注册为 dsh Workspace ->
# 经 dsh 代理（3080）分别 init、写同名不同内容章节 -> 校验代理/磁盘/失效隔离。
# 前置：scripts/dev.sh 栈在跑（dsh web 3080 + Studio 4567，均为当前源码构建）。
# 结束后自动清理：workspace.delete 两个临时 Workspace 并删除临时目录。
set -uo pipefail

export NO_PROXY="127.0.0.1,localhost"
DSH="${DSH_URL:-http://127.0.0.1:3080}"
STUDIO="${STUDIO_URL:-http://127.0.0.1:4567}"
fail=0

check() { # $1=name $2=expected-substring $3=actual
  if [[ "$3" == *"$2"* ]]; then echo "PASS  $1"; else
    echo "FAIL  $1 (期望含: $2; 实际: ${3:0:200})"; fail=1
  fi
}
check_absent() {
  if [[ "$3" != *"$2"* ]]; then echo "PASS  $1"; else
    echo "FAIL  $1 (不应含: $2; 实际: ${3:0:200})"; fail=1
  fi
}

rpc() { # $1=method $2=payload
  curl -s -m 10 -X POST "$DSH/api/$1" -H 'content-type: application/json' \
    -d "{\"type\":\"client-request\",\"rpcId\":\"rpc_ab_$$_$1\",\"method\":\"$1\",\"payload\":$2}"
}
json_field() { # stdin=json $1=dot-path
  node -e '
    let s = "";
    process.stdin.on("data", (c) => (s += c)).on("end", () => {
      const v = process.argv[1].split(".").reduce((o, k) => o?.[k], JSON.parse(s));
      process.stdout.write(v == null ? "" : String(v));
    });' "$1"
}

DIR_A="$(mktemp -d /tmp/dsh-novel-ab-A.XXXXXX)"
DIR_B="$(mktemp -d /tmp/dsh-novel-ab-B.XXXXXX)"
ROOT_A="$(realpath "$DIR_A")"
ROOT_B="$(realpath "$DIR_B")"
WS_A=""; WS_B=""
cleanup() {
  [[ -n "$WS_A" ]] && rpc workspace.delete "{\"workspaceId\":\"$WS_A\"}" >/dev/null 2>&1 || true
  [[ -n "$WS_B" ]] && rpc workspace.delete "{\"workspaceId\":\"$WS_B\"}" >/dev/null 2>&1 || true
  rm -rf "$DIR_A" "$DIR_B"
}
trap cleanup EXIT

curl -sf -m 3 "$DSH/" >/dev/null || { echo "SKIP: dsh web $DSH 不可达"; exit 0; }
curl -sf -m 3 "$STUDIO/api/health" >/dev/null || { echo "SKIP: Studio $STUDIO 不可达"; exit 0; }

echo "==> A: $ROOT_A"
echo "==> B: $ROOT_B"

# --- 注册两个 dsh Workspace ----------------------------------------------------
WS_A="$(rpc workspace.create "{\"path\":\"$ROOT_A\"}" | json_field result.value.workspace.workspaceId)"
WS_B="$(rpc workspace.create "{\"path\":\"$ROOT_B\"}" | json_field result.value.workspace.workspaceId)"
[[ -n "$WS_A" && -n "$WS_B" ]] || { echo "FAIL  workspace.create"; exit 1; }
echo "==> WS_A=$WS_A WS_B=$WS_B"

api() { # $1=workspace-id $2=method $3=path $4=body(optional)
  local args=(-s -m 30 -X "$2" -H "X-Dsh-Workspace-Id: $1")
  [[ -n "${4:-}" ]] && args+=(-H 'content-type: application/json' -d "$4")
  curl "${args[@]}" "$DSH/studio-panel/api$3"
}

# --- init（context 模式，绝对 canonical path） --------------------------------
INIT_A="$(printf '{"project_path":"%s","novel_id":"abdemo","title":"AB Demo A"}' "$ROOT_A")"
INIT_B="$(printf '{"project_path":"%s","novel_id":"abdemo","title":"AB Demo B"}' "$ROOT_B")"
check "A init" '"initialized": true' "$(api "$WS_A" POST /project/init "$INIT_A")"
check "B init" '"initialized": true' "$(api "$WS_B" POST /project/init "$INIT_B")"

# init 反例：project_path 与 context root 不一致
INIT_BAD="$(printf '{"project_path":"%s","novel_id":"abdemo","title":"x"}' "$ROOT_B")"
check "init root 不匹配拒绝" 'WORKSPACE_CONTEXT_MISMATCH' "$(api "$WS_A" POST /project/init "$INIT_BAD")"

# --- 同名不同内容章节 -----------------------------------------------------------
CH_A="第七章 甲地初雪。林霁在A世界点起烽火。"
CH_B="第七章 乙城夜雨。苏离在B世界收起纸伞。"
DOC_A="$(printf '{"path":"data/manuscript/arc_001/ch_001.md","content":"%s"}' "$CH_A")"
DOC_B="$(printf '{"path":"data/manuscript/arc_001/ch_001.md","content":"%s"}' "$CH_B")"
check "A 写 ch_001" '"path"' "$(api "$WS_A" PUT /document "$DOC_A")"
check "B 写 ch_001" '"path"' "$(api "$WS_B" PUT /document "$DOC_B")"

# --- 代理读取隔离 ----------------------------------------------------------------
check "A 读到 A 内容"   '甲地初雪' "$(api "$WS_A" GET '/document?path=data%2Fmanuscript%2Farc_001%2Fch_001.md')"
check "B 读到 B 内容"   '乙城夜雨' "$(api "$WS_B" GET '/document?path=data%2Fmanuscript%2Farc_001%2Fch_001.md')"
check_absent "A 不含 B 内容" '乙城夜雨' "$(api "$WS_A" GET '/document?path=data%2Fmanuscript%2Farc_001%2Fch_001.md')"
check_absent "B 不含 A 内容" '甲地初雪' "$(api "$WS_B" GET '/document?path=data%2Fmanuscript%2Farc_001%2Fch_001.md')"
check "A workspace 指向 A" "$ROOT_A" "$(api "$WS_A" GET /workspace | head -c 2000)"
check "B workspace 指向 B" "$ROOT_B" "$(api "$WS_B" GET /workspace | head -c 2000)"

# --- 磁盘证据 ---------------------------------------------------------------------
HASH_A="$(shasum -a 256 "$ROOT_A/data/novels/abdemo/data/manuscript/arc_001/ch_001.md" | cut -d' ' -f1)"
HASH_B="$(shasum -a 256 "$ROOT_B/data/novels/abdemo/data/manuscript/arc_001/ch_001.md" | cut -d' ' -f1)"
echo "==> hash A=$HASH_A"
echo "==> hash B=$HASH_B"
if [[ "$HASH_A" != "$HASH_B" && -n "$HASH_A" && -n "$HASH_B" ]]; then
  echo "PASS  磁盘章节 hash 不同"
else
  echo "FAIL  磁盘章节 hash（A=$HASH_A B=${HASH_B}）"; fail=1
fi
check_absent "A 目录无 B 文本" '乙城夜雨' "$(grep -r '乙城夜雨' "$ROOT_A" 2>/dev/null || true)"
check_absent "B 目录无 A 文本" '甲地初雪' "$(grep -r '甲地初雪' "$ROOT_B" 2>/dev/null || true)"
check_absent "A 无嵌套项目" 'novel_config' "$(ls "$ROOT_A/data/novels/abdemo" 2>/dev/null)"

# --- 失效快照按 root 隔离 -----------------------------------------------------------
REV_A_BEFORE="$(curl -s -m 5 "$DSH/studio-panel/invalidation.json?workspace=$WS_A" | json_field revision)"
REV_B_BEFORE="$(curl -s -m 5 "$DSH/studio-panel/invalidation.json?workspace=$WS_B" | json_field revision)"
DOC_A2="$(printf '{"path":"data/manuscript/arc_001/ch_001.md","content":"%s"}' "$CH_A 追记一笔。")"
api "$WS_A" PUT /document "$DOC_A2" >/dev/null
REV_A_AFTER="$(curl -s -m 5 "$DSH/studio-panel/invalidation.json?workspace=$WS_A" | json_field revision)"
REV_B_AFTER="$(curl -s -m 5 "$DSH/studio-panel/invalidation.json?workspace=$WS_B" | json_field revision)"
echo "==> revision A: $REV_A_BEFORE -> $REV_A_AFTER ; B: $REV_B_BEFORE -> $REV_B_AFTER"
if [[ "$REV_A_AFTER" -gt "$REV_A_BEFORE" && "$REV_B_AFTER" == "$REV_B_BEFORE" ]]; then
  echo "PASS  A 写操作只推进 A 的 revision"
else
  echo "FAIL  revision 隔离（A $REV_A_BEFORE->$REV_A_AFTER, B $REV_B_BEFORE->${REV_B_AFTER}）"; fail=1
fi

# --- context 反例 -------------------------------------------------------------------
check "缺 context 拒绝"     'WORKSPACE_CONTEXT_MISSING' "$(curl -s -m 5 "$DSH/studio-panel/api/workspace")"
check "未知 workspace 拒绝" 'WORKSPACE_UNKNOWN' \
  "$(api 00000000-0000-0000-0000-000000000000 GET /workspace)"
check "Studio 相对 root 拒绝" 'WORKSPACE_ROOT_INVALID' \
  "$(curl -s -m 5 -H 'X-OpenWrite-Workspace-Root: ../etc' "$STUDIO/api/workspace/context")"
check "Studio A 诊断" "\"workspace_root\": \"$ROOT_A\"" \
  "$(curl -s -m 5 -H "X-OpenWrite-Workspace-Root: $ROOT_A" "$STUDIO/api/workspace/context")"
OPEN_BAD="$(printf '{"project_path":"%s"}' "$ROOT_B")"
check "context 模式禁止 project/open" 'not allowlisted' "$(api "$WS_A" POST /project/open "$OPEN_BAD")"

# --- 重启恢复（Studio 重启后 A/B 内容仍在） -------------------------------------------
echo "==> 请手动重启 Studio 后重跑本脚本可验证恢复；当前轮仅验证运行态隔离"

echo
[[ $fail -eq 0 ]] && echo "A/B 隔离验证全部通过" || { echo "存在失败项"; exit 1; }
