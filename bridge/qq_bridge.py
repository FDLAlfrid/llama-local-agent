#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QQ ↔ 本地 llama 桥（OneBot 11 / HTTP 上报 + HTTP API）
   - 白名单、每会话独立上下文、人设、世界书、全部持久化为 JSON
   - 不依赖第三方库，只用标准库
"""
from fnmatch import fnmatch
import json, os, re, threading, time, urllib.request, random, subprocess, base64, tempfile
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
SESS = os.path.join(DATA, "sessions")
for d in (DATA, SESS):
    os.makedirs(d, exist_ok=True)

DEFAULTS = {
    "onebot_api": "http://127.0.0.1:3000",
    "llama": "http://127.0.0.1:8082",
    "model": "local",
    "whitelist": [],
    "allow_group": False,
    "max_tokens": 400,
    "history_turns": 10,
    "max_context_chars": 6000,
    "temperature": 0.7,
    "port": 8090,
    "ack": True,
    "system_suffix": "回答用中文，简洁直接，不要复述问题。",
    "group_mode": "keyword",
    "group_whitelist": [],
    "keywords": ["咕咕", "斑鸠", "大肥鱼", "肥鱼"],
    "reply_min_interval": 45,
    "reply_probability": 0.5,
    "tools": True,
    "sudo_pass": os.environ.get("SUDO_PASS",""),
}

def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

CFG = os.path.join(ROOT, "config.json")
if not os.path.exists(CFG):
    _save(CFG, DEFAULTS)
CONF = {**DEFAULTS, **_load(CFG, {})}

SESS_DIR = os.path.join(DATA, "sessions")
PERSONA_F = os.path.join(DATA, "personas.json")
WORLD_F = os.path.join(DATA, "worldbook.json")
if not os.path.exists(PERSONA_F):
    _save(PERSONA_F, {"默认": {"prompt": "你是一个中文助手，回答准确、简短。", "updated": int(time.time())}})
if not os.path.exists(WORLD_F):
    _save(WORLD_F, [])

lock = threading.Lock()

USERS_F = os.path.join(DATA, "users.json")

def cur_persona(uid):
    u = _load(USERS_F, {})
    return (u.get(str(uid)) or {}).get("persona") or CONF.get("default_persona") or "大肥鱼"

def set_persona(uid, name):
    u = _load(USERS_F, {}); u[str(uid)] = {"persona": name}; _save(USERS_F, u)

def sess_path(uid, persona=None, mode=None):
    m = mode or "work"
    return os.path.join(SESS, f"{uid}__{persona or cur_persona(uid)}__{m}.json")

def get_sess(uid, persona=None, mode=None):
    p = sess_path(uid, persona, mode)
    s = _load(p, {})
    s.setdefault("persona", persona or cur_persona(uid))
    s.setdefault("history", [])
    s.setdefault("mode", "work")
    return s

def put_sess(uid, s):
    _save(sess_path(uid, s.get("persona"), s.get("mode")), s)

# ---------- llama ----------
TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "列出目录内容。only=dir 只看子目录，only=file 只看文件，pattern 可按 *.md 这类通配符过滤。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "目录绝对路径，例如 /home/alfrid/Desktop；不要写 $HOME 或 $(whoami)"},
            "only": {"type": "string", "enum": ["both", "dir", "file"]},
            "pattern": {"type": "string"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "find_path",
        "description": "在目录里按名字查找。默认 depth=1 只查这一层；只有用户明确要求「往下找/递归」时才把 depth 调大。",
        "parameters": {"type": "object", "properties": {
            "root": {"type": "string"}, "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["any", "dir", "file"]},
            "depth": {"type": "integer", "description": "向下查几层，默认 1"},
            "fuzzy": {"type": "boolean", "description": "模糊匹配：字符按顺序出现或拼写接近也算命中，默认 true"}},
            "required": ["root", "name"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取文本文件，可指定起始行 start 与行数 lines（默认前 120 行）。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start": {"type": "integer"}, "lines": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "grep_text",
        "description": "按正则搜索文本内容，返回 文件:行号:内容。ignore_case 默认 true；include 可按 *.py 限定文件类型；path 可以是文件或目录。",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"}, "max": {"type": "integer"},
            "ignore_case": {"type": "boolean"}, "include": {"type": "string"}},
            "required": ["pattern", "path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "写文件。mode=overwrite 覆盖（会先备份原文件）、append 追加。父目录不存在会自动创建。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "mode": {"type": "string", "enum": ["overwrite", "append"]}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "在 bash 里执行命令，返回 stdout/stderr 与退出码。可指定 timeout 与 cwd。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}, "timeout": {"type": "integer"}, "cwd": {"type": "string"}},
            "required": ["command"]}}},
]

HOME = os.path.expanduser("~")

def resolve_path(p):
    """容忍模型瞎编的路径：占位符用户名、shell 展开、~、引号；实在没有就按末段去找。"""
    p = (p or "").strip().strip('"').strip("'")
    for fake in ("/home/username", "/home/user", "/home/your_username", "/home/yourname", "/home/alfred"):
        if p.startswith(fake):
            p = HOME + p[len(fake):]; break
    if not p: return p
    if "$" in p or "`" in p:
        try:
            r = subprocess.run(["bash", "-lc", f'printf %s "{p}"'], capture_output=True, text=True, timeout=10)
            if r.stdout.strip(): p = r.stdout.strip()
        except Exception: pass
    p = os.path.expanduser(p)
    if p and not os.path.exists(p):
        leaf = os.path.basename(p.rstrip("/"))
        if leaf and leaf not in ("", "/"):
            try:
                for root in (HOME, os.path.join(HOME, "Desktop"), os.path.join(HOME, "Documents")):
                    for name in os.listdir(root):
                        if name == leaf:
                            cand = os.path.join(root, name)
                            print(f"[path] {p} -> {cand}", flush=True)
                            return cand
            except Exception:
                pass
    return p

def backup_write(path):
    """覆盖前把原文件复制到 var/backups/writes/，保留最近 100 份。"""
    try:
        d = os.path.join(ROOT, "..", "var", "backups", "writes")
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, time.strftime("%Y%m%d-%H%M%S-") + os.path.basename(path))
        shutil.copy2(path, dst)
        fs = sorted((os.path.join(d, f) for f in os.listdir(d)), key=os.path.getmtime)
        for old in fs[:-100]:
            os.remove(old)
        return dst
    except Exception as e:
        return ""

def exec_tool(name, args):
    """统一入口：参数容错 + 单工具超时 + 异常兜底。"""
    try:
        a = json.loads(args) if isinstance(args, str) else (args or {})
        if not isinstance(a, dict): a = {}
    except Exception:
        return "[参数不是合法 JSON，请重新用正确的 JSON 对象调用]"
    try:
        if name == "list_dir":
            p = resolve_path(a.get("path", ""))
            if not os.path.isdir(p): return f"[不是目录] {p}"
            only = a.get("only", "both"); pat = a.get("pattern") or ""
            rows = []
            for e in sorted(os.scandir(p), key=lambda x: (not x.is_dir(), x.name))[:300]:
                try: sz = e.stat().st_size if e.is_file() else 0
                except Exception: sz = 0
                if only == "dir" and not e.is_dir(): continue
                if only == "file" and not e.is_file(): continue
                if pat and not fnmatch(e.name, pat): continue
                rows.append(f"{'[D]' if e.is_dir() else '[F]'} {sz:>10}  {e.name}")
            return (f"{p}（{len(rows)} 项）:\n" + "\n".join(rows)) if rows else f"{p}: 没有匹配的条目"
        if name == "find_path":
            root = resolve_path(a.get("root", "~")); kw = (a.get("name") or "").lower()
            kind = a.get("kind", "any")
            if not kw: return "[需要 name 关键词]"
            fuzzy = a.get("fuzzy", True)
            def hitname(n):
                n = n.lower()
                if kw in n: return True
                if not fuzzy: return False
                it = iter(n)
                return all(ch in it for ch in kw)   # 子序列匹配：codebdy -> codebuddy
            hits, base = [], root.rstrip("/").count(os.sep)
            maxd = max(1, min(int(a.get("depth") or 1), 6))
            SKIP = {".git", "node_modules", ".cache", ".dsh", "__pycache__", ".local"}
            for dirpath, dirnames, filenames in os.walk(root):
                if dirpath.count(os.sep) - base >= maxd:
                    dirnames[:] = []
                    for f in filenames:
                        if hitname(f) and kind in ("any", "file"):
                            hits.append(os.path.join(dirpath, f))
                    continue
                dirnames[:] = [d for d in dirnames if d not in SKIP]
                for d in dirnames:
                    if hitname(d) and kind in ("any", "dir"):
                        hits.append(os.path.join(dirpath, d) + "/")
                for f in filenames:
                    if kw in f.lower() and kind in ("any", "file"):
                        hits.append(os.path.join(dirpath, f))
                if len(hits) > 200: break
            return "\n".join(hits[:200]) if hits else f"{root} 下没有名字含「{kw}」的条目"
        if name == "read_file":
            p = resolve_path(a.get("path", ""))
            if not os.path.isfile(p): return f"[不是文件] {p}"
            st = int(a.get("start") or 1); n = int(a.get("lines") or 120)
            out = []
            with open(p, errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if i < st: continue
                    if i >= st + n: break
                    out.append(f"{i:>5}| {line.rstrip()}")
            return "".join(x + "\n" for x in out) or "（空文件）"
        if name == "write_file":
            p = resolve_path(a.get("path", ""))
            content = a.get("content", "")
            mode = a.get("mode", "overwrite")
            if not p: return "[需要 path]"
            for bad in ("/etc", "/usr", "/boot", "/sys", "/proc", "/dev",
                        os.path.expanduser("~/.ssh"), os.path.expanduser("~/.gnupg")):
                if p == bad or p.startswith(bad + "/"):
                    return f"[拒绝] 受保护路径 {p}"
            d = os.path.dirname(p)
            if d: os.makedirs(d, exist_ok=True)
            bak = ""
            if os.path.exists(p) and mode != "append":
                bak = backup_write(p)
            with open(p, "a" if mode == "append" else "w", encoding="utf-8") as f:
                f.write(content)
            return f"已写入 {p}（{len(content)} 字符，{mode}）" + (f"；原文件备份 {bak}" if bak else "")
        if name == "grep_text":
            pat = a.get("pattern") or ""; p = resolve_path(a.get("path", ""))
            if not pat: return "[需要 pattern]"
            if not os.path.exists(p): return f"[路径不存在] {p}"
            cmd = ["grep", "-InE", "--binary-files=without-match"]
            if a.get("ignore_case", True): cmd.append("-i")
            if os.path.isdir(p):
                cmd.append("-r")
                inc = a.get("include") or ""
                if inc: cmd.append(f"--include={inc}")
                for d in (".git", "node_modules", ".cache", "__pycache__", ".dsh"):
                    cmd.append(f"--exclude-dir={d}")
            cmd += [pat, p]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
            if r.returncode not in (0, 1):
                return f"[grep 出错] {(r.stderr or '').strip()[:200]}"
            lines = (r.stdout or "").splitlines()[:int(a.get("max") or 40)]
            return "\n".join(lines) if lines else "（没有命中）"
        if name == "run_shell":
            return run_shell(a.get("command") or "",
                             timeout=min(int(a.get("timeout") or 30), 120),
                             cwd=resolve_path(a.get("cwd") or "~"))
    except subprocess.TimeoutExpired:
        return "[执行超时]"
    except Exception as ex:
        return f"[{name} 出错] {type(ex).__name__}: {ex}"
    return f"[未知工具] {name}"

def llama_chat_msg(messages, tools=None, max_tokens=None):
    body = {"model": CONF["model"], "messages": messages,
            "max_tokens": max_tokens or CONF["max_tokens"],
            "temperature": CONF["temperature"], "stream": False}
    if tools: body["tools"] = tools; body["tool_choice"] = "auto"
    req = urllib.request.Request(CONF["llama"].rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["choices"][0]["message"]

def llama_chat(messages, max_tokens=None):
    body = json.dumps({
        "model": CONF["model"],
        "messages": messages,
        "max_tokens": max_tokens or CONF["max_tokens"],
        "temperature": CONF["temperature"],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        CONF["llama"].rstrip("/") + "/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    return (d["choices"][0]["message"].get("content") or "").strip()

# ---------- onebot ----------
def send(action, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        CONF["onebot_api"].rstrip("/") + "/" + action,
        data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except Exception as e:
        print("[onebot] send fail:", e, flush=True)
        return {}

def reply(ev, text):
    if ev.get("message_type") == "group" and ev.get("group_id"):
        send("send_group_msg", {"group_id": ev["group_id"], "message": text})
    else:
        send("send_private_msg", {"user_id": ev["user_id"], "message": text})

# ---------- 人设 / 世界书 ----------
def personas():
    return _load(PERSONA_F, {})

def worldbook():
    return _load(WORLD_F, [])

def build_system(uid):
    s = get_sess(uid)
    if s.get("mode") == "work":
        parts = ["你是这台机器上的编码助手，中文回答，先动手再解释。可执行命令、联网、用 sudo（echo droidvm | sudo -S）。"]
    else:
        p = personas().get(s["persona"]) or {"prompt": ""}
        parts = [p.get("prompt", "")]
    if s.get("mode") != "work":
        for w in worldbook():
            if w.get("enabled", True) and w.get("keyword"):
                parts.append(f"【{w.get('name') or '设定'}】{w.get('text','')}")
    parts.append(CONF["system_suffix"])
    return "\n\n".join([x for x in parts if x])

def trim(history):
    n = int(CONF["history_turns"]) * 2
    h = history[-n:] if n > 0 else history
    cap = int(CONF["max_context_chars"])
    total, out = 0, []
    for m in reversed(h):
        total += len(m.get("content", ""))
        if total > cap:
            break
        out.append(m)
    return list(reversed(out))

# ---------- 指令 ----------
HELP = """
╭─ 对话 ───────────────────────
│ /            这份帮助
│ /ctx         上下文占用 / 压缩阈值 / 当前模式
│ /stats       历史条数、字数、记忆长度
│ /new         清空本轮历史（记忆保留）
│ /memory      看长期记忆
│ /queue       排队情况
├─ 角色 ───────────────────────
│ /who         当前人设；/who 斑鸠 换人设
│ /mode work   纯工作模式（不注入人设世界观）
│ /mode role   切回角色扮演
├─ 工具 ───────────────────────
│ /sticker 字  生成表情图
├─ 管理员 ─────────────────────
│ /compact     立刻压缩早期对话
│ /reset all   历史 + 记忆一起清
│ /persona     看/管理人设
│ /world       看/管理世界书
│ /sys         看当前注入内容
│ /backup      立即备份
│ /backups     列备份
╰─────────────────────────────
"""

OWNER_ONLY = ("/persona", "/world", "/backup", "/sys", "/reset", "/compact")

def handle_cmd(uid, text):
    if not text.startswith("/"):
        return False, None
    _c = text.split()[0].lower()
    if _c in OWNER_ONLY and str(CONF.get("owner") or "") not in ("", str(uid)):
        return True, "这个指令只有管理员能用。你发 /bind 申请白名单就行。"
    if text.strip() == "/":
        return True, HELP.strip()
    a = text.split()
    c = a[0].lower()
    s = get_sess(uid)
    if c == "/help":
        return True, HELP.strip()
    if c in ("/reset", "/new"):
        s["history"] = []
        if len(a) > 1 and a[1].lower() == "all":
            s["memory"] = ""; put_sess(uid, s); return True, "已清空历史与长期记忆（人设保留）。"
        put_sess(uid, s); return True, "已清空本轮对话历史（长期记忆保留，用 /reset all 连记忆一起清）。"
    if c == "/backup":
        return True, backup()
    if c == "/backups":
        return True, list_backups()
    if c == "/queue":
        return True, f"排队 {len(_pending.get(uid) or [])} 条，{'生成中' if _busy.get(uid) else '空闲'}"
    if c == "/compact":
        return True, compact(uid)
    if c == "/memory":
        return True, s.get("memory") or "（暂无长期记忆）"
    if c == "/sys":
        return True, build_system(uid)
    if c == "/who":
        if len(a) > 1:
            if a[1] not in personas():
                return True, f"没有人设「{a[1]}」，用 /persona 看列表"
            set_persona(uid, a[1]); s = get_sess(uid)
        return True, f"当前人设：{s['persona']}"
    if c == "/mode":
        if len(a) == 1:
            return True, f"当前模式：{s.get('mode','role')}（role=角色扮演，work=纯工作）"
        m = a[1].lower()
        if m not in ("role", "work"):
            return True, "用法：/mode role 或 /mode work"
        old = sess_path(uid, s.get("persona"), s.get("mode"))
        s["mode"] = m
        s["history"] = []          # 换模式 = 换上下文，避免角色口癖带到工作模式
        put_sess(uid, s)
        try: os.remove(old)
        except Exception: pass
        return True, ("已切到工作模式：不注入人设与世界观，只当编码助手。" if m=="work"
                      else "已切到角色模式：恢复人设与世界观注入。")
    if c == "/ctx":
        chars = sum(len(m.get("content","")) for m in s["history"])
        return True, (f"上下文：{chars} 字 / {len(s['history'])} 条消息｜记忆 {len(s.get('memory',''))} 字\n"
                      f"压缩阈值 {COMPACT_AT} 字｜模型 {CONF.get('model','')}｜模式 {s.get('mode','role')}｜人设 {s['persona']}")
    if c == "/sticker":
        t = text[8:].strip() or "咕"
        path = f"/tmp/sticker_{int(time.time())}.png"
        if make_sticker(t, path):
            return True, ("[CQ:image,file=file://" + path + "]")
        return True, "生成失败（缺 Pillow 或字体），先看 /mode 是否 work"
    if c == "/stats":
        chars = sum(len(m.get("content","")) for m in s["history"])
        return True, f"人设 {s['persona']}｜历史 {len(s['history'])} 条 / {chars} 字｜记忆 {len(s.get('memory',''))} 字"
    if c == "/persona":
        P = personas()
        if len(a) == 1:
            return True, "人设：" + ("、".join(P) or "（空）")
        op = a[1]
        if op in ("add","set") and len(a) >= 4:
            P[a[2]] = {"prompt": " ".join(a[3:])}; _save(PERSONA_F, P)
            return True, f"已{'新增' if op=='add' else '更新'}人设 {a[2]}"
        if op == "del" and len(a) >= 3:
            P.pop(a[2], None); _save(PERSONA_F, P); return True, f"已删除 {a[2]}"
        return True, "用法：/persona add|set <名字> <正文>｜/persona del <名字>"
    if c == "/world":
        W = worldbook()
        if len(a) == 1:
            if not W: return True, "世界书是空的"
            return True, "\n".join(f"{i+1}. {w.get('name') or w.get('keyword','')} [{'开' if w.get('enabled',True) else '关'}] {w.get('text','')[:40]}" for i, w in enumerate(W))
        op = a[1]
        if op == "add" and len(a) >= 4:
            W.append({"keyword": a[2], "name": a[2], "text": " ".join(a[3:]), "enabled": True})
            _save(WORLD_F, W); return True, f"已加世界书 #{len(W)}"
        if op == "del" and len(a) >= 3:
            try: W.pop(int(a[2]) - 1); _save(WORLD_F, W); return True, "已删除"
            except Exception: return True, "序号不对"
        if op == "only" and len(a) >= 3:
            try:
                k = int(a[2]) - 1
                for i, w in enumerate(W): w["enabled"] = (i == k)
                _save(WORLD_F, W); return True, f"只启用 #{k+1} {W[k].get('name','')}"
            except Exception: return True, "序号不对"
        if op in ("on","off") and len(a) >= 3:
            try: W[int(a[2]) - 1]["enabled"] = (op == "on"); _save(WORLD_F, W); return True, f"已{op}"
            except Exception: return True, "序号不对"
        return True, "用法：/world add <关键词> <内容>｜del/on/off <序号>"
    return True, "未知指令，/help 看列表"

COMPACT_AT = int(os.environ.get("COMPACT_AT", "9000"))
GROUP_KEEP = 20

_locks = {}
_pending = {}
_busy = {}
_glock = threading.Lock()
REJECTS = []  # 最近被白名单拒掉的记录
GHIST = {}   # group_id -> [{nick, text}]

def _lock(uid):
    with _glock:
        return _locks.setdefault(uid, threading.Lock())

def allowed(ev):
    uid = ev.get("user_id")
    if CONF.get("auto_allow"):
        return True
    if uid in (CONF.get("whitelist") or []):
        return True
    if ev.get("message_type") == "group":
        gid = ev.get("group_id")
        if gid and (gid in (CONF.get("group_whitelist") or []) or gid in (CONF.get("group_whitelist") or [])):
            return True
        if CONF.get("allow_group") and gid:
            return True
    return False

def chunk(text, size=1400):
    out, rest = [], text
    while len(rest) > size:
        cut = rest.rfind("\n", 0, size)
        if cut < size * 0.5: cut = rest.rfind("。", 0, size)
        if cut < size * 0.5: cut = size
        out.append(rest[:cut]); rest = rest[cut:]
    if rest.strip(): out.append(rest)
    return out

def group_context(gid):
    h = GHIST.get(gid) or []
    if not h: return ""
    lines = [f"{x['nick']}：{x['text']}" for x in h[-GROUP_KEEP:]]
    return "【最近群聊】\n" + "\n".join(lines)

def build_system(uid, ev=None):
    s = get_sess(uid)
    if s.get("mode") == "work":
        parts = ["你是这台机器上的编码助手，中文回答，先动手再解释。可执行命令、联网、用 sudo（echo droidvm | sudo -S）。"]
    else:
        p = personas().get(s["persona"]) or {"prompt": ""}
        parts = [p.get("prompt", "")]
    if s.get("memory"):
        parts.append("【长期记忆·早期对话摘要】\n" + s["memory"])
    if ev and ev.get("message_type") == "group":
        g = group_context(ev.get("group_id"))
        if g: parts.append(g)
    if s.get("mode") != "work":
        for w in worldbook():
            if w.get("enabled", True) and w.get("keyword"):
                parts.append(f"【{w.get('name') or '设定'}】{w.get('text','')}")
    parts.append(CONF["system_suffix"])
    return "\n\n".join([x for x in parts if x])

def compact(uid):
    s = get_sess(uid)
    h = s["history"]
    if len(h) < 4: return "对话太少，不用压缩"
    msgs = [{"role": "system", "content": "把下面这段对话压缩成要点式记忆，保留人物、设定、约定、未完成的事，不要评论，200 字以内。"},
            {"role": "user", "content": "\n".join(f"{m['role']}: {m['content']}" for m in h[:-4])}]
    try:
        summary = llama_chat(msgs, max_tokens=400)
    except Exception as e:
        return f"压缩失败：{e}"
    s["memory"] = (s.get("memory", "") + "\n" + summary).strip()[-3000:]
    s["history"] = h[-4:]
    put_sess(uid, s)
    return f"已压缩，记忆 {len(s['memory'])} 字，保留最近 {len(s['history'])} 条"

_last_reply = {}

def is_mentioned(ev, text):
    raw = ev.get("raw_message") or ""
    if ev.get("to_me") or ev.get("at_me"):
        return True
    if "<@" in raw or "CQ:at" in raw:
        return True
    return ev.get("message_type") == "private"

def has_keyword(text):
    for k in (CONF.get("keywords") or []):
        if k and k in text:
            return True
    return False

def should_reply(ev, text):
    if ev.get("message_type") != "group":
        return True
    gid = ev.get("group_id")
    if not allowed(ev):
        return False
    direct = is_mentioned(ev, text) or has_keyword(text)
    mode = CONF.get("group_mode", "keyword")
    if mode == "mention" and not is_mentioned(ev, text):
        return False
    if mode == "keyword" and not direct:
        return False
    if direct:
        _last_reply[gid] = time.time()
        return True
    gap = float(CONF.get("reply_min_interval", 45))
    if time.time() - _last_reply.get(gid, 0) < gap:
        return False
    if random.random() > float(CONF.get("reply_probability", 0.5)):
        return False
    _last_reply[gid] = time.time()
    return True

def msg_has_tool_calls(msgs):
    return any(m.get("tool_calls") for m in msgs)

def process(ev):
    uid = ev.get("user_id")
    gid = ev.get("group_id")
    text = (ev.get("raw_message") or "").strip()
    if not text: return
    nick = (ev.get("sender") or {}).get("nickname") or str(uid)
    is_cmd = text.startswith("/")
    if gid and not is_cmd and not should_reply(ev, text):
        if gid:
            with _glock:
                GHIST.setdefault(gid, []).append({"nick": nick, "text": text[:200]})
                GHIST[gid] = GHIST[gid][-GROUP_KEEP:]
        return
    if gid:
        with _glock:
            GHIST.setdefault(gid, []).append({"nick": nick, "text": text[:200]})
            GHIST[gid] = GHIST[gid][-GROUP_KEEP:]

    handled, out = handle_cmd(uid, text)
    if handled:
        reply(ev, out); return

    s = get_sess(uid)
    mode = s.get("mode", "work")
    msgs = [{"role": "system", "content": build_system(uid, ev)}]
    msgs += trim(s["history"])
    msgs.append({"role": "user", "content": text})

    if CONF.get("ack"): reply(ev, "…")
    try:
        use_tools = CONF.get("tools", True)
        ans, seen, used = "", {}, 0
        t0 = time.time()
        for _round in range(8):
            if time.time() - t0 > 100:
                break                      # 总时长上限，避免一轮卡死整个会话
            try:
                m = llama_chat_msg(msgs, TOOLS_SPEC if use_tools else None)
            except urllib.error.URLError as e:
                reply(ev, f"[模型服务没响应] 检查 llama-server 是否在跑：{e.reason}"); return
            tcs = m.get("tool_calls") or []
            if tcs:
                msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
                dup = 0
                for tc in tcs:
                    fn = (tc.get("function") or {})
                    key = (fn.get("name"), str(fn.get("arguments")))
                    if key in seen:
                        out = "[重复调用，结果已在上文，不要重复执行，直接根据已有结果回答]"
                        dup += 1
                    else:
                        out = exec_tool(fn.get("name"), fn.get("arguments")); seen[key] = 1; used += 1
                    print(f"[tool] {fn.get('name')} -> {out[:120]!r}", flush=True)
                    msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": out[:6000]})
                if dup:
                    msgs.append({"role": "user", "content": "资料已经齐了，请直接给出最终答案，不要再调用工具。"})
                continue
            ans = (m.get("content") or "").strip()
            break
        if not ans and used:
            # 轮次用尽：关掉工具强制它总结已有结果
            msgs.append({"role": "user", "content": "不要再调用工具。根据上面已经拿到的结果，用中文直接回答用户的问题。"})
            try: ans = (llama_chat_msg(msgs, None).get("content") or "").strip()
            except Exception as e: ans = ""
        if not ans:
            ans = "（这轮没拿到结果，换个说法再问一次，比如把路径写全）"
        # 兼容旧写法：模型自己在正文里写 ```run``` 块
        if use_tools and not msg_has_tool_calls(msgs):
            for _ in range(2):
                code = extract_run(ans)
                if not code: break
                out = run_shell(code)
                msgs.append({"role": "assistant", "content": ans})
                msgs.append({"role": "user", "content": "【命令输出】\n" + out + "\n请据此继续，或用 ```run``` 再试一步。"})
                ans = llama_chat(msgs) or ans
    except Exception as e:
        print(f"[err] {type(e).__name__}: {e}", flush=True)
        reply(ev, f"[模型出错] {type(e).__name__}: {e}\n（/logs 看详情）"); return

    s["history"] = trim(s["history"] + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": ans},
    ])
    put_sess(uid, s)
    for part in chunk(ans): reply(ev, part)

    if sum(len(m["content"]) for m in s["history"]) > COMPACT_AT:
        print("[compact]", uid, compact(uid), flush=True)

def extract_run(text):
    m = re.search(r"```run\s*\n(.*?)```", text, re.S)
    return m.group(1).strip() if m else None

def run_shell(cmd, timeout=30, cwd=None):
    if not (cmd or "").strip(): return "[空命令]"
    if re.search(r"rm\s+-(rf|fr)\s+/(\s|$)", cmd) or "mkfs" in cmd:
        return "[拒绝] 危险命令"
    if re.search(r"\b(DISPLAY|WAYLAND_DISPLAY)\s*=", cmd):
        return "[拒绝] 不要设置 DISPLAY/WAYLAND_DISPLAY，这类命令会弹图形窗口。"
    if re.search(r"\b(xdg-open|gio\s+open|nautilus|dolphin|thunar|explorer|gnome-open|kde-open|code\s|gedit|mousepad)\b", cmd):
        return "[拒绝] 该命令会弹图形窗口，无人能点。请用 ls / cat / find 等命令行方式。"
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS")}
    try:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True,
                           timeout=timeout, cwd=cwd or HOME, env=env)
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if (r.stderr or "").strip() else "")
        out = out.strip()
        head = "" if r.returncode == 0 else f"[退出码 {r.returncode}]\n"
        return head + (out[:6000] or "(无输出)")
    except subprocess.TimeoutExpired:
        return f"[超时 {timeout}s，命令可能卡住了]"
    except Exception as e:
        return f"[执行失败] {e}"

def make_sticker(text, path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    W, H = 400, 400
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    font = None
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
        if os.path.exists(f):
            try:
                font = ImageFont.truetype(f, 46); break
            except Exception: pass
    if font is None:
        return None
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if d.textlength(cur, font=font) > W - 40:
            lines.append(cur[:-1]); cur = ch
    lines.append(cur)
    y = (H - len(lines) * 58) // 2
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text(((W - w) / 2, y), ln, font=font, fill=(20, 20, 20))
        y += 58
    d.rectangle([2, 2, W - 3, H - 3], outline=(20, 20, 20), width=4)
    img.save(path, "PNG")
    return path

def worker(uid, ev):
    process(ev)
    with _glock:
        rest = _pending.get(uid) or []
        if rest:
            nxt = rest.pop(0)
        else:
            _busy[uid] = False
            return
    worker(uid, nxt)

def enqueue(ev):
    uid = ev.get("user_id")
    with _glock:
        if _busy.get(uid):
            _pending.setdefault(uid, []).append(ev)
            print(f"[queue] {uid} 排队 {len(_pending[uid])}", flush=True)
            return
        _busy[uid] = True
    threading.Thread(target=worker, args=(uid, ev), daemon=True).start()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            ev = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self.send_response(400); self.end_headers(); return
        self.send_response(204); self.end_headers()
        if ev.get("post_type") != "message": return
        _txt = (ev.get("raw_message") or "").strip()
        _gid = ev.get("group_id")
        _uid = str(ev.get("user_id") or "")
        if _gid and _uid and _uid == str(CONF.get("owner") or ""):
            _wl = CONF.setdefault("group_whitelist", [])
            if str(_gid) not in _wl:
                _wl.append(str(_gid))
                CONF["allow_group"] = True
                _save(CFG, CONF)
                print("[auto-join]", _gid, flush=True)
        if _gid and _uid != str(CONF.get("owner") or "") and not _txt.startswith("/"):
            print("[skip] group non-owner:", _uid, flush=True); return
        if _txt.startswith("/"):
            enqueue(ev); return
        if not allowed(ev):
            import time as _t
            uid = ev.get("user_id")
            REJECTS.append({"t": _t.strftime("%H:%M:%S"), "uid": uid, "text": (ev.get("raw_message") or "")[:40]})
            del REJECTS[:-5]
            print("[skip] not allowed:", uid, flush=True); return
        enqueue(ev)


# ---------- 本地面板（扫码/状态/编辑） ----------
PANEL_PORT = int(os.environ.get("PANEL_PORT", "8091"))
QR_F = os.path.join(ROOT, "qqbot", "qr.txt")


BK_DIR = os.path.join(ROOT, "..", "var", "backups")
def backup(keep=10):
    import shutil, time
    os.makedirs(BK_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BK_DIR, ts)
    shutil.copytree(DATA, dst, dirs_exist_ok=True)
    subs = sorted(os.listdir(BK_DIR))
    for old in subs[:-keep]:
        shutil.rmtree(os.path.join(BK_DIR, old), ignore_errors=True)
    total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(dst) for f in fs)
    return f"已备份 {ts}（{total//1024} KB），共 {min(len(subs), keep)} 份"

def list_backups():
    if not os.path.isdir(BK_DIR): return "还没有备份"
    subs = sorted(os.listdir(BK_DIR))[-10:]
    return "备份：\n" + "\n".join("  " + x for x in subs)

def _qr_png():
    try:
        import io, qrcode
        url = open(QR_F).read().strip()
        img = qrcode.make(url)
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None

def bk_count():
    return len(os.listdir(BK_DIR)) if os.path.isdir(BK_DIR) else 0

def _esc(x):
    import html
    return html.escape(str(x))

def _panel_html(msg=""):
    P = personas(); W = worldbook()
    qr_status = "已有凭据" if os.path.exists(os.path.join(ROOT, "qqbot", "creds.json")) else "待扫码"
    wl = CONF.get("whitelist") or []
    n_sess = len(os.listdir(SESS_DIR)) if os.path.isdir(SESS_DIR) else 0
    ph = "".join(
        f'<form method=post action=/act class=row>'
        f'<input type=hidden name=act value=persona><input type=hidden name=name value="{_esc(k)}">'
        f'<div class=head><b>{_esc(k)}</b></div><textarea name=prompt rows=6>{_esc(v.get("prompt",""))}</textarea>'
        f'<button>保存</button></form>' for k, v in P.items())
    wh = "".join(
        f'<form method=post action=/act class=row>'
        f'<input type=hidden name=act value=world><input type=hidden name=i value="{i}">'
        f'<div class=head><input type=checkbox name=on id=w{i} {"checked" if w.get("enabled") else ""}>'
        f'<label for=w{i}><b>{_esc(w.get("name"))}</b> <code>{_esc(w.get("keyword"))}</code></label></div>'
        f'<textarea name=text rows=4>{_esc(w.get("text",""))}</textarea>'
        f'<button>保存</button></form>' for i, w in enumerate(W))
    return f"""<!doctype html><meta charset=utf-8><title>llama QQ 桥</title>
