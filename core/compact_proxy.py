#!/usr/bin/env python3
"""上下文压缩代理：:8093 → llama-server。阈值=窗口80%，支持 /compact 手动压缩。"""
import gzip, io, json, os, sys, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "var", "ctxstore"); os.makedirs(STORE, exist_ok=True)
UP = os.environ.get("UPSTREAM", "http://127.0.0.1:8082").rstrip("/")
PORT = int(os.environ.get("PORT", "8093"))
KEEP = int(os.environ.get("KEEP_TURNS", "6"))
MODEL = os.environ.get("MODEL", "local")

def n_ctx():
    try:
        with urllib.request.urlopen(UP + "/props", timeout=5) as r:
            return int(json.load(r)["default_generation_settings"]["n_ctx"])
    except Exception:
        return 40960
LIMIT = int(n_ctx() * float(os.environ.get("LIMIT_RATIO", "0.8")))
STATE = {"est": 0, "limit": LIMIT, "last": None}
CWD_NOISE = ("当前工作目录已设置为", "当前工作目录已切换", "Current working directory")

def est(msgs):
    t = 0
    for m in msgs:
        c = m.get("content") or ""
        if isinstance(c, list): c = "".join(p.get("text","") for p in c if isinstance(p,dict))
        t += len(c)/2.2 + 4
    return int(t)

