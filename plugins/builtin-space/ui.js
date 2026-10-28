// 内置插件：空间管理
(() => {
  const btn = document.createElement('button');
  btn.textContent = '空间';
  btn.style.cssText = 'all:unset;cursor:pointer;padding:2px 8px;border-radius:6px;background:#3a3a44;color:#fff;font:12px system-ui';
  const bar = document.querySelector('#cmdbar') || document.body;
  bar.appendChild(btn);
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:14px;bottom:200px;z-index:99998;width:280px;background:rgba(22,22,26,.98);border:1px solid #333;border-radius:10px;padding:10px;display:none;font:12px/1.7 system-ui;color:#ddd';
  document.body.appendChild(box);
  const mb = n => `${n} MB`;
  async function draw() {
    const d = await (await fetch('/__ctx/space')).json();
    box.innerHTML = `<b>空间</b> <span style="opacity:.5">内置</span>
      <div style="opacity:.85;margin-top:6px">
      总占用 ${mb(d.root)} · 模型 ${mb(d.models)}<br>
      备份 ${mb(d.backups)}（${d.backupCount} 份）<br>
      摘要 ${mb(d.ctxstore)}（${d.ctxCount} 个）· 日志 ${mb(d.logs)}</div>
      <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
        <button data-w="logs" class="pb">清日志</button>
        <button data-w="backups" class="pb">备份留3</button>
        <button data-w="ctx" class="pb">摘要留20</button>
        <button data-w="all" class="pb" style="background:#d9534f">全部</button>
      </div><span id="m" style="opacity:.6"></span>`;
    box.querySelectorAll('.pb').forEach(b => {
      b.style.cssText = 'all:unset;cursor:pointer;padding:3px 10px;border-radius:6px;background:#3a3a44;color:#fff';
      b.onclick = async () => {
        const what = b.dataset.w === 'all' ? ['logs','backups','ctx'] : [b.dataset.w];
        const r = await (await fetch('/__ctx/clean', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(what)})).json();
        box.querySelector('#m').textContent = ` 释放 ${r.freedMB} MB`;
        setTimeout(draw, 600);
      };
    });
  }
  btn.onclick = () => { const on = box.style.display === 'block'; box.style.display = on ? 'none' : 'block'; if (!on) draw(); };
})();
