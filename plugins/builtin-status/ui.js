(() => {
  const mk = (t) => { const b = document.createElement('button'); b.textContent = t;
    b.style.cssText = 'all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44;color:#fff;font:12px system-ui'; return b; };
  const btn = mk('状态'); (document.querySelector('#cmdbar') || document.body).appendChild(btn);
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:14px;bottom:200px;z-index:99998;width:300px;background:rgba(22,22,26,.98);border:1px solid #333;border-radius:10px;padding:10px;display:none;font:12px/1.7 system-ui;color:#ddd';
  document.body.appendChild(box);
  let tab = 'info';
  const tabBtn = (k, t) => `<button data-t="${k}" style="all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:${tab===k?'#2d6cdf':'#333'}">${t}</button>`;
  async function draw() {
    const i = await (await fetch('/__ctx/info')).json();
    let body = '';
    if (tab === 'info') {
      body = `<div style="opacity:.85">服务 ${i.up?'<b style="color:#3a7">运行中</b>':'<b style="color:#d9534f">未运行</b>'}<br>
        模型 ${i.model || '—'}<br>端口 ${i.port} · 运行 ${i.uptime || '—'}<br>内存 ${i.rss} MB · 上下文 ${(i.n_ctx/1000).toFixed(0)}k</div>`;
    } else {
      body = `<pre id="lg" style="max-height:230px;overflow:auto;background:#111;color:#bbb;padding:6px;border-radius:6px;font:11px/1.5 ui-monospace;white-space:pre-wrap">加载中…</pre>
        <div style="display:flex;gap:6px;margin-top:6px"><button id="rf" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44">刷新</button>
        <button id="lc" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#d9534f">清空</button></div>`;
    }
    box.innerHTML = `<div style="display:flex;gap:6px;margin-bottom:8px">${tabBtn('info','状态')}${tabBtn('logs','日志')}<span style="flex:1"></span><span style="opacity:.5">内置</span></div>${body}`;
    box.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { tab = b.dataset.t; draw(); });
    if (tab === 'logs') {
      const load = async () => { const d = await (await fetch('/__ctx/logs')).json(); box.querySelector('#lg').textContent = d.text || '(空)'; };
      box.querySelector('#rf').onclick = load;
      box.querySelector('#lc').onclick = async () => { await fetch('/__ctx/logs/clear'); load(); };
      load();
    }
  }
  btn.onclick = () => { const on = box.style.display === 'block'; box.style.display = on ? 'none' : 'block'; if (!on) draw(); };
})();
