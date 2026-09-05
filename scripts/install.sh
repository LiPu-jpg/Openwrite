#!/usr/bin/env bash
# 安装 dsh-Openwrite：构建插件、安装统一 OpenWrite 预设、把插件装进 dsh profile。
# 幂等，可重复运行。用法：scripts/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRIDGE="$ROOT/packages/openwrite-bridge"
PANEL="$ROOT/packages/studio-panel"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
DSH_DOG_DIR="${DSH_DOG_DIR:-}"
DSH_DOG_AUTO_INSTALL="${DSH_DOG_AUTO_INSTALL:-1}"
DSH_DOG_REPOSITORY="${DSH_DOG_REPOSITORY:-https://github.com/Fun10165/dsh-dog.git}"
DSH_DOG_REF="${DSH_DOG_REF:-v1.2.0}"
DSH_DOG_WORKSPACE_ROOT="${DSH_DOG_WORKSPACE_ROOT:-$ROOT}"
# dsh 装在项目内（devDependency，pin 版本）；不走 npx——npx 的缓存自旋过
DSH=("$ROOT/node_modules/.bin/dsh")

for command in node npm pnpm rsync; do
  command -v "$command" >/dev/null || { echo "缺少命令: $command" >&2; exit 2; }
done

case "$DSH_DOG_AUTO_INSTALL" in
  0|1) ;;
  *) echo "DSH_DOG_AUTO_INSTALL 只能是 0 或 1" >&2; exit 2 ;;
esac

if [[ -z "$DSH_DOG_DIR" && "$DSH_DOG_AUTO_INSTALL" == "1" ]]; then
  DSH_DOG_DIR="$DSH_HOME/extensions/dsh-dog"
  if [[ ! -f "$DSH_DOG_DIR/package.json" ]]; then
    command -v git >/dev/null || { echo "自动安装 dsh-dog 需要 git" >&2; exit 2; }
    if [[ -e "$DSH_DOG_DIR" ]]; then
      echo "自动安装目录已存在但不是有效的 dsh-dog 仓库: $DSH_DOG_DIR" >&2
      exit 2
    fi
    dog_tmp="${DSH_DOG_DIR}.tmp.$$"
    mkdir -p "$(dirname "$DSH_DOG_DIR")"
    rm -rf "$dog_tmp"
    echo "==> 自动获取 dsh-dog $DSH_DOG_REF"
    dog_clone_args=(clone --depth 1 --branch "$DSH_DOG_REF" "$DSH_DOG_REPOSITORY" "$dog_tmp")
    if ! git "${dog_clone_args[@]}"; then
      rm -rf "$dog_tmp"
      echo "    通过当前 Git 代理获取失败，尝试直连"
      if ! git -c http.proxy= -c https.proxy= "${dog_clone_args[@]}"; then
        rm -rf "$dog_tmp"
        exit 1
      fi
    fi
    mv "$dog_tmp" "$DSH_DOG_DIR"
    printf 'repository=%s\nref=%s\n' "$DSH_DOG_REPOSITORY" "$DSH_DOG_REF" \
      > "$DSH_DOG_DIR/.dsh-openwrite-managed"
  else
    echo "==> 复用已安装的 dsh-dog: $DSH_DOG_DIR"
  fi
fi
if [[ -n "$DSH_DOG_DIR" && ! -f "$DSH_DOG_DIR/package.json" ]]; then
  echo "DSH_DOG_DIR 不是有效的 dsh-dog 仓库: $DSH_DOG_DIR" >&2
  exit 2
fi
if [[ -n "$DSH_DOG_DIR" ]]; then
  DSH_DOG_DIR="$(cd "$DSH_DOG_DIR" && pwd)"
  dog_package_name="$(node -e 'const p=require(process.argv[1]); process.stdout.write(String(p.name || ""))' "$DSH_DOG_DIR/package.json")"
  if [[ "$dog_package_name" != "@dsh-external/dsh-dog" ]]; then
    echo "dsh-dog package 名称不匹配: $dog_package_name" >&2
    exit 2
  fi
