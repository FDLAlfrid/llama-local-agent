#!/usr/bin/env bash
# llama-local-agent installer
# 用法: ./install.sh [--no-vulkan] [--prefix DIR]
set -euo pipefail

VULKAN=1
PREFIX="$HOME/llama.cpp"
for a in "$@"; do
  case "$a" in
    --no-vulkan) VULKAN=0 ;;
    --prefix) shift; PREFIX="$1" ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
  esac
done

say() { printf '\033[36m▸\033[0m %s\n' "$*"; }
die() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

say "检查依赖"
for c in git cmake; do have "$c" || die "缺 $c，先 apt install $c"; done
have nproc || die "缺 nproc"

if [ ! -d "$PREFIX/.git" ]; then
  say "克隆 llama.cpp 到 $PREFIX"
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$PREFIX"
else
  say "已有源码，拉取更新"
  git -C "$PREFIX" pull --ff-only || true
fi

FLAGS=(-DCMAKE_BUILD_TYPE=Release)
if [ "$VULKAN" = 1 ]; then
  say "启用 Vulkan 后端（核显也能加速）"
  FLAGS+=(-DGGML_VULKAN=ON)
fi

say "编译（$((`nproc`)) 线程，几分钟）"
cmake -B "$PREFIX/build" -S "$PREFIX" "${FLAGS[@]}"
cmake --build "$PREFIX/build" -j"$(nproc)"

say "安装到 /usr/local/bin（需要 sudo）"
sudo cmake --install "$PREFIX/build"
"$(command -v llama-server)" --version | head -2

say "建工作目录"
mkdir -p "$HOME/llama-workspace" "$HOME/models"

cat <<TIP

完成。下一步：
  1) 把 .gguf 放进 ~/models/
  2) 启动：
     llama-server -m ~/models/<model>.gguf \\
       --host 127.0.0.1 --port 8082 -c 16384 -ngl 99 \\
       --no-kv-offload -b 2048 -ub 512 -t 8 \\
       --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 \\
       --jinja --tools all --ui-mcp-proxy
  3) 打开 http://127.0.0.1:8082 ，设置 → Agentic 勾选工具，新开对话

详见 README.md 与 docs/pitfalls.md
TIP
