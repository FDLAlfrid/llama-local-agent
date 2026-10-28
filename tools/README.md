# 自制工具

这台机器上用得上的一些小工具，都是单文件 shell/Python，无依赖（除了系统自带的 bash/python3）。

## 本地大模型启动器

| 文件 | 作用 |
|---|---|
| `llama-launcher.sh` | 总入口。菜单：1 启动 / 2 角色扮演 / 3 停止 / 4 状态 / 5 日志 / 7 QQ 机器人 / 8 连接设置 / 9 角色与世界 |
| `server.sh` | 真正的启动内核：模型发现、参数拼装、健康检查、pid 校验 |
| `pick-persona` | 从 `personas.json` 列编号选角色，写进 `var/persona.txt` |

目录结构（放到 `~/llama/` 即可用）：

```
~/llama/
├── llama.sh            -> bin/llama
├── bin/{llama,pick-persona}
├── core/server.sh
├── bridge/             # QQ 桥（可选）
├── models/             # .gguf
└── var/                # 日志、pid、备份
```

`server.sh` 关键默认值，都可用环境变量覆盖：

```bash
LLAMA_BIN=llama-server          # 二进制路径
MODELS_DIR=$HOME/models         # 模型目录
PORT=8082  HOST=127.0.0.1
CTX=16384  THREADS=8  NGL=999
KV_GPU=0                        # 0 = KV 放内存（防 Vulkan 崩溃）
LLAMA_TOOLS=all                 # 文件/命令工具，别关
LLAMA_MCP_PROXY=1
```

### 为什么值得抄

- **pid 三重校验**：`kill -0` + `/proc/<pid>/stat` 非 `Z` + `cmdline` 含 `llama-server`。只靠 `kill -0` 会把僵尸进程当活着，导致"显示运行中但没响应"。
- **能力默认值下沉**：`LLAMA_TOOLS`、`LLAMA_MCP_PROXY` 在脚本内部 `: "${VAR:=默认}"`，任何直接调用都不会丢工具。
- **按端口杀进程**：`ss -ltnp 'sport = :8082'` 取 pid，而不是 `pkill -f llama`——后者会把你自己的 shell 一起 SIGTERM 掉（踩过很多次）。
- **健康检查轮询**：启动后轮询 `/health` 最多 120 秒，而不是 `sleep 5` 赌它起来了。

## 磁盘与备份

| 工具 | 作用 | 要点 |
|---|---|---|
| `bigmove` | 把家目录大目录搬到别的盘并留软链 | rsync → 比对字节数 → 才删原件 → 建软链；`-n` 演习模式 |
| `spaceguard` | 分区容量看门狗，85% 警告 / 92% 严重 | systemd timer 每 6 小时；**测试时不要用真实 notify-send**，会弹假警报 |
| `hs-unity-cache` | 从已安装的游戏文件重建启动器缓存 | 绕开官方 404 镜像；15 秒完成，5 GB 的下载变成 14 MB |
| `hs-ngdp-sync` | 修正 NGDP 清单里被兼容层改过的 mtime | 否则每次启动都重下 6 MB 的三个 DLL |
| `bin-backup` | 工具目录 git 快照 + 裸仓库副本 | 每天 03:00 |

## 手机 / ADB

| 工具 | 作用 |
|---|---|
| `adb-5555` | 起 server → 取设备 IP → 设常亮 → `tcpip 5555` → connect |
| `shizuku-start` | 通过 USB 选中设备，启动 Shizuku server 并校验进程 |
| `adb-watch` | 轮询 `/sys/bus/usb/devices`，判断设备是否暴露了 ADB 接口（`configuration` 里有没有 `_adb`） |
| `termux-llm.sh` | 在 Termux/ZeroTermux 里一键部署 llama.cpp：测速换源、按可用内存选模型、状态机判断首次运行 |

### ADB 排查经验

`lsusb` 能看到设备 ≠ adb 能用。真正的判据是：

```bash
lsusb -v -d 12d1:107e 2>/dev/null | grep -i configuration
# hisuite_mtp_mass_storage        → 只有 MTP，没开 USB 调试
# hisuite_mtp_mass_storage_adb    → 有 ADB 接口，能连
```

接口层面：ADB 是 `class=ff, subclass=42, protocol=01`。没有这个接口，电脑侧 udev 配得再对也没用。

## 踩过的坑（通用）

1. `pkill -f '<你的命令>'` 会匹配到自己所在的 `bash -c`，把自己杀掉。用 `ss -ltnp` 拿 pid。
2. 稀疏文件不能用 `ls -l` 判断下载进度（aria2c/curl 续传会预分配）。
3. Python 后台脚本重定向到日志时加 `PYTHONUNBUFFERED=1`，否则日志一直是空的。
4. `set -e` 下 `x="$(cmd || echo)"` 这类写法很危险：命令替换失败会让赋值返回非零，脚本静默退出。
5. 系统 `df -Pm` 在 Android 上列错位，用 `stat -f -c '%a %S'` 算可用空间。
6. 后台服务别直接 `nohup`，用 `setsid`——否则关掉终端一起死。

## License

MIT
