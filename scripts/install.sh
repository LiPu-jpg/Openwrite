#!/usr/bin/env bash
# 安装 dsh-novel：构建插件、安装 goethe/dante 预设、把插件装进 dsh profile。
# 幂等，可重复运行。用法：scripts/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRIDGE="$ROOT/packages/openwrite-bridge"
PANEL="$ROOT/packages/studio-panel"
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
DSH_DOG_DIR="${DSH_DOG_DIR:-}"
DSH_DOG_WORKSPACE_ROOT="${DSH_DOG_WORKSPACE_ROOT:-$ROOT}"
# dsh 装在项目内（devDependency，pin 版本）；不走 npx——npx 的缓存自旋过
DSH=("$ROOT/node_modules/.bin/dsh")

echo "==> 1/5 构建 openwrite-bridge 插件"
(cd "$BRIDGE" && npm install --no-audit --no-fund && npm run build)

echo "==> 2/5 构建 studio-panel 插件"
(cd "$PANEL" && npm install --no-audit --no-fund && npm run build)

echo "==> 3/5 安装 agent 预设到 $DSH_HOME/.agent-presets/"
mkdir -p "$DSH_HOME/.agent-presets"
for preset in goethe dante; do
  rsync -a --delete "$ROOT/presets/$preset/" "$DSH_HOME/.agent-presets/$preset/"
  echo "    installed preset: $preset"
done

echo "==> 4/5 初始化 dsh profile（web / headless）"
# 先让 dsh 按官方模板初始化 profile，再往里装插件
"${DSH[@]}" --profile web --dump-config >/dev/null
"${DSH[@]}" --profile headless "ok" >/dev/null 2>&1 || true

echo "==> 5/5 把插件装进 profile"
# dsh plugin add 透传 pnpm 时不带 -w，而 profile 目录本身是 workspace root
#（pnpm-workspace.yaml: packages: [.]），pnpm >=9 会拒绝。改为手动：
# pnpm add -w <本地路径> + 把包名追加进 dsh.profile.bundles。
install_pkg() { # $1=profile $2=pkg-dir $3=pkg-name
  local dir="$DSH_HOME/profiles/$1"
  if grep -q "\"$3\"" "$dir/package.json" 2>/dev/null; then
    echo "    $1: $3 已安装，跳过"
  else
    (cd "$dir" && pnpm add -w "$2" && node -e "
      const fs = require('fs');
      const p = JSON.parse(fs.readFileSync('package.json','utf8'));
      if (!p.dsh.profile.bundles.includes('$3'))
        p.dsh.profile.bundles.push('$3');
      fs.writeFileSync('package.json', JSON.stringify(p, null, 2) + '\n');
    ")
    echo "    $1: $3 安装完成"
  fi
}

configure_dog_settings() {
  local settings="$DSH_HOME/settings.yaml"
  mkdir -p "$DSH_HOME"
  touch "$settings"
  if grep -Eq '^dog:[[:space:]]*$' "$settings"; then
    echo "    dog.workspaceRoot 已存在，未覆盖: $settings"
    echo "    如需切换项目，请手动设置 dog.workspaceRoot=$DSH_DOG_WORKSPACE_ROOT 后重启 dsh"
    return
  fi
  {
    printf '\n# dsh-novel DoG workspace (由 scripts/install.sh 写入)\n'
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
  if [[ ! -f "$DSH_DOG_DIR/package.json" ]]; then
    echo "DSH_DOG_DIR 不是有效的 dsh-dog 仓库: $DSH_DOG_DIR" >&2
    exit 2
  fi
  echo "    构建 dsh-dog（首次 clone 没有 lib/ 构建产物）"
  (cd "$DSH_DOG_DIR" && pnpm install --no-frozen-lockfile && pnpm run build)
  # DoG agentic verifiers need a resident host; deliberately mount web only.
  install_pkg web "$DSH_DOG_DIR" '@dsh-external/dsh-dog'
  configure_dog_settings
else
  echo "    未安装 dsh-dog（设置 DSH_DOG_DIR=/path/to/dsh-dog 可启用 web 插件）"
fi

# dsh-dog's programmatic kernel resolves scripts from the user-level library.
# Install the novel review adapter even when dsh-dog itself is added separately.
mkdir -p "$DSH_HOME/dog/scripts"
cp "$ROOT/scripts/dog/"*.js "$DSH_HOME/dog/scripts/"
chmod 755 "$DSH_HOME/dog/scripts/"*.js

echo
echo "安装完成。下一步："
echo "  scripts/dev.sh        # 启动 OpenWrite Studio + dsh web"
echo "  在 dsh web (http://127.0.0.1:3080) 新建会话时选择 Goethe 规划 / Dante 写作 预设，"
echo "  会话头部使用「创作 / 资料 / 任务」原生工作台；Studio 仅作为高级维护出口"
