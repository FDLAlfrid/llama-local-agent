# 插件规范（给本地模型看的）

你要做的是**填一份 JSON**，不是写代码。写代码的模板已经在了。

## 目录

```
plugins/<id>/
  manifest.json   必填，声明
  ui.js           可选，注入网页的脚本
  data/           私有数据，宿主自动创建
  README.md       可选
```

`<id>` 用小写字母、数字、短横线；`builtin-` 前缀是内置插件专用，别占。

## manifest.json 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 与目录名一致 |
| `name` | 是 | 界面上显示的按钮文字，**≤4 个汉字** |
| `version` | 是 | `0.1.0` 这种 |
| `description` | 否 | 一句话，面板里显示 |
| `ui` | 否 | 通常是 `ui.js` |
| `actions` | 否 | 用到的内置动作，可选 `get` `set` `list` |
| `enabled` | 否 | 默认 true |
| `kind` | 否 | 别写，宿主按前缀自动判定 |

## 能用的东西（不用自己实现）

| 接口 | 作用 |
|---|---|
| `GET /__plugin/<id>/get?key=K` | 读一个键 |
| `GET /__plugin/<id>/set?key=K&value=V` | 写一个键 |
| `GET /__plugin/<id>/get` | 读全部（JSON） |
| `GET /__plugin/list` | 列出所有插件 |

数据落在 `plugins/<id>/data/kv.json`，越界路径会被拒。

## 界面约定（保持简洁）

1. **一个按钮**，文字就是 `name`，挂到 `#cmdbar`（右下角那排）
2. 点开才出现面板，**不要一进来就弹窗**
3. 面板宽度 ≤ 300px，深色背景 `rgba(22,22,26,.98)`，圆角 10px
4. 主要操作 **≤4 个按钮**
5. 结果就地显示，不要 `alert` 刷屏

## 最简单的做法

```bash
bin/llama-plugin new my-thing --tpl kv --name 我的按钮
```

然后只改 `manifest.json` 里的 `description`，和 `ui.js` 里你要的交互。

## 模板

| 模板 | 已经写好的 |
|---|---|
| `kv` | 按钮 + 读写一个键 |
| `prompt` | 按钮 + 每轮插入一段话 |

## 自检

```bash
bin/llama-plugin list      # 能看到、✓ 表示启用
curl localhost:8093/__plugin/<id>/ui.js
```
