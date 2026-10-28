#!/usr/bin/env python3
"""llama-server 上下文压缩代理。
- 端口 8095，转发到 llama-server(8082)，静态页也转发
- 自动：估算 prompt > AUTO_AT 时，把早期对话压成摘要
- 手动：最后一条用户消息为 /compact 时执行同样压缩
- 持久：摘要存 var/ctxstore/<id>.json，用标记 ⟦CTX:<id>⟧ 在历史里定位
"""
import json, os, re, sys, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "var", "ctxstore")
UP = os.environ.get("UPSTREAM", "http://127.0.0.1:8082").rstrip("/")
PORT = int(os.environ.get("PORT", "8095"))
AUTO_AT = int(os.environ.get("AUTO_AT", "24000"))   # 估算 token
KEEP_TURNS = int(os.environ.get("KEEP_TURNS", "6"))
MODEL = os.environ.get("MODEL", "local")
MARK = re.compile(r"⟦CTX:([0-9a-f]{8})⟧")
LOCK = threading.Lock()
os.makedirs(STORE, exist_ok=True)

def est_tokens(msgs):
    n = 0
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
        n += len(c or "") / 2.2 + 4
    return int(n)

def upstream(path, body=None, method=None, headers=None, raw=False):
    req = urllib.request.Request(UP + path, data=body,
                                 headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=900) as r:
        return r.status, dict(r.headers), (r.read() if raw else r.read())

def summarize(msgs):
    txt = []
    for m in msgs:
        role = m.get("role", "?")
        c = m.get("content") or ""
        if isinstance(c, list):
            c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
        if role in ("user", "assistant") and c:
            txt.append(f"{role}: {c[:800]}")
    convo = "\n".join(txt)[:12000]
    prompt = ("把下面这段对话压缩成中文要点摘要，保留：用户目标、已确认的事实与数值、"
              "已做的改动与文件路径、未完成的待办。不要寒暄，不要复述原文。\n\n" + convo)
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 500, "temperature": 0.2, "stream": False}).encode()
    try:
        _, _, data = upstream("/v1/chat/completions", body, "POST",
                              {"Content-Type": "application/json"})
        return json.loads(data)["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"（压缩失败：{e}）"

def compress(msgs):
    keep = msgs[-KEEP_TURNS:] if len(msgs) > KEEP_TURNS else []
    head = msgs[:len(msgs) - len(keep)]
    summary = summarize(head)
    key = os.urandom(4).hex()
    with open(os.path.join(STORE, key + ".json"), "w") as f:
        json.dump({"summary": summary, "covered": len(head), "at": __import__("time").strftime("%F %T")}, f)
    packed = (f"⟦CTX:{key}⟧ 以下是本次对话到目前的压缩摘要（覆盖前 {len(head)} 条消息）：\n\n{summary}")
    out = list(keep)
    out.insert(0, {"role": "system", "content": packed})
    return out, key, len(head), len(summary)

def expand(msgs):
    """历史里已有标记 → 只保留标记那条 + 之后的消息"""
    for i, m in enumerate(msgs):
        mt = MARK.search(json.dumps(m, ensure_ascii=False))
        if mt:
            key = mt.group(1)
            p = os.path.join(STORE, key + ".json")
            if os.path.exists(p):
                return msgs[i:], key
    return msgs, None

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            code, hdrs, body = upstream(self.path, None, "GET", {}, raw=True)
        except Exception as e:
            return self._send(502, json.dumps({"error": str(e)}).encode())
        self.send_response(code)
        for k, v in hdrs.items():
            if k.lower() in ("content-type", "content-encoding", "cache-control"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if not self.path.startswith("/v1/chat/completions"):
            try:
                code, hdrs, body = upstream(self.path, raw, "POST",
                                            {"Content-Type": "application/json"})
            except Exception as e:
                return self._send(502, json.dumps({"error": str(e)}).encode())
            return self._send(code, body)
        try:
            req = json.loads(raw)
        except Exception:
            return self._send(400, b'{"error":"bad json"}')
        msgs = req.get("messages", [])
        msgs, _ = expand(msgs)
        last = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
        txt = (last or {}).get("content") or ""
        if isinstance(txt, list):
            txt = "".join(p.get("text", "") for p in txt if isinstance(p, dict))
        manual = txt.strip() in ("/compact", "/压缩")

        if manual and len(msgs) > 2:
            packed, key, covered, ssum = compress(msgs)
            msg = (f"已完成压缩：前 {covered} 条消息压成 {ssum} 字摘要，保留最近 {KEEP_TURNS} 条。\n"
                   f"标记 ⟦CTX:{key}⟧ 已写入上下文，后续请求会自动展开。\n\n【摘要】\n{ssum}")
            return self._send(200, json.dumps({"id": key, "object": "chat.completion",
                "model": MODEL, "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": msg}}]}).encode())

        auto = est_tokens(msgs) > AUTO_AT and len(msgs) > KEEP_TURNS + 2
        if auto:
            msgs, key, covered, _ = compress(msgs)
        req["messages"] = msgs
        body = json.dumps(req).encode()
        try:
            code, hdrs, data = upstream("/v1/chat/completions", body, "POST",
                                        {"Content-Type": "application/json"})
        except urllib.error.HTTPError as e:
            return self._send(e.code, e.read())
        except Exception as e:
            return self._send(502, json.dumps({"error": str(e)}).encode())
        if req.get("stream"):
            self.send_response(code)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            if auto:
                self.send_header("X-Ctx-Compressed", f"1;covered={covered}")
            self.end_headers()
            for line in data.splitlines(keepends=True):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line))
            self.wfile.write(b"0\r\n\r\n")
            return
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if auto:
            self.send_header("X-Ctx-Compressed", f"1;covered={covered}")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

if __name__ == "__main__":
    print(f"ctx-proxy on :{PORT} → {UP} (auto@{AUTO_AT} tokens, keep {KEEP_TURNS})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
