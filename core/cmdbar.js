(() => {
  if (window.__ctxBar) return; window.__ctxBar = 1;
  const CMDS = [
    ['/compact', '压缩早期对话，保留最近 6 轮'],
    ['/ctx', '查看当前上下文占用'],
  ];
  let STATUS = { est: 0, limit: 1 };
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:14px;bottom:76px;z-index:99999;font:12px/1.6 system-ui;display:flex;gap:8px;align-items:center;padding:6px 10px;border-radius:8px;background:rgba(20,20,24,.92);color:#ddd;box-shadow:0 2px 12px rgba(0,0,0,.4)';
  const label = document.createElement('span');
  const btn = document.createElement('button');
  btn.textContent = '压缩';
  btn.style.cssText = 'all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#2d6cdf;color:#fff';
  box.append(label, btn); document.body.appendChild(box);

  const pop = document.createElement('div');
  pop.style.cssText = 'position:fixed;right:14px;bottom:120px;z-index:99999;min-width:260px;background:rgba(24,24,28,.97);border:1px solid #333;border-radius:8px;padding:6px;display:none;font:12px/1.7 system-ui;color:#ccc';
  document.body.appendChild(pop);

  function ta() { return document.querySelector('textarea') || document.querySelector('[contenteditable="true"]'); }
  function setText(el, v) {
    if (el.tagName === 'TEXTAREA') {
      const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      set.call(el, v);
    } else { el.textContent = v; }
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function send() {
    const b = [...document.querySelectorAll('button')].find(x =>
      /send|提交|发送/i.test(x.getAttribute('aria-label') || x.title || '') || x.type === 'submit');
    if (b) b.click(); else {
      const e = ta(); if (!e) return;
      e.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    }
  }
  function run(cmd) { const e = ta(); if (!e) return; setText(e, cmd); setTimeout(send, 60); }

  async function tick() {
    try {
      const r = await fetch('/__ctx/status'); const d = await r.json();
      STATUS = d;
      const pct = d.limit ? Math.round(d.est * 100 / d.limit) : 0;
      label.textContent = `上下文 ${(d.est / 1000).toFixed(1)}k / ${(d.limit / 1000).toFixed(0)}k · ${pct}%`;
      box.style.borderTop = '2px solid ' + (pct > 80 ? '#d9534f' : pct > 60 ? '#e0a800' : '#3a7');
      if (d.last && d.last.id) label.title = '上次压缩 ' + d.last.at + '：' + d.last.n + ' 条 → 摘要';
    } catch (e) {}
  }
  btn.onclick = () => run('/compact');

  document.addEventListener('input', (ev) => {
    const el = ev.target; if (!el || el.tagName !== 'TEXTAREA') return;
    const v = el.value;
    if (!v.startsWith('/') || v.includes(' ') || v.includes('\n')) { pop.style.display = 'none'; return; }
    const hits = CMDS.filter(c => c[0].startsWith(v));
    if (!hits.length) { pop.style.display = 'none'; return; }
    pop.innerHTML = '';
    hits.forEach(([c, d]) => {
      const row = document.createElement('div');
      row.style.cssText = 'padding:4px 8px;border-radius:6px;cursor:pointer';
      row.onmouseenter = () => row.style.background = '#2a2a30';
      row.onmouseleave = () => row.style.background = 'transparent';
      row.innerHTML = `<b style="color:#8ab4f8">${c}</b><span style="opacity:.6"> — ${d}</span>`;
      row.onmousedown = (e) => { e.preventDefault(); setText(el, c); pop.style.display = 'none'; };
      pop.appendChild(row);
    });
    pop.style.display = 'block';
  }, true);

  setInterval(tick, 5000); tick();

  // ---- 角色 / 世界书 面板 ----
  const rpBtn = document.createElement('button');
  rpBtn.textContent = '角色';
  rpBtn.style.cssText = 'all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44;color:#fff';
  rpBtn.style.display='none'; /* 已迁移为 builtin-role 插件 */
  const dr = document.createElement('div');
  dr.style.cssText = 'position:fixed;right:14px;bottom:120px;z-index:99999;width:420px;max-height:70vh;overflow:auto;background:rgba(22,22,26,.98);border:1px solid #333;border-radius:10px;padding:10px;display:none;font:12px/1.6 system-ui;color:#ddd';
  document.body.appendChild(dr);
  let DATA = null;
  async function loadRP(force) {
    if (DATA && !force) return DATA;
    DATA = await (await fetch('/__ctx/data')).json();
    return DATA;
  }
  function render(kind) {
    let sel = null;
    const raw = kind === 'persona' ? DATA.personas : DATA.worldbook;
    const list = Array.isArray(raw) ? Object.fromEntries(raw.map(e => [e.name, e])) : (raw || {});
    const names = Object.keys(list);
    dr.innerHTML = `<div style="display:flex;gap:6px;margin-bottom:8px">
      <button data-k="persona" style="all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:${kind==='persona'?'#2d6cdf':'#333'}">人设 ${Object.keys(DATA.personas).length}</button>
      <button data-k="world" style="all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:${kind==='world'?'#2d6cdf':'#333'}">世界书 ${Object.keys(DATA.worldbook).length}</button>
      <button data-new="1" style="all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44">+ 新建</button>
      <span style="flex:1"></span><button data-close="1" style="all:unset;cursor:pointer;opacity:.6">关闭</button></div>
      <div id="rpList">${names.map(n=>`<div data-n="${n}" style="padding:3px 6px;border-radius:6px;cursor:pointer;${n===(sel||'')?'background:#2a2a30':''}">${n}</div>`).join('')||'<div style="opacity:.5">空</div>'}</div>
      <textarea id="rpText" style="width:100%;height:200px;margin-top:8px;background:#15151a;color:#ddd;border:1px solid #333;border-radius:6px;padding:6px;font:12px/1.6 ui-monospace"></textarea>
      <div style="display:flex;gap:6px;margin-top:6px"><button id="rpSave" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#2d6cdf">保存</button><span id="rpMsg" style="opacity:.7"></span></div>`;
    sel = kind === 'persona' ? ((DATA.config && DATA.config.default_persona) || names[0]) : names[0];
    const ta2 = dr.querySelector('#rpText');
    const fill = (n) => { sel = n; ta2.value = kind === 'persona' ? (list[n]?.prompt || '') : (list[n]?.text || list[n]?.content || ''); };
    if (sel) fill(sel);
    dr.querySelectorAll('[data-n]').forEach(el => el.onclick = () => { fill(el.dataset.n); dr.querySelectorAll('[data-n]').forEach(x=>x.style.background=''); el.style.background='#2a2a30'; });
    dr.querySelectorAll('[data-k]').forEach(el => el.onclick = () => render(el.dataset.k));
    dr.querySelector('[data-close]').onclick = () => dr.style.display = 'none';
    dr.querySelector('[data-new]').onclick = () => { const n = prompt('新名字'); if (n) { list[n] = kind==='persona'?{prompt:''}:{content:'',enabled:true}; fill(n); } };
    dr.querySelector('#rpSave').onclick = async () => {
      const r = await fetch('/__ctx/save', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ kind, name: sel, text: ta2.value }) });
      const j = await r.json();
      dr.querySelector('#rpMsg').textContent = j.ok ? '已保存' : ('失败：' + j.error);
      DATA = null;
    };
  }
  const mgBtn = document.createElement('button');
  mgBtn.textContent = '管理';
  mgBtn.style.cssText = 'all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44;color:#fff';
  mgBtn.style.display='none'; /* 已迁移为 builtin-status/space/qq 插件 */
  const mp = document.createElement('div');
  mp.style.cssText = 'position:fixed;right:14px;bottom:160px;z-index:99999;width:300px;background:rgba(22,22,26,.98);border:1px solid #333;border-radius:10px;padding:10px;display:none;font:12px/1.7 system-ui;color:#ddd';
  document.body.appendChild(mp);
  let TAB = 'status';
  async function drawMg() {
    const sp = await (await fetch('/__ctx/space')).json();
    const info = await (await fetch('/__ctx/info')).json();
    const tabBtn = (k, label) => `<button data-tab="${k}" style="all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:${TAB===k?'#2d6cdf':'#333'}">${label}</button>`;
    let body = '';
    if (TAB === 'space') {
      body = `<div style="opacity:.85">总占用 ${sp.root} MB · 模型 ${sp.models} MB<br>
        备份 ${sp.backups} MB（${sp.backupCount} 份）· 摘要 ${sp.ctxstore} MB（${sp.ctxCount} 个）<br>日志 ${sp.logs} MB</div>
        <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
          <button data-clean="logs" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44">清日志 ${sp.logs}M</button>
          <button data-clean="backups" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44">备份留3份 ${sp.backups}M</button>
          <button data-clean="ctx" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44">摘要留20 ${sp.ctxstore}M</button>
          <button data-clean="all" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#d9534f;color:#fff">全部清理</button>
          <span id="msg" style="opacity:.7"></span></div>`;
    } else if (TAB === 'bridge') {
      const b = await (await fetch('/__ctx/bridge')).json();
      body = `<div style="opacity:.85">桥 ${b.running ? '<b style="color:#3a7">运行中</b>' : '<b style="color:#d9534f">未运行</b>'} · 面板 ${b.panel ? '开' : '关'}<br>
        已绑定 ${b.whitelist.length} 个 ID · 会话 ${b.sessions} 个<br>
        ${b.auto_allow ? '⚠ 任何人可用（auto_allow）' : '仅白名单可用'}</div>
        <div style="margin-top:6px">白名单：${b.whitelist.map(x => `<span style="display:inline-block;background:#2a2a30;padding:1px 6px;border-radius:4px;margin:2px">${x} <a href="#" data-del="${x}" style="color:#d9534f;text-decoration:none">×</a></span>`).join('') || '（空）'}</div>
        <div style="display:flex;gap:6px;margin-top:8px">
          <input id="wid" placeholder="openid" style="flex:1;background:#15151a;color:#ddd;border:1px solid #333;border-radius:6px;padding:3px 6px">
          <button id="wadd" style="all:unset;cursor:pointer;padding:3px 12px;border-radius:6px;background:#2d6cdf;color:#fff;font-weight:600">确认添加</button>
        </div>
        <div style="display:flex;gap:6px;margin-top:6px">
          <button data-act="${b.running ? 'stop' : 'start'}" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:${b.running ? '#d9534f' : '#3a7'}">${b.running ? '停止桥' : '启动桥'}</button>
          ${b.qr ? '<button id="qrbtn" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44">显示二维码</button>' : ''}
          <span id="bmsg" style="opacity:.7"></span>
        </div>`;
    } else if (TAB === 'status') {
      body = `<div style="opacity:.85">
        服务 ${info.up ? '<b style="color:#3a7">运行中</b>' : '<b style="color:#d9534f">未运行</b>'}<br>
        模型 ${info.model || '—'}<br>端口 ${info.port} · 已运行 ${info.uptime || '—'}<br>
        内存 ${info.rss} MB · 上下文 ${(info.n_ctx/1000).toFixed(0)}k</div>`;
    } else {
      body = `<pre id="lg" style="max-height:240px;overflow:auto;background:#111;color:#bbb;padding:6px;border-radius:6px;font:11px/1.5 ui-monospace;white-space:pre-wrap">加载中…</pre>
        <div style="display:flex;gap:6px;margin-top:6px"><button id="rf" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44">刷新</button><button id="lc" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#d9534f;color:#fff">清空日志</button></div>`;
    }
    mp.innerHTML = `<div style="display:flex;gap:6px;margin-bottom:8px">${tabBtn('status','状态')}${tabBtn('bridge','QQ')}${tabBtn('logs','日志')}<span style="flex:1"></span><button data-close="1" style="all:unset;cursor:pointer;opacity:.6">关闭</button></div>${body}`;
    mp.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { TAB = b.dataset.tab; drawMg(); });
    mp.querySelector('[data-close]').onclick = () => { mp.style.display = 'none'; };
    if (TAB === 'space') mp.querySelectorAll('[data-clean]').forEach(b => b.onclick = async () => {
      const what = b.dataset.clean === 'all' ? ['logs','backups','ctx'] : [b.dataset.clean];
      const r = await (await fetch('/__ctx/clean', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(what) })).json();
      mp.querySelector('[data-clean="all"]').parentElement.querySelector('#msg').textContent = `释放 ${r.freedMB} MB`;
      setTimeout(drawMg, 700);
    });
    if (TAB === 'bridge') {
      const send = async (o) => { await fetch('/__ctx/bridge/act', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(o) }); drawMg(); };
      mp.querySelectorAll('[data-act]').forEach(b => b.onclick = () => send({ act: b.dataset.act, id: (mp.querySelector('#wid')||{}).value }));
      mp.querySelectorAll('[data-del]').forEach(a => a.onclick = (e) => { e.preventDefault(); send({ act:'del', id: a.dataset.del }); });
      const wi = mp.querySelector('#wid');
      const addIt = () => { const v = (wi.value||'').trim(); if (!v) { wi.focus(); return; } send({ act:'add', id: v }); };
      mp.querySelector('#wadd').onclick = addIt;
      const qb = mp.querySelector('#qrbtn');
      if (qb) qb.onclick = () => {
        const d = document.createElement('div');
        d.style.cssText = 'margin-top:8px;text-align:center';
        d.innerHTML = `<img src="/__ctx/qr?t=${Date.now()}" style="width:220px;height:220px;background:#fff;padding:6px;border-radius:8px"><div style="opacity:.6;margin-top:4px">用 QQ 扫码绑定机器人</div>`;
        mp.appendChild(d);
      };
      wi.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); addIt(); } };
    }
    if (TAB === 'logs') {
      const load = async () => { const d = await (await fetch('/__ctx/logs')).json(); mp.querySelector('#lg').textContent = d.text || '(空)'; };
      mp.querySelector('#rf').onclick = load;
      mp.querySelector('#lc').onclick = async () => { await fetch('/__ctx/logs/clear'); load(); };
      load();
    }
  }
  mgBtn.onclick = () => { if (mp.style.display === 'block') { mp.style.display='none'; return; } mp.style.display='block'; drawMg(); };
  rpBtn.onclick = async () => {
    if (dr.style.display === 'block') { dr.style.display = 'none'; return; }
    await loadRP(true); dr.style.display = 'block'; render('persona');
  };
})();
