#!/usr/bin/env bash
# setup-openwrite-daemon.sh
# ---------------------------------------------------------------------------
# One-shot, idempotent machine setup for the OpenWrite + dsh development stack.
#
# What it does:
#   1. Preflight-checks that the OpenWrite runtime exists (repo + .venv).
#   2. Installs the `dsh` CLI globally via npm (skippable).
#   3. Installs a launchd LaunchAgent that keeps `openwrite studio` alive on
#      port 4567 (RunAtLoad + KeepAlive, crash-safe), with proxies disabled
#      for localhost so the 7892-style local proxy cannot hijack it.
#   4. Puts a `dsh` launcher on PATH (~/.local/bin + ~/.npm-global/bin) and
#      appends PATH exports to your shell rc (idempotent).
#   5. Boots the agent and waits for the Studio health check.
#
# Usage:
#   scripts/setup-openwrite-daemon.sh \
#       [--dsh-root /path/to/dsh-novel] \
#       [--project /path/to/legacy-project] \
#       [--port 4567] \
#       [--skip-npm]
#
# Requirements on the target machine (any macOS):
#   * macOS with a GUI user session (launchctl gui/$UID).
#   * OpenWrite sources cloned and its .venv created (scripts/dev.sh does this:
#     `uv venv .venv && uv pip install --python .venv/bin/python -e <OpenWrite-src>`).
#   * node/npm available for the global `dsh` install.
#
# Notes / portability:
#   * Everything under $HOME is parameterised at install time; the plist is
#     rendered from this script, so a copy of this script works on any machine
#     (paths are substituted, not hardcoded).
#   * The `--project` value is only the "legacy default" project for direct
#     CLI requests; dsh sessions route per-workspace regardless.
#   * Only zsh/bash rc files are touched; fish users should add the PATH
#     exports manually (the script prints them).
# ---------------------------------------------------------------------------
set -euo pipefail

# --- defaults -------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSH_ROOT="${DSH_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PROJECT="${PROJECT:-$HOME/my_novel}"
PORT="${PORT:-4567}"
LABEL="${LABEL:-com.openwrite.studio}"
SKIP_NPM=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dsh-root) DSH_ROOT="$(cd "$2" && pwd)"; shift 2 ;;
    --project)  PROJECT="$2"; shift 2 ;;
    --port)     PORT="$2"; shift 2 ;;
    --skip-npm) SKIP_NPM=1; shift ;;
    -h|--help)  sed -n '2,60p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

LOG_DIR="$HOME/Library/Logs"
LA_DIR="$HOME/Library/LaunchAgents"
PLIST="$LA_DIR/$LABEL.plist"
UID_NUM="$(id -u)"

echo "==> OpenWrite Studio daemon setup"
echo "    dsh-root : $DSH_ROOT"
echo "    project  : $PROJECT"
echo "    port     : $PORT"
echo "    label    : $LABEL"

# --- 1) preflight ----------------------------------------------------------
OW_BIN="$DSH_ROOT/.venv/bin/openwrite"
if [[ ! -x "$OW_BIN" ]]; then
  echo "!! 未找到 OpenWrite 运行时: $OW_BIN" >&2
  echo "   请在目标机器先准备 dsh-novel 与 OpenWrite 源码并创建 .venv：" >&2
  echo "     cd $DSH_ROOT && bash scripts/dev.sh --project '$PROJECT'   # 首次会自动建 venv" >&2
  echo "   或手动: uv venv '$DSH_ROOT/.venv' --python 3.12 && uv pip install --python '$DSH_ROOT/.venv/bin/python' -e /path/to/OpenWrite" >&2
  exit 1
fi

# --- 2) global dsh CLI (best effort) ---------------------------------------
if [[ "$SKIP_NPM" -eq 0 ]] && command -v npm >/dev/null 2>&1; then
  if [[ ! -x "$HOME/.npm-global/bin/dsh" ]]; then
    echo "==> npm i -g @deepseek-ai/dsh"
    npm i -g @deepseek-ai/dsh || echo "    (npm 安装失败，将用 ~/.local/bin/dsh 启动器回退到 npx 缓存)"
  else
    echo "==> dsh 已全局安装，跳过 npm install"
  fi
fi

# --- 3) dsh launcher + PATH -------------------------------------------------
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/dsh" <<'EOF'
#!/usr/bin/env bash
set -e
if [ -x "$HOME/.npm-global/bin/dsh" ]; then
  exec "$HOME/.npm-global/bin/dsh" "$@"
