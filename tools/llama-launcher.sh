#!/usr/bin/env bash
# 总启动器（脚本本体）。可直接跑，也可经外面的软链 llama.sh 调用。
exec "$(dirname "$(readlink -f "$0")")/bin/llama" "$@"