fi

echo "==> 1/6 按锁文件安装项目内 dsh CLI"
(cd "$ROOT" && npm ci --no-audit --no-fund)

echo "==> 2/6 构建 openwrite-bridge 插件"
(cd "$BRIDGE" && npm ci --no-audit --no-fund && npm run build)

echo "==> 3/6 构建 studio-panel 插件"
(cd "$PANEL" && npm ci --no-audit --no-fund && npm run build)

if [[ -n "$DSH_DOG_DIR" ]]; then
  echo "    构建 dsh-dog（首次 clone 没有 lib/ 构建产物）"
  (cd "$DSH_DOG_DIR" && pnpm install --frozen-lockfile && pnpm run build)
fi

echo "==> 4/6 安装 agent 预设到 $DSH_HOME/.agent-presets/"
mkdir -p "$DSH_HOME/.agent-presets"
for preset in openwrite; do
  rsync -a --delete "$ROOT/presets/$preset/" "$DSH_HOME/.agent-presets/$preset/"
  echo "    installed preset: $preset"
done
# Move only the two presets previously installed by this project out of the
# discovery root. They are generated configuration, not novel data; keeping
# them would leave duplicate selectable agents after the migration. The move
# is reversible and leaves a migration copy under ~/.dsh/.agent-presets-legacy.
mkdir -p "$DSH_HOME/.agent-presets-legacy"
for legacy in goethe dante; do
  if [[ -d "$DSH_HOME/.agent-presets/$legacy" ]]; then
    # A fresh destination preserves earlier migration backups on repeated runs.
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

configure_dog_settings() {
  local settings="$DSH_HOME/settings.yaml"
  mkdir -p "$DSH_HOME"
  touch "$settings"
  if grep -Eq '^dog:[[:space:]]*$' "$settings"; then
    echo "    dog.workspaceRoot 已存在，未覆盖: $settings"
    echo "    当前会话 Workspace 会覆盖该兜底值，无需为切换作品修改它"
    return
  fi
  {
    printf '\n# dsh-Openwrite DoG fallback (由 scripts/install.sh 写入)\n'
    printf 'dog:\n'
    printf '  workspaceRoot: %s\n' "$DSH_DOG_WORKSPACE_ROOT"
    printf '  scriptsDirectory: dog/scripts\n'
    printf '  storageDirectory: dog\n'
  } >> "$settings"
  echo "    dog.workspaceRoot 已配置为: $DSH_DOG_WORKSPACE_ROOT"
}

install_pkg web "$BRIDGE" '@dsh-novel/openwrite-bridge'
install_pkg headless "$BRIDGE" '@dsh-novel/openwrite-bridge'
install_pkg web "$PANEL" '@dsh-novel/studio-panel'

if [[ -n "$DSH_DOG_DIR" ]]; then
  # DoG agentic verifiers need a resident host; deliberately mount web only.
  install_pkg web "$DSH_DOG_DIR" '@dsh-external/dsh-dog'
  configure_dog_settings
else
  echo "    已按 DSH_DOG_AUTO_INSTALL=0 跳过 dsh-dog"
fi

# dsh-dog's programmatic kernel resolves scripts from the user-level library.
# Install the novel review adapter even when dsh-dog itself is added separately.
mkdir -p "$DSH_HOME/dog/scripts"
cp "$ROOT/scripts/dog/"*.js "$DSH_HOME/dog/scripts/"
chmod 755 "$DSH_HOME/dog/scripts/"*.js

echo
echo "安装完成。下一步："
echo "  scripts/dev.sh        # 启动 OpenWrite Studio + dsh web"
echo "  在 dsh web (http://127.0.0.1:3080) 新建会话时选择 OpenWrite 创作 预设，"
echo "  会话头部使用「创作 / 资料 / 任务」原生工作台；Studio 仅作为高级维护出口"