fi
CACHE="$(npm config get cache 2>/dev/null)/_npx"
CAND="$(ls -1t "$CACHE"/*/node_modules/.bin/dsh 2>/dev/null | head -1)"
if [ -n "$CAND" ] && [ -x "$CAND" ]; then
  exec "$CAND" "$@"
fi
echo "dsh 未找到：请先运行  npm i -g @deepseek-ai/dsh" >&2
exit 127
EOF
chmod +x "$HOME/.local/bin/dsh"
echo "==> 已写入启动器: $HOME/.local/bin/dsh"

# Append PATH exports to the login shell rc (idempotent).
RC=""
case "${SHELL##*/}" in
  zsh) RC="$HOME/.zshrc" ;;
  bash) [[ -f "$HOME/.bash_profile" ]] && RC="$HOME/.bash_profile" || RC="$HOME/.bashrc" ;;
esac
if [[ -n "$RC" ]]; then
  for line in 'export PATH="$HOME/.local/bin:$PATH"' 'export PATH="$HOME/.npm-global/bin:$PATH"'; do
    if ! grep -qF -- "$line" "$RC" 2>/dev/null; then
      printf '\n%s\n' "$line" >> "$RC"
      echo "==> 已追加到 $RC : $line"
    fi
  done
else
  echo "==> 未识别的登录 shell（$SHELL），请手动把以下两行加入 rc："
  echo '    export PATH="$HOME/.local/bin:$PATH"'
  echo '    export PATH="$HOME/.npm-global/bin:$PATH"'
fi

# --- 4) launchd LaunchAgent --------------------------------------------------
mkdir -p "$LA_DIR" "$LOG_DIR"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$OW_BIN</string>
        <string>studio</string>
        <string>--project</string>
        <string>$PROJECT</string>
        <string>--port</string>
        <string>$PORT</string>
        <string>--no-open</string>
    </array>
    <key>WorkingDirectory</key><string>$DSH_ROOT</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NO_PROXY</key><string>127.0.0.1,localhost</string>
        <key>no_proxy</key><string>127.0.0.1,localhost</string>
        <key>http_proxy</key><string></string>
        <key>https_proxy</key><string></string>
        <key>all_proxy</key><string></string>
        <key>OPENWRITE_FRAME_ANCESTORS</key><string>http://127.0.0.1:3080</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>5</integer>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>$LOG_DIR/openwrite-studio.out.log</string>
    <key>StandardErrorPath</key><string>$LOG_DIR/openwrite-studio.err.log</string>
</dict>
</plist>
EOF
echo "==> 已写入 plist: $PLIST"

# (Re)load the agent robustly: bootout can race an immediate bootstrap in the
# gui domain, so allow retries and a legacy `launchctl load` fallback.
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
sleep 1
if launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
  echo "==> 守护已在运行，重启以应用新配置: kickstart -k"
  launchctl kickstart -k "gui/$UID_NUM/$LABEL" || true
else
  booted=0
  for _ in 1 2 3; do
    if launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/dev/null; then
      booted=1; break
    fi
    sleep 1
  done
  if [[ "$booted" -eq 0 ]]; then
    launchctl load -w "$PLIST"   # legacy fallback
  fi
  echo "==> 已加载 (gui/$UID_NUM/$LABEL)"
fi
for _ in 1 2 3 4 5; do
  launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 && break
  sleep 1
done
if ! launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
  echo "!! launchd 未能注册 $LABEL，请查看: launchctl print gui/$UID_NUM/$LABEL" >&2
fi

# --- 5) health wait ---------------------------------------------------------
for _ in $(seq 1 30); do
  code=$(NO_PROXY="127.0.0.1,localhost" curl -s -o /dev/null -w '%{http_code}' -m 2 \
         "http://127.0.0.1:$PORT/api/workspace/context" 2>/dev/null || true)
  [[ "$code" != "000" && -n "$code" ]] && break
  sleep 1
done
echo
echo "完成。OpenWrite Studio 守护进程运行中："
echo "   http://127.0.0.1:${PORT}    (launchd label: ${LABEL}，崩溃自动重启)"
echo
echo "日常使用（新开终端，或先 source ~/.zshrc）："
echo "   dsh web"
echo
echo "管理命令："
echo "   launchctl list | grep openwrite"
echo "   launchctl bootout gui/${UID_NUM}/${LABEL}"
echo "   launchctl bootstrap gui/${UID_NUM} ${PLIST}"
echo "   tail -f ${LOG_DIR}/openwrite-studio.err.log"