def post(path, obj):
    body = json.dumps(obj).encode()
    req = urllib.request.Request(UP+path, body, {"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)

def summarize(msgs):
    txt = []
    for m in msgs:
        c = m.get("content") or ""
        if isinstance(c, list): c = "".join(p.get("text","") for p in c if isinstance(p,dict))
        if m.get("role") in ("user","assistant") and c: txt.append(f"{m['role']}: {c[:800]}")
    prompt = ("把下面这段对话压缩成中文要点，必须保留：目标、结论、文件名与路径、"
              "具体数值、未完成的待办。不寒暄、不复述原文。\n\n" + "\n".join(txt)[:12000])
    out = post("/v1/chat/completions", {"model": MODEL, "max_tokens": 500,
               "temperature": 0.2, "messages":[{"role":"user","content":prompt}]})
    return out["choices"][0]["message"]["content"].strip()

def compress(msgs):
    keep = msgs[-KEEP:]
    head = msgs[:len(msgs)-len(keep)]
    s = summarize(head)
    fid = "%08x" % int(time.time())
    json.dump({"summary": s, "n": len(head), "at": time.strftime("%F %T")},
              open(os.path.join(STORE, fid+".json"), "w"), ensure_ascii=False)
    packed = f"⟦CTX:{fid}⟧ 前 {len(head)} 条消息的压缩摘要：\n\n{s}"
    return [{"role":"system","content":packed}] + keep, fid, len(head), len(s)

RP = os.path.join(ROOT, "bridge", "data")

def _du(p):
    tot = 0
    for r, _, fs in os.walk(p):
        for f in fs:
            try: tot += os.path.getsize(os.path.join(r, f))
            except OSError: pass
    return tot

def space_info():
    def mb(n): return round(n / 1048576, 1)
    v = os.path.join(ROOT, "var")
    logs = sum(os.path.getsize(os.path.join(v, f)) for f in os.listdir(v) if f.endswith(".log"))
    return {"root": mb(_du(ROOT)), "backups": mb(_du(os.path.join(v, "backups"))),
            "backupCount": len(os.listdir(os.path.join(v, "backups"))) if os.path.isdir(os.path.join(v, "backups")) else 0,
            "ctxstore": mb(_du(os.path.join(v, "ctxstore"))),
            "ctxCount": len([f for f in os.listdir(os.path.join(v, "ctxstore")) if f.endswith(".json")]) if os.path.isdir(os.path.join(v, "ctxstore")) else 0,
            "logs": mb(logs), "models": 4710}

def _port_alive(port):
    import socket
    with socket.socket() as sk:
        sk.settimeout(0.4)
        return sk.connect_ex(("127.0.0.1", port)) == 0

def bridge_info():
    cfg = _j("../config.json", {})
    sess = os.path.join(ROOT, "bridge", "data", "sessions")
    return {"running": _port_alive(8090), "panel": _port_alive(8091),
            "whitelist": cfg.get("whitelist", []), "auto_allow": cfg.get("auto_allow", False),
            "sessions": len(os.listdir(sess)) if os.path.isdir(sess) else 0,
            "model": cfg.get("model", ""), "qr": os.path.exists(os.path.join(ROOT, "bridge", "qqbot", "qr.txt"))}

def bridge_act(req):
    import subprocess, signal
    act = req.get("act")
    cfgp = os.path.join(ROOT, "bridge", "config.json")
    cfg = _j("../config.json", {})
    if act in ("add", "del"):
        uid = str(req.get("id", "")).strip()
        if not uid: return {"ok": False, "error": "id 为空"}
        wl = [str(x) for x in cfg.get("whitelist", [])]
        if act == "add" and uid not in wl: wl.append(uid)
        if act == "del": wl = [x for x in wl if x != uid]
        cfg["whitelist"] = wl
        json.dump(cfg, open(cfgp, "w"), ensure_ascii=False, indent=1)
        return {"ok": True, **bridge_info()}
    if act == "start":
        subprocess.Popen(["python3", "-u", os.path.join(ROOT, "bridge", "qq_bridge.py")],
                         cwd=os.path.join(ROOT, "bridge"), stdout=open(os.path.join(ROOT, "var", "bridge.log"), "a"),
                         stderr=subprocess.STDOUT, start_new_session=True)
        time.sleep(2); return {"ok": True, **bridge_info()}
    if act == "stop":
        out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if ":8090" in line and "pid=" in line:
                pid = int(line.split("pid=")[1].split(",")[0])
                try: os.kill(pid, signal.SIGTERM)
                except OSError: pass
        time.sleep(1); return {"ok": True, **bridge_info()}
    return {"ok": False, "error": "未知动作"}

def server_info():
    import glob, subprocess
    pid = None
    try:
        out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if ":8082" in line and "pid=" in line:
                pid = int(line.split("pid=")[1].split(",")[0]); break
    except Exception:
        pass
    d = {"port": 8082, "up": False, "model": "", "uptime": "", "rss": 0, "n_ctx": LIMIT // 0.8}
    if pid:
        d["up"] = True
        try:
            with open(f"/proc/{pid}/stat") as f: btime = float(f.read().split()[21])
            with open("/proc/stat") as f: bt = [l for l in f if l.startswith("btime")][0].split()[1]
            up = int(time.time()) - (int(bt) + btime / 100)
            d["uptime"] = f"{up//3600}h{(up%3600)//60}m"
        except Exception: pass
        try:
            with open(f"/proc/{pid}/status") as f:
                for l in f:
                    if l.startswith("VmRSS"): d["rss"] = int(l.split()[1]) // 1024
        except Exception: pass
        try:
            with open(f"/proc/{pid}/cmdline") as f:
                args = f.read().split("\0")
            if "-m" in args: d["model"] = os.path.basename(args[args.index("-m")+1])
        except Exception: pass
    return d

def tail_logs(n=160):
    parts = []
    for name in ("server.log", "proxy.log", "bridge.log"):
        fp = os.path.join(ROOT, "var", name)
        if not os.path.exists(fp): continue
        try:
            with open(fp, "rb") as f:
                f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 20000))
                txt = f.read().decode("utf-8", "replace")
            parts.append(f"===== {name} =====\n" + "\n".join(txt.splitlines()[-n // 3:]))
        except Exception as e:
            parts.append(f"===== {name} ===== (读取失败 {e})")
    return "\n".join(parts)

def do_clean(what=None):
    what = what or ["logs", "backups", "ctx"]
    v = os.path.join(ROOT, "var")
    before = _du(v)
    for f in (os.listdir(v) if "logs" in what else []):
        if f.endswith(".log"):
            fp = os.path.join(v, f)
            if os.path.getsize(fp) > 1048576:
                with open(fp, "r+b") as fh: fh.truncate(1048576)
    b = os.path.join(v, "backups")
    if os.path.isdir(b) and "backups" in what:
        for d in sorted(os.listdir(b))[3:] if False else sorted(os.listdir(b), reverse=True)[3:]:
            import shutil; shutil.rmtree(os.path.join(b, d), ignore_errors=True)
    c = os.path.join(v, "ctxstore")
    if os.path.isdir(c) and "ctx" in what:
        for f in sorted(os.listdir(c), reverse=True)[20:]:
            try: os.remove(os.path.join(c, f))
            except OSError: pass
    return {"freedMB": round((before - _du(v)) / 1048576, 1), **space_info()}

def _j(name, default):
    try:
        return json.load(open(os.path.join(RP, name), encoding="utf-8"))
    except Exception:
        return default

def load_rp():
    wb = _j("worldbook.json", {})
    if isinstance(wb, list):
        wb = {e.get("name") or e.get("keyword") or f"条目{i}": e for i, e in enumerate(wb, 1)}
    return {"personas": _j("personas.json", {}), "worldbook": wb,
            "config": _j("../config.json", {})}

def save_rp(req):
    kind = req.get("kind")
    if kind == "persona":
        d = _j("personas.json", {})
        n = req.get("name", "").strip()
        if not n:
            return {"ok": False, "error": "名字不能为空"}
        d[n] = {"prompt": req.get("text", "")}
        json.dump(d, open(os.path.join(RP, "personas.json"), "w"), ensure_ascii=False, indent=1)
        return {"ok": True, "personas": d}
    if kind == "world":
        d = _j("worldbook.json", [])
        if isinstance(d, dict):
            d = [dict(name=k, **v) for k, v in d.items()]
        n = req.get("name", "").strip()
        if not n:
            return {"ok": False, "error": "名字不能为空"}
        for e in d:
            if e.get("name") == n:
                e["text"] = req.get("text", e.get("text", ""))
                if "enabled" in req: e["enabled"] = bool(req["enabled"])
                break
        else:
            d.append({"name": n, "keyword": n, "enabled": True, "text": req.get("text", "")})
        json.dump(d, open(os.path.join(RP, "worldbook.json"), "w"), ensure_ascii=False, indent=1)
        return {"ok": True, "worldbook": d}
    return {"ok": False, "error": "未知类型"}

def ensure_up():
    """上游不可达时尝试拉起一次（守护），失败则静默返回 False"""
    try:
        urllib.request.urlopen(UP + "/health", timeout=2)
        return True
    except Exception:
        pass
    try:
        import subprocess
        subprocess.Popen(["bash", os.path.join(ROOT, "core", "server.sh"), "start"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(30):
            time.sleep(2)
            try:
                urllib.request.urlopen(UP + "/health", timeout=2); return True
            except Exception:
                continue
    except Exception:
        pass
    return False

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _out(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path.startswith("/__ctx/qr"):
            try:
                import qrcode
                url = open(os.path.join(ROOT, "bridge", "qqbot", "qr.txt")).read().strip()
                img = qrcode.make(url); buf = io.BytesIO(); img.save(buf, format="PNG")
                return self._out(200, buf.getvalue(), "image/png")
            except Exception as e:
                return self._out(500, f"二维码生成失败: {e}\nqr.txt 内容缺失或 qrcode 未安装".encode(), "text/plain; charset=utf-8")
        if self.path == "/__ctx/logs/clear":
            n = 0
            for f in os.listdir(os.path.join(ROOT, "var")):
                if f.endswith(".log"):
                    open(os.path.join(ROOT, "var", f), "w").close(); n += 1
            return self._out(200, json.dumps({"ok": True, "cleared": n}))
        if self.path == "/__ctx/bridge":
            return self._out(200, json.dumps(bridge_info(), ensure_ascii=False))
        if self.path == "/__ctx/info":
            return self._out(200, json.dumps(server_info(), ensure_ascii=False))
        if self.path.startswith("/__ctx/logs"):
            return self._out(200, json.dumps({"text": tail_logs()}, ensure_ascii=False))
        if self.path == "/__ctx/space":
            return self._out(200, json.dumps(space_info(), ensure_ascii=False))
        if self.path == "/__ctx/data":
            return self._out(200, json.dumps(load_rp(), ensure_ascii=False))
        if self.path == "/__ctx/status":
            return self._out(200, json.dumps(STATE))
        if self.path == "/__ctx/cmdbar.js":
            js = open(os.path.join(ROOT, "core", "cmdbar.js"), "rb").read()
            return self._out(200, js, "application/javascript")
        ensure_up()
        try:
            rq = urllib.request.Request(UP+self.path, headers={"Accept-Encoding":"gzip"})
            with urllib.request.urlopen(rq, timeout=60) as r:
                data = r.read(); ct = r.headers.get("Content-Type","application/octet-stream")
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
            if "text/html" in ct and b"</body>" in data:
                data = data.replace(b"</body>", b'<script src="/__ctx/cmdbar.js"></script></body>', 1)
            self._out(200, data, ct)
        except Exception as e:
            self._out(502, json.dumps({"error":str(e)}))
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n)
        if self.path == "/__ctx/bridge/act":
            return self._out(200, json.dumps(bridge_act(json.loads(raw)), ensure_ascii=False))
        if self.path == "/__ctx/clean":
            return self._out(200, json.dumps(do_clean(json.loads(raw) if raw else None), ensure_ascii=False))
        if self.path == "/__ctx/save":
            return self._out(200, json.dumps(save_rp(json.loads(raw)), ensure_ascii=False))
        if not self.path.startswith("/v1/chat/completions"):
            return self._proxy_raw(raw)
        req = json.loads(raw); msgs = req.get("messages", [])
        # 过滤"工作目录已设置"这类噪音消息，避免反复污染上下文
        msgs = [m for m in msgs if not any(k in str(m.get("content") or "") for k in CWD_NOISE)]
        last = next((m for m in reversed(msgs) if m.get("role")=="user"), {})
        txt = last.get("content") or ""
        if isinstance(txt, list): txt = "".join(p.get("text","") for p in txt if isinstance(p,dict))
        if txt.strip() in ("/compact", "/压缩"):
            msgs2, fid, ncov, slen = compress(msgs)
            msg = (f"已压缩：前 {ncov} 条 → {slen} 字摘要，保留最近 {KEEP} 条。标记 ⟦CTX:{fid}⟧\n\n{slen and ''}")
            return self._out(200, json.dumps({"object":"chat.completion","model":MODEL,
                "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":msg}}]}))
        before = est(msgs); STATE["est"] = before
        auto = before > LIMIT and len(msgs) > KEEP+2
        if auto:
            msgs, fid, ncov, slen = compress(msgs)
            STATE["last"] = {"id": fid, "n": ncov, "len": slen, "at": time.strftime("%F %T")}
            STATE["est"] = est(msgs)
        req["messages"] = msgs
        return self._proxy_raw(json.dumps(req).encode(),
                               {"X-Ctx-Auto": "1"} if auto else None)
    def _proxy_raw(self, raw, extra=None):
        try:
            rq = urllib.request.Request(UP+self.path, raw, {"Content-Type":"application/json"})
            with urllib.request.urlopen(rq, timeout=900) as r:
                data = r.read(); code = r.status
        except urllib.error.HTTPError as e:
            data = e.read(); code = e.code
        except Exception as e:
            return self._out(502, json.dumps({"error":str(e)}))
        self._out(code, data, "application/json", extra)

if __name__ == "__main__":
    print(f"compact-proxy :{PORT} → {UP}  limit={LIMIT} ({LIMIT*100//n_ctx()}% of {n_ctx()}) keep={KEEP}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
