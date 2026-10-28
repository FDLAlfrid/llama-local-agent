# llama-local-agent

在 Linux 上跑一个**能读写文件、执行命令、联网**的本地大模型，全程离线推理，不需要 API key。

配套 llama.cpp 的 `--tools all` + 一个固定工作目录。

## 1. 硬件前提

| 项目 | 建议 |
|---|---|
| 内存 | 8B 模型 Q4_K_M 需要 ~6 GB 可用；16 GB 起步 |
| 显存 | 可选。Intel/AMD 核显也能用（Vulkan），比纯 CPU 快 50–80% |
| 磁盘 | 每个模型 1–5 GB |

推理瓶颈通常是**内存带宽**，不是显存。8B Q4 在双通道 DDR4-3200 上约 5.5 tok/s。

## 2. 装 llama.cpp

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_VULKAN=ON      # 不用 GPU 就去掉这行
cmake --build build -j"$(nproc)"
sudo cmake --install build
```

## 3. 拿模型

```bash
mkdir -p ~/models
curl -L -C - -o ~/models/model.gguf \
  "https://hf-mirror.com/<repo>/resolve/main/<file>.gguf"
```

**别用 `ls -l` 判断下载是否完成**——续传会预分配空间，大小早就到终点。用 `curl -sI` 对比 `Content-Length` 或核对 sha256。

## 4. 启动：关键是 `--tools all`

```bash
mkdir -p ~/llama-workspace
llama-server \
  -m ~/models/model.gguf \
  --host 127.0.0.1 --port 8082 \
  -c 16384 \
  -ngl 99 \
  --no-kv-offload \
  -b 2048 -ub 512 \
  -t 8 \
  --flash-attn on \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --jinja \
  --tools all \
  --ui-mcp-proxy
```

| 参数 | 作用 |
|---|---|
| `--tools all` | 开内置工具：`read_file`、`write_file`、`edit_file`、`file_glob_search`、`grep_search`、`exec_shell_command`、`get_info`。**这是让它能动手的唯一开关** |
| `--jinja` | 用模型自带 chat template，否则 tool_calls 格式对不上 |
| `--no-kv-offload` | KV cache 放内存而非显存，见坑 1 |
| `-ngl 99` | 权重全给 GPU，核显也受益 |
| `-b 2048 -ub 512` | 批 / 微批，prefill 与显存占用的平衡点 |
| `-c 16384` | 上下文长度 |

打开 http://127.0.0.1:8082 ，在**设置 → Agentic** 里勾选工具，然后**新开一个对话**（旧对话不会自动获得工具）。

## 5. 验证它真的能动手

问它「列一下工作目录里有什么」。应该返回 `tool_calls` 调 `exec_shell_command`，而不是回答「我在浏览器环境无法访问文件」。编造答案 = 工具没开或没新开会话。

## 坑

### 1. `vk::Device::waitForSubmit: ErrorDeviceLost`（8192 token 处崩）

| 方案 | prefill | 稳定 |
|---|---|---|
| `ubatch 256` + KV 显存 | 36 t/s | ✅ |
| `ubatch 512` + KV 内存 | 46 t/s | ✅ |
| `ubatch 512` + KV 显存 | 95→35 t/s | ❌ 崩 |

推荐第二种：`--no-kv-offload` + `-ub 512`。

### 2. `--reasoning off` 会隐藏 UI 上的思考开关

想保留入口写 `--reasoning auto`。另外很多小模型只有 `enable_thinking`，**没有** `reasoning_effort` 分档——`low/medium/high` 行为相同（查 `/props` 的 `supports_reasoning_effort`）。

### 3. 环境变量丢失导致能力静默降级

`--tools`、`--ui-mcp-proxy` 若靠外部环境变量传递，任何绕过启动脚本的直接调用都会丢，表现为「昨天能读写文件，今天不行」。

### 4. `--agent` 参数不存在

模型会一本正经地说「用 `llama-server --agent`」——没有这个参数，以 `--help` 为准。

### 5. 缓存目录被清理工具误删

模型放 `~/.cache/` 下会被当垃圾扫走，放 `~/.local/share/` 或独立目录。

## 它不能做什么

- 不会"看见"图片，除非多模态模型（`-mmproj`）
- 没有长期记忆，新对话是白纸
- 工具执行需在 WebUI 确认（设计如此，别关）

## License

MIT
