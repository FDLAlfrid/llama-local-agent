# QQ Bridge

把本地 llama-server 接到 QQ，带人设、世界书、会话与工具调用。纯 Python 标准库，无依赖（`qrcode`、`PIL` 可选）。

```
QQ 官方机器人 ──┐
                ├──> qq_bridge.py :8090 ──> llama-server :8082
NapCat OneBot ──┘         │
                          └──> 面板 :8091
```

## 为什么需要它

llama-server 有 WebUI，但：

- 没有持久的人设/世界观（每次要手贴 system prompt）
- 没有"每次进入角色就切档案"
- 手机上没有入口

这个桥补的就是这三件事，外加**真正的工具调用**（见下）。

## 两种接入方式

### A. 官方机器人（扫码，零封号风险）

```bash
cd qqbot && npm i @tencent-connect/qqbot-connector @tencent-connect/qqbot-nodejs
node sidecar.mjs        # 终端出二维码，手机 QQ 扫
```

扫码即完成"创建机器人 + 拿 AppID/AppSecret"，凭据落 `qqbot/creds.json`。sidecar 把消息转成 OneBot 事件 POST 到 `:8090`，并在 `:3000` 暴露 `/send_private_msg`、`/send_group_msg` 供桥回调。

**限制**：官方接口只推送 `GROUP_AT_MESSAGE_CREATE`，**收不到未 @ 的群消息**。想要"概率搭话"必须走 B。

### B. NapCat / Lagrange（能看到全部群消息）

它们以普通用户身份登录，OneBot 11 上报。桥不用改代码：

```json
{ "onebot_api": "http://127.0.0.1:3000", "group_mode": "all" }
```

代价：协议模拟，有封号风险，用小号。

## 配置 `config.json`

| 键 | 说明 |
|---|---|
| `onebot_api` | OneBot HTTP API 地址 |
| `llama` | llama-server 地址 |
| `model` | 模型名 |
| `whitelist` / `auto_allow` | 白名单 openid；`auto_allow` 放开所有人 |
| `group_mode` | `mention` 只回@ / `keyword` 关键词 / `all` @或概率 |
| `reply_min_interval`, `reply_probability` | 群内搭话的间隔与概率 |
| `max_tokens`, `temperature`, `history_turns`, `max_context_chars` | 生成与上下文 |
| `default_persona` | 新用户默认角色 |
| `tools` | 是否启用工具调用（默认 true） |

数据目录 `data/`：`personas.json`、`worldbook.json`、`users.json`、`sessions/<openid>__<角色>__<模式>.json`。

## 指令

```
/               帮助
/ctx /stats     上下文与统计
/new /reset     新会话 / 清空（all = 连记忆一起清）
/mode work|role 工作模式 / 角色模式
/who [名字]     查看或切换人设
/persona        列出人设（管理员可增删）
/world          世界书列表与开关（管理员）
/compact        压缩早期对话进记忆
/backup         立即备份
```

`/mode` 切换会**清空历史并换档案文件**——否则角色口癖会被历史带进工作模式。

## 工具调用（重要）

早期版本有个设计错误：人设里写着"你能执行命令"，但请求里**没有 tools 字段**。模型没有工具，只能对着人设演戏——输出 bash 命令、声称执行成功、再编一个输出。

现在走标准 OpenAI function calling：

```python
body["tools"] = [run_shell, list_dir, read_file]
body["tool_choice"] = "auto"
# 模型返回 tool_calls -> 本机执行 -> role:"tool" 回灌 -> 最多 5 轮
```

三个工具：

| 工具 | 说明 |
|---|---|
| `run_shell` | `bash -lc`，超时 40s，输出截 3000 字，拒绝 `rm -rf /` |
| `list_dir` | 列目录（名称/类型/大小），支持 `*?[` 通配 |
| `read_file` | 读前 N 行 |

### 小模型的坑

8B 会把 shell 展开直接写进路径参数：

```
list_dir("/home/$USER/Desktop")      # 它以为你会展开
list_dir("/home/$(whoami)/Desktop")
```

`resolve_path()` 用 `bash -lc 'printf %s "<path>"'` 兜住这类写法，否则你会看到一串 `No such file or directory`，然后模型开始编。

## 安全

- `sudo_pass` 从环境变量 `SUDO_PASS` 读，不要写进 `config.json`
- 白名单按 openid 硬校验
- 无界面通道（QQ）**没有交互确认**，`run_shell` 就是真执行
- 建议在容器或独立用户下跑

## License

MIT