<style>*{{box-sizing:border-box}}body{{font-family:system-ui;background:#111;color:#eee;margin:0;padding:24px;max-width:980px;line-height:1.6}}
h2{{font-weight:600;margin-top:0}} .card{{background:#1b1b1b;border:1px solid #2a2a2a;border-radius:10px;padding:16px;margin-bottom:16px}}
textarea{{width:100%;background:#0d0d0d;color:#ddd;border:1px solid #333;border-radius:6px;padding:8px;font:13px/1.5 ui-monospace}}
button{{background:#2d6cdf;color:#fff;border:0;border-radius:6px;padding:6px 14px;margin-top:6px;cursor:pointer}}
img{{background:#fff;padding:8px;border-radius:8px}} code{{background:#222;padding:2px 6px;border-radius:4px}}
.row{{border-top:1px solid #262626;padding-top:12px;margin-top:12px}}
.head{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.btnrow{{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}}
form{{margin:0}} .ok{{color:#5fd67a}}</style>
<h2>llama QQ 桥</h2>
{"<div class='card ok'>"+_esc(msg)+"</div>" if msg else ""}
<div class=card>状态 <b>{qr_status}</b> ｜ 白名单 <code>{_esc(wl)}</code> ｜ 会话 {n_sess} ｜ 备份 {bk_count()}</div>
<div class=card>{'<img src="/qr.png" width=260>' if qr_status=='待扫码' else '已绑定，无需扫码。'}</div>
<div class=card><b>人设</b>（改完点保存，下一轮生效）{ph}
<form method=post action=/act class=row><input type=hidden name=act value=newpersona>
<input name=name placeholder="新人设名" style="background:#0d0d0d;color:#ddd;border:1px solid #333;border-radius:6px;padding:6px">
<textarea name=prompt rows=3 placeholder="人设正文"></textarea><button>新建人设</button></form></div>
<div class=card><b>世界观 / 世界书</b>{wh}</div>
<div class=card><b>维护</b><br>
<form method=post action=/act style="display:inline"><input type=hidden name=act value=backup><button>立即备份</button></form>
<form method=post action=/act style="display:inline"><input type=hidden name=act value=resetall><button>清空所有会话</button></form>
<form method=post action=/act style="display:inline"><input type=hidden name=act value=clearbak><button>清空备份</button></form>
<div style="margin-top:10px">{_esc(list_backups()).replace(chr(10), '<br>')}</div></div>
<div class=card><b>最近被拒消息</b><br>{"".join(f"<div class=row><code>{_esc(r['t'])}</code> <code>{_esc(r['uid'])}</code> {_esc(r['text'])}</div>" for r in reversed(REJECTS)) or "<div class=row>暂无</div>"}</div>"""

class P(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, ctype="text/html; charset=utf-8", code=200):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/qr.png":
            png = _qr_png()
            return self._send(png, "image/png") if png else self._send("no qr", code=404)
        self._send(_panel_html())

    def do_POST(self):
        from urllib.parse import parse_qs
        n = int(self.headers.get("Content-Length") or 0)
        d = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
        a = d.get("act")
        try:
            if a == "persona":
                Pp = personas(); Pp[d["name"]] = {"prompt": d.get("prompt", "")}; _save(PERSONA_F, Pp)
                msg = f"人设「{d['name']}」已保存"
            elif a == "newpersona" and d.get("name"):
                Pp = personas(); Pp[d["name"]] = {"prompt": d.get("prompt", "")}; _save(PERSONA_F, Pp)
                msg = f"已新建人设「{d['name']}」"
            elif a == "world":
                W = worldbook(); i = int(d["i"])
                W[i]["text"] = d.get("text", ""); W[i]["enabled"] = ("on" in d)
                _save(WORLD_F, W); msg = f"世界书 #{i+1} 已保存"
            elif a == "backup":
                msg = backup()
            elif a == "clearbak":
                import shutil
                if os.path.isdir(BK_DIR):
                    for x in os.listdir(BK_DIR): shutil.rmtree(os.path.join(BK_DIR, x), ignore_errors=True)
                msg = "备份已清空"
            elif a == "resetall":
                for f in os.listdir(SESS_DIR) if os.path.isdir(SESS_DIR) else []:
                    os.remove(os.path.join(SESS_DIR, f))
                msg = "所有会话已清空"
            else:
                msg = "未知操作"
        except Exception as e:
            msg = f"失败：{e}"
        self._send(_panel_html(msg))

def serve_panel():
    ThreadingHTTPServer(("127.0.0.1", PANEL_PORT), P).serve_forever()

if __name__ == "__main__":
    port = int(CONF["port"])
    print(f"QQ 桥已启动：0.0.0.0:{port}  →  llama {CONF['llama']}  白名单 {CONF.get('whitelist')}", flush=True)
    threading.Thread(target=serve_panel, daemon=True).start()
    print(f"面板：http://127.0.0.1:{PANEL_PORT}", flush=True)
    print(backup(), flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
