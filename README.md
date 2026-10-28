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


## 7. 扩展工具（MCP 与自写脚本）

`--tools all` 给的是**内置 7 个工具**，到此为止。想让模型多会一件事，有两条路。

### 7.1 先判断：真的需要新工具吗

`exec_shell_command` 等于"能运行任何程序"。所以「让它会画表情包」不需要新增工具：

> 你写个 Python 脚本，用 Pillow 画 400x400 白底黑框，文字自动折行，存到 /tmp/x.png

它会自己 `pip install pillow`、写脚本、跑、看报错再改。**先把这条路走通，再考虑 MCP。**

### 7.2 MCP：把外部程序变成工具

llama.cpp 自己**不实现**具体工具，它当 MCP 客户端。`--ui-mcp-proxy` 的作用是让 WebUI 去连你配置的 MCP server。

```bash
llama-server ... --tools all --ui-mcp-proxy
```

然后在 WebUI 的 **Settings → MCP Servers** 里登记 server（命令 + 参数 + 环境变量）。server 暴露的每个 tool 会以 `mcp__<server>__<tool>` 的形式出现在工具列表里。

⚠️ 这个功能在快速演进，flag 名称各版本可能不同。以你装的版本为准：

```bash
llama-server --help | grep -i mcp
```

### 7.3 不依赖 MCP 的工具循环（30 行）

思路：让模型把要执行的命令写在 ```run 代码块里，宿主执行、把结果回灌，最多两轮。

```python
import re, subprocess

def extract_run(text):
    m = re.search(r"```run\s*\n(.*?)```", text, re.S)
    return m.group(1).strip() if m else None

def run_shell(cmd, timeout=40):
    if re.search(r"rm\s+-rf\s+/(\s|$)", cmd):
        return "[拒绝] 危险命令"
    r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=timeout)
    return ((r.stdout + r.stderr).strip() or f"[退出码 {r.returncode}]")[:3000]

# 主循环
for _ in range(2):
    code = extract_run(answer)
    if not code: break
    out = run_shell(code)
    messages += [{"role": "assistant", "content": answer},
                 {"role": "user", "content": f"【命令输出】\n{out}\n请据此继续。"}]
    answer = chat(messages)
```

好处：不依赖 MCP、能跑在任何 OpenAI 兼容端点上、行为完全可控。
代价：没有权限确认弹窗——**必须自己做危险命令拦截**（上面那条 `rm -rf /` 只是最低限度）。

### 7.4 安全边界

| 方式 | 谁在把关 |
|---|---|
| WebUI + 内置工具 | 每次执行弹确认框 |
| WebUI + MCP | 取决于 MCP server 自己 |
| 自己的工具循环 | 只有你写的白名单 |

QQ / 微信这类无界面的桥，走的是第三种——**默认没有护栏**，上线前务必加白名单或容器隔离。

---

## 8. 文件清单

| 文件 | 内容 |
|---|---|
| `install.sh` | 一键编译安装（含 Vulkan 探测） |
| `docs/pitfalls.md` | 8 个坑的完整记录与实验数据 |
| `README.md` | 本文 |

## License

MIT

## 8. 工具调用：不要只写进人设

一个踩过的坑：在人设里写"你可以执行命令、读文件"，但请求里**没有 `tools` 字段**，模型就只能演戏——输出 bash、声称成功、再编一个输出。

正确做法是标准 function calling：

```python
body["tools"] = [
  {"type":"function","function":{"name":"run_shell", ...}},
  {"type":"function","function":{"name":"list_dir",  ...}},
]
body["tool_choice"] = "auto"
# 模型返回 tool_calls -> 宿主执行 -> 以 role:"tool" 回灌 -> 循环直到给出最终回答
```

完整实现见 [`bridge/qq_bridge.py`](bridge/qq_bridge.py)，包含三个坑的处理：

1. **路径展开** — 8B 会把 `$HOME`/`$(whoami)` 写进路径参数，必须自己展开
2. **轮次上限** — 不给上限它会一直试同一个错，5 轮封顶
3. **模式隔离** — 角色扮演的历史会污染工作模式，切换时必须换会话文件

