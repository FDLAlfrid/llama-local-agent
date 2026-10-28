"""插件宿主：扫描 plugins/*/manifest.json，注入 UI，提供 /__plugin/<id>/* 路由。
插件不写 Python 代码：只声明 manifest + ui.js，后端逻辑走内置 action（template 提供）。
"""
import json, os, re

class PluginHost:
    def __init__(self, root):
        self.root = os.path.join(root, "plugins")
        self.items = {}
        self.load()

    def load(self):
        self.items = {}
        if not os.path.isdir(self.root):
            return
        for name in sorted(os.listdir(self.root)):
            d = os.path.join(self.root, name)
            mf = os.path.join(d, "manifest.json")
            if not os.path.isfile(mf):
                continue
            try:
                m = json.load(open(mf, encoding="utf-8"))
            except Exception as e:
                print(f"[plugin] {name}: manifest 解析失败 {e}", flush=True)
                continue
            m.setdefault("id", name)
            m.setdefault("name", m["id"])
            m.setdefault("version", "0.0.0")
            m.setdefault("enabled", True)
            m.setdefault("kind", "builtin" if name.startswith("builtin-") else "user")
            m["_dir"] = d
            self.items[m["id"]] = m
        print(f"[plugin] 已加载 {sum(1 for m in self.items.values() if m['enabled'])}/{len(self.items)} 个插件", flush=True)

    def list(self):
        return [{"id": m["id"], "name": m["name"], "version": m["version"],
                 "enabled": m["enabled"], "kind": m.get("kind", "user"),
                 "description": m.get("description", "")}
                for m in self.items.values()]

    def scripts(self):
        out = []
        for m in self.items.values():
            if not m["enabled"] or not m.get("ui"):
                continue
            if os.path.isfile(os.path.join(m["_dir"], m["ui"])):
                out.append(m["id"])
        return out

    def read_ui(self, pid):
        m = self.items.get(pid)
        if not m or not m.get("ui"):
            return None
        fp = os.path.join(m["_dir"], m["ui"])
        return open(fp, encoding="utf-8").read() if os.path.isfile(fp) else None

    def data_file(self, pid, rel):
        """插件私有数据目录 plugins/<id>/data/<rel>，越界拒绝"""
        m = self.items.get(pid)
        if not m:
            return None
        base = os.path.realpath(os.path.join(m["_dir"], "data"))
        os.makedirs(base, exist_ok=True)
        fp = os.path.realpath(os.path.join(base, rel))
        return fp if fp.startswith(base) else None

TPL = {
 "kv": {
   "manifest": {"name": "我的记忆", "version": "0.1.0", "description": "键值存储示例",
                "ui": "ui.js", "actions": ["get", "set", "list"], "kind": "user"},
   "ui": ("// 通用按键面板\n"
          "const b = document.createElement('button');\n"
          "b.textContent = NAME; b.style.cssText='all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44';\n"
          "document.querySelector('#cmdbar')?.appendChild(b);\n"
          "b.onclick = async () => {\n"
          "  const k = prompt('键'); if (!k) return;\n"
          "  const v = prompt('值（留空=读取）');\n"
          "  const u = `/__plugin/${ID}/${v ? 'set' : 'get'}?key=${encodeURIComponent(k)}` + (v ? `&value=${encodeURIComponent(v)}` : '');\n"
          "  const r = await fetch(u);\n"
          "  alert(await r.text());\n"
          "};\n"),
 },
 "prompt": {
   "manifest": {"name": "提示词片段", "version": "0.1.0", "description": "往每轮开头插入一句话",
                "ui": "ui.js", "hooks": ["prompt"], "kind": "user"},
   "ui": ("const b = document.createElement('button');\n"
          "b.textContent = NAME; b.style.cssText='all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44';\n"
          "document.querySelector('#cmdbar')?.appendChild(b);\n"
          "b.onclick = async () => {\n"
          "  const t = prompt('每轮插入的内容', await (await fetch('/__plugin/'+ID+'/get')).text());\n"
          "  if (t === null) return;\n"
          "  await fetch('/__plugin/'+ID+'/set', { method:'POST', body: JSON.stringify({ value: t }) });\n"
          "};\n"),
 },
}

def scaffold(root, pid, tpl="kv", name=None):
    d = os.path.join(root, "plugins", pid)
    if os.path.exists(d):
        return False, f"已存在: {d}"
    t = TPL.get(tpl)
    if not t:
        return False, f"模板只能是: {', '.join(TPL)}"
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    m = dict(t["manifest"])
    if name:
        m["name"] = name
    json.dump(m, open(os.path.join(d, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    ui = t["ui"].replace("ID", json.dumps(pid)).replace("NAME", json.dumps(m["name"]))
    open(os.path.join(d, "ui.js"), "w", encoding="utf-8").write(ui)
    open(os.path.join(d, "README.md"), "w", encoding="utf-8").write(
        f"# {m['name']}\n\n模板：{tpl}\n\n- 界面：`ui.js`（注入到网页，可改）\n- 数据：`data/`\n- 声明：`manifest.json`\n")
    return True, d
