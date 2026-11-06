#!/usr/bin/env bash
# 安装 dsh-Openwrite：构建插件、安装统一 OpenWrite 预设、把插件装进 dsh profile。
# 幂等，可重复运行。用法：scripts/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRIDGE="$ROOT/packages/openwrite-bridge"
PANEL="$ROOT/packages/studio-panel"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
# dsh 装在项目内（devDependency，pin 版本）；不走 npx——npx 的缓存自旋过
DSH=("$ROOT/node_modules/.bin/dsh")

# Only what this script actually runs. The dsh CLI drives pnpm itself when it
# installs into a profile, so requiring it here would block a working machine.
for command in node npm rsync; do
  command -v "$command" >/dev/null || { echo "缺少命令: $command" >&2; exit 2; }
done

echo "==> 1/6 按锁文件安装项目内 dsh CLI"
(cd "$ROOT" && npm ci --no-audit --no-fund)

echo "==> 2/6 构建 openwrite-bridge 插件"
(cd "$BRIDGE" && npm ci --no-audit --no-fund && npm run build)

echo "==> 3/6 构建 studio-panel 插件"
(cd "$PANEL" && npm ci --no-audit --no-fund && npm run build)

preset_digest() { # $1 = file
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  else sha256sum "$1" | cut -d' ' -f1; fi
}

echo "==> 4/6 安装 agent 预设到 $DSH_HOME/.agent-presets/"
mkdir -p "$DSH_HOME/.agent-presets"
for preset in openwrite; do
  # Never --delete: this directory is author-owned territory (a custom skill, a
  # note, an editor backup), and maintenance.mjs classifies everything without
  # an ownership marker as preserved. Files the package no longer ships move
  # aside under .agent-presets-legacy/ instead of being dropped.
  target="$DSH_HOME/.agent-presets/$preset"
  if [[ -e "$target" ]]; then
    mkdir -p "$DSH_HOME/.agent-presets-legacy"
    # mktemp -d on a template, not a timestamp: two installs in the same second
    # must not share a destination, or the second overwrites the first backup.
    backup="$(mktemp -d "$DSH_HOME/.agent-presets-legacy/$preset.XXXXXXXX")"
    # Relative paths, NUL-delimited: a preset name may contain anything.
    # A file is moved aside when the package does not ship it at all, OR when it
    # ships it but the author has changed it. Without the second case the rsync
    # below silently reverted every author edit to a shipped file - the very
    # files this block's comment calls author-owned territory - with no warning
    # and no backup.
    while IFS= read -r -d '' foreign; do
      relative="${foreign#./}"
      destination="$backup/$relative"
      mkdir -p "$(dirname "$destination")"
      mv "$target/$foreign" "$destination"
      echo "    moved author file out of the managed preset: $relative -> $backup/"
    done < <(cd "$target" && find . -type f ! -name '.openwrite-managed.json' -print0 | while IFS= read -r -d '' f; do
      shipped="$ROOT/presets/$preset/$f"
      if [[ ! -e "$shipped" ]]; then
        printf '%s\0' "$f"
      elif ! cmp -s "$shipped" "$f"; then
        echo "    preserving author edit to a shipped preset file: $f" >&2
        printf '%s\0' "$f"
      fi
    done)
  fi
  rsync -a "$ROOT/presets/$preset/" "$target/"
  # The ownership marker is what maintenance.mjs and plugin.mjs use to tell a
  # package-managed preset from an author-owned one. It was never written, so
  # this script's own output was reported as author-owned (and upgrades refused).
  # Write it atomically: a truncated marker is indistinguishable from a corrupt
  # one, and both used to be reported as "author-owned" - permanently blocking
  # upgrades with no diagnostic.
  marker_tmp="$(mktemp "$target/.openwrite-managed.XXXXXX")" || exit 1
  # shellcheck disable=SC2064  # expand now: the path is fixed for this iteration
  trap "rm -f '$marker_tmp'" EXIT
  cat > "$marker_tmp" <<MARKER
{"source":"package","tree":"sha256:$(preset_digest "$ROOT/presets/$preset/agent.cordis.yml")","version":"$(sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([^"]*\)".*/\1/p' "$ROOT/package.json" | head -n 1)"}
MARKER
  mv "$marker_tmp" "$target/.openwrite-managed.json"
  trap - EXIT
  echo "    installed preset: $preset (package-managed)"
done
# Move only the two presets previously installed by this project out of the
# discovery root. They are generated configuration, not novel data; keeping
# them would leave duplicate selectable agents after the migration. The move
# is reversible and leaves a migration copy under ~/.dsh/.agent-presets-legacy.
mkdir -p "$DSH_HOME/.agent-presets-legacy"
for legacy in goethe dante; do
  if [[ -d "$DSH_HOME/.agent-presets/$legacy" ]]; then
    # A fresh destination preserves earlier migration backups on repeated runs.
    # mktemp -d on a template: the template is one quoted argument, so a home
    # path with spaces is fine, and it never reuses an existing directory.
    backup="$(mktemp -d "$DSH_HOME/.agent-presets-legacy/$legacy.XXXXXXXX")"
    mv "$DSH_HOME/.agent-presets/$legacy" "$backup/preset"
    echo "    moved legacy preset out of roster: $legacy"
  fi
done

echo "==> 5/6 初始化 dsh profile（web / headless）"
# 先让 dsh 按官方模板初始化 profile，再往里装插件
"${DSH[@]}" --profile web --dump-config >/dev/null
"${DSH[@]}" --profile headless --dump-config >/dev/null

echo "==> 6/6 把插件装进 profile"
# rc.7 forwards -w to pnpm and reconciles bundles from installed packages.
# Always run it: a dependency name alone does not prove a complete installation.
install_pkg() { # $1=profile $2=pkg-dir $3=pkg-name
  "${DSH[@]}" plugin --profile "$1" add -w "$2"
  echo "    $1: $3 安装完成"
}

install_pkg web "$BRIDGE" '@dsh-novel/openwrite-bridge'
install_pkg headless "$BRIDGE" '@dsh-novel/openwrite-bridge'
install_pkg web "$PANEL" '@dsh-novel/studio-panel'

echo
echo "安装完成。下一步："
echo "  scripts/dev.sh        # 启动 OpenWrite Studio + dsh web"
echo "  在 dsh web (http://127.0.0.1:3080) 新建会话时选择 OpenWrite 创作 预设，"
echo "  会话头部使用「创作 / 资料 / 任务」原生工作台；Studio 仅作为高级维护出口"
