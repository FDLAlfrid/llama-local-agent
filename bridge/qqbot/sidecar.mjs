// QQ 官方机器人 → 本桥（OneBot 兼容适配层）
// 1) 首次运行：扫码 → 自动拿到 appId/appSecret，存 creds.json
// 2) 之后：连官方网关，把消息转成 OneBot 事件投给 qq_bridge.py(:8090)
// 3) 暴露 :3000 的 /send_private_msg /send_group_msg，给 qq_bridge.py 回消息
import { createServer } from 'node:http';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { startQrConnect } from '@tencent-connect/qqbot-connector';
import { QQBot } from '@tencent-connect/qqbot-nodejs';

const CREDS = new URL('./creds.json', import.meta.url);
const BRIDGE = process.env.BRIDGE_URL || 'http://127.0.0.1:8090/';
const SIDE_PORT = Number(process.env.SIDE_PORT || 3000);

const targets = new Map(); // openid -> replyTarget

// 借鉴 dsh-im 的 normalizeQqMentions：把 <@!123> 这类 @ 标记去掉
function cleanMentions(text) {
  return String(text || '').replace(/<@!?\d+>/g, '').replace(/\s+/g, ' ').trim();
}

// 借鉴它的 markdown 分片：优先在换行/句号处切，避免把代码块劈开
function chunk(text, size = 1400) {
  const out = [];
  let rest = text;
  while (rest.length > size) {
    let cut = rest.lastIndexOf('\n', size);
    if (cut < size * 0.5) cut = rest.lastIndexOf('。', size);
    if (cut < size * 0.5) cut = size;
    out.push(rest.slice(0, cut));
    rest = rest.slice(cut);
  }
  if (rest.trim()) out.push(rest);
  return out;
}

async function credentials() {
  if (existsSync(CREDS)) return JSON.parse(readFileSync(CREDS, 'utf8'));
  console.log('没有凭据，开始扫码授权…');
  const c = await new Promise((resolve, reject) => {
    startQrConnect({
      displayQrCodeToConsole: true,
      source: 'llama-bridge',
      onSuccess: (list) => resolve(list[0]),
      onFailure: reject,
      onQrDisplayed: (url) => { console.log('二维码：' + url); writeFileSync(new URL('./qr.txt', import.meta.url), url); },
    });
  });
  writeFileSync(CREDS, JSON.stringify(c, null, 2));
  console.log('已保存 creds.json，appId=' + c.appId);
  return c;
}

const { appId, appSecret } = await credentials();

const bot = new QQBot({ appId, appSecret, logger: console });

bot.on('message', async (ctx, msg) => {
  const rt = msg.replyTarget;
  const userId = msg.senderId || rt.targetId;
  const id = rt.scope === 'c2c' ? userId : rt.targetId;
  targets.set(String(rt.scope === 'c2c' ? userId : id), rt);
  const ev = {
    post_type: 'message',
    message_type: rt.scope === 'c2c' ? 'private' : 'group',
    user_id: userId,
    group_id: rt.scope === 'c2c' ? undefined : id,
    raw_message: cleanMentions(msg.content),
    sender: { nickname: msg.author?.username || '' },
  };
  console.log(`[in] ${rt.scope} ${id}: ${ev.raw_message.slice(0, 40)}`);
  try {
    await fetch(BRIDGE, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ev),
    });
  } catch (e) { console.error('投递失败', e.message); }
});

createServer(async (req, res) => {
  let body = '';
  for await (const c of req) body += c;
  let out = { status: 'ok', retcode: 0 };
  try {
    const d = body ? JSON.parse(body) : {};
    const key = String(d.group_id || d.user_id);
    const rt = targets.get(key);
    if (!rt) { out = { status: 'failed', retcode: 100, msg: `未知会话 ${key}（先让它发一条消息）` }; }
    else {
      const text = String(d.message ?? '');
      for (const part of chunk(text)) await bot.sendText(rt, part);
    }
  } catch (e) { out = { status: 'failed', retcode: 500, msg: e.message }; }
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(out));
}).on('error', (e) => {
  if (e.code === 'EADDRINUSE') {
    console.error(`\n[端口冲突] ${SIDE_PORT} 已被占用。`);
    console.error(`  解决：杀掉占用进程，或换端口：SIDE_PORT=3001 node sidecar.mjs`);
    console.error(`  换端口后记得把 bridge/config.json 的 onebot_api 改成 http://127.0.0.1:3001\n`);
    process.exit(1);
  }
  throw e;
}).listen(SIDE_PORT, '127.0.0.1', () => console.log(`OneBot 兼容接口：http://127.0.0.1:${SIDE_PORT}`));

await bot.start();
