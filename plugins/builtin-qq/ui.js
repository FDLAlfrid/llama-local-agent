(() => {
  const btn = document.createElement('button'); btn.textContent = 'QQ';
  btn.style.cssText = 'all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44;color:#fff;font:12px system-ui';
  (document.querySelector('#cmdbar') || document.body).appendChild(btn);
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:14px;bottom:200px;z-index:99998;width:300px;background:rgba(22,22,26,.98);border:1px solid #333;border-radius:10px;padding:10px;display:none;font:12px/1.6 system-ui;color:#ddd';
  document.body.appendChild(box);
  const act = async (o) => { await fetch('/__ctx/bridge/act', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(o)}); draw(); };
  async function draw() {
    const b = await (await fetch('/__ctx/bridge')).json();
    box.innerHTML = `<div style="display:flex"><b>QQ 机器人</b><span style="flex:1"></span><span style="opacity:.5">内置</span></div>
      <div style="opacity:.85;margin-top:6px">${b.running?'<b style="color:#3a7">运行中</b>':'<b style="color:#d9534f">未运行</b>'} · 会话 ${b.sessions}
      ${b.auto_allow?'<br>⚠ 任何人可用':''}</div>
      <div style="margin-top:6px">白名单：${b.whitelist.map(x=>`<span style="background:#2a2a30;padding:1px 6px;border-radius:4px;margin:2px;display:inline-block">${x.slice(0,8)}… <a href="#" data-del="${x}" style="color:#d9534f;text-decoration:none">×</a></span>`).join('')||'（空）'}</div>
      <div style="display:flex;gap:6px;margin-top:8px">
        <input id="w" placeholder="openid" style="flex:1;background:#15151a;color:#ddd;border:1px solid #333;border-radius:6px;padding:3px 6px">
        <button id="add" style="all:unset;cursor:pointer;padding:3px 12px;border-radius:6px;background:#2d6cdf;color:#fff">确认添加</button></div>
      <div style="display:flex;gap:6px;margin-top:6px">
        <button id="sw" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:${b.running?'#d9534f':'#3a7'};color:#fff">${b.running?'停止':'启动'}</button>
        ${b.qr?'<button id="qr" style="all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44">二维码</button>':''}</div>`;
    const wi = box.querySelector('#w');
    const add = () => { const v = wi.value.trim(); if (v) act({act:'add', id:v}); };
    box.querySelector('#add').onclick = add;
    wi.onkeydown = (e) => { if (e.key === 'Enter') add(); };
    box.querySelectorAll('[data-del]').forEach(a => a.onclick = (e) => { e.preventDefault(); act({act:'del', id:a.dataset.del}); });
    box.querySelector('#sw').onclick = () => act({act: b.running ? 'stop' : 'start'});
    const q = box.querySelector('#qr');
    if (q) q.onclick = () => {
      const d = document.createElement('div'); d.style.cssText = 'margin-top:8px;text-align:center';
      d.innerHTML = `<img src="/__ctx/qr?t=${Date.now()}" style="width:210px;height:210px;background:#fff;padding:6px;border-radius:8px">`;
      box.appendChild(d);
    };
  }
  btn.onclick = () => { const on = box.style.display === 'block'; box.style.display = on ? 'none' : 'block'; if (!on) draw(); };
})();
