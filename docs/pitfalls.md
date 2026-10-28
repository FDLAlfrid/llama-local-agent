# 踩坑记录

全部来自真实环境：Intel i5-13500H / Iris Xe 核显 / 32 GB DDR4-3200 / Debian，模型 Qwen3-8B Q4_K_M。

---

## 1. `vk::Device::waitForSubmit: ErrorDeviceLost`

**现象**：8192 token 的提示词，必崩。

```
send_error: decode() failed: vk::Device::waitForFences: ErrorDeviceLost
n_tokens = 8192
terminate called after throwing an instance of 'vk::DeviceLostError'
```

**隔离实验**（同一模型、同一提示词）：

| # | ubatch | KV 位置 | 结果 | prefill |
|---|---|---|---|---|
| A | 512 | 显存 | ❌ 崩 | 95 → 35 t/s |
| B | 256 | 内存 | ✅ | 36 t/s |
| C | 256 | 显存 | ✅ | 38 t/s |
| D | 512 | 内存 | ✅ | 46 → 36 t/s |

**结论**：触发条件是 `ubatch 512` + KV 放显存。Intel ANV 驱动在 8K 处分配失败。

**采用**：`--no-kv-offload -ub 512`（D 方案），速度与稳定性都不亏。

---

## 2. `--reasoning off` 会隐藏 WebUI 的思考开关

`--reasoning off` 不只是关思考，它让 UI 判断"模型不支持思考"，把开关整个藏起来。

想保留入口：`--reasoning auto`。

**另外**：很多小模型的 chat template 里只有 `enable_thinking`（开/关），没有 `reasoning_effort` 分档。查证：

```bash
curl -s localhost:8082/props | jq '.default_generation_settings.supports_reasoning_effort'
# false  → low/medium/high 行为完全相同
```

开启思考后速度从 5.5 掉到 1.3–2.3 t/s，且小 `max_tokens` 时全部输出落在 `reasoning_content`，`content` 为空——看起来像"模型傻了"，其实是 token 被思考吃光了。

---

## 3. 能力静默降级：环境变量丢失

`--tools`、`--ui-mcp-proxy` 若靠外部环境变量传给启动脚本，任何直接调用（手工敲、systemd、另一个脚本）都会丢。

表现：昨天能读写文件，今天只会说"我无法访问本地文件"。

**解法**：默认值下沉到启动脚本内部，别依赖调用方。

```bash
: "${LLAMA_TOOLS:=all}"      # 不在环境里也用这个值
: "${LLAMA_MCP_PROXY:=1}"
```

---

## 4. `--agent` 参数不存在

问模型"怎么让你能操作文件"，它可能回答：

> 尝试启动 llama-server 并使用 `--agent` 参数

**没有这个参数**。以 `llama-server --help` 为准。实际是 `--tools all`。

这类幻觉通常出现在模型**没有工具定义**的时候——它在用训练数据里见过的说法补空。

---

## 5. 下载进度不能用 `ls -l` 判断

`curl -C -` 续传会预分配文件大小，`ls -l` 一开始就显示完整大小，实际数据还没写。

**正确做法**：

```bash
# 对比远端
curl -sI "$URL" | grep -i content-length
# 或
sha256sum model.gguf    # 与仓库页面的哈希比对
```

`aria2c` 同理——`.aria2` 控制文件才是进度真相。

---

## 6. 模型放 `~/.cache/` 会被清理工具删

各种 "clean" 脚本的默认目标就包含 `~/.cache`。5 GB 的模型说没就没，还不进回收站。

放 `~/.local/share/models/` 或独立目录（如 `/srv/models`）。

---

## 7. 端口冲突

llama.cpp 启动时会 `best-effort kill` 占用目标端口的进程。这意味着：

- 端口被别的服务占着 → 那个服务被杀，不是你想要的
- 你自己的脚本也监听同端口 → 互相杀

启动前先确认：

```bash
ss -ltnp 'sport = :8082'
```

---

## 8. 换模型后旧的会话上下文不兼容

WebUI 的历史存在浏览器里，换模型不会清。旧模型的对话喂给新模型，容易出现格式错乱（尤其 tool_calls 记录）。

换模型后**新开对话**。
