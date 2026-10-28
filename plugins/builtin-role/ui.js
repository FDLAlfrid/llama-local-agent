(() => {
  const btn = document.createElement('button'); btn.textContent = '角色';
  btn.style.cssText = 'all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44;color:#fff;font:12px system-ui';
  (document.querySelector('#cmdbar') || document.body).appendChild(btn);
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:14px;bottom:200px;z-index:99998;width:320px;background:rgba(22,22,26,.98);border:1px solid #333;border-radius:10px;padding:10px;display:none;font:12px/1.6 system-ui;color:#ddd';
  document.body.appendChild(box);
  let DATA = null, kind = 'persona', sel = null;
  async function load() { DATA = await (await fetch('/__ctx/data')).json(); }
  function draw() {
    const raw = kind === 'persona' ? DATA.personas : DATA.worldbook;
    const list = Array.isArray(raw) ? Object.fromEntries(raw.map(e => [e.name, e])) : (raw || {});
    const names = Object.keys(list);
    sel = sel && list[sel] ? sel : (kind === 'persona' ? ((DATA.config && DATA.config.default_persona) || names[0]) : names[0]);
    const text = sel ? (list[sel].prompt || list[sel].text || list[sel].content || '') : '';
    box.innerHTML = `<div style="display:flex;gap:6px;margin-bottom:8px">
        <button data-k="persona" style="all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:${kind==='persona'?'#2d6cdf':'#333'}">人设 ${Object.keys(DATA.personas).length}</button>
        <button data-k="world" style="all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:${kind==='world'?'#2d6cdf':'#333'}">世界书 ${names.length}</button>
        <span style="flex:1"></span><span style="opacity:.5">内置</span></div>
      <select id="pick" style="width:100%;background:#15151a;color:#ddd;border:1px solid #333;border-radius:6px;padding:3px">
        ${names.map(n => `<option ${n===sel?'selected':''}>${n}</option>`).join('')}</select>
      <textarea id="txt" style="width:100%;height:180px;margin-top:6px;background:#15151a;color:#ddd;border:1px solid #333;border-radius:6px;padding:6px;font:12px/1.6 ui-monospace">${text}</textarea>
      <div style="display:flex;gap:6px;margin-top:6px">
        <button id="sv" style="all:unset;cursor:pointer;padding:3px 12px;border-radius:6px;background:#2d6cdf;color:#fff">保存</button>
        <button id="nv" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44">新建</button>
        <span id="m" style="opacity:.6"></span></div>`;
    box.querySelectorAll('[data-k]').forEach(b => b.onclick = () => { kind = b.dataset.k; sel = null; draw(); });
    box.querySelector('#pick').onchange = (e) => { sel = e.target.value; draw(); };
    box.querySelector('#sv').onclick = async () => {
      const r = await (await fetch('/__ctx/save', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ kind, name: sel, text: box.querySelector('#txt').value })})).json();
      box.querySelector('#m').textContent = r.ok ? ' 已保存' : ` ${r.error || '失败'}`;
      await load();
    };
    box.querySelector('#nv').onclick = async () => {
      const n = prompt('新名字'); if (!n) return;
      sel = n; await fetch('/__ctx/save', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ kind, name: n, text: '' })}); await load(); draw();
    };
  }
  btn.onclick = async () => {
    const on = box.style.display === 'block'; box.style.display = on ? 'none' : 'block';
    if (!on) { await load(); draw(); }
  };
})();
