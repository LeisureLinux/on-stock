/**
 * stock.freelamp.com 付费墙 Worker
 *
 * 职责：
 *   1. 公开区（/、/trial/、/subscribe/、静态资源、/jd_root.txt）直接放行
 *   2. 付费区（/latest/、/news/YYYYMMDD/）要求登录（Cookie 或 Basic Auth）
 *   3. 订阅系统 API（/api/*）：
 *      - POST /api/verify-email   邮箱验证（Turnstile + 发验证码）
 *      - POST /api/verify-code    校验验证码 → 给管理员发"确认收款"邮件
 *      - GET  /api/confirm-pay    管理员点邮件链接 → 发号 → 给用户发账密
 *      - POST /api/login          网页登录表单 → Set-Cookie
 *   4. 账号存 Cloudflare KV（USERS）
 *
 * KV 记录格式（key = 邮箱/用户名）：
 *   {"salt","hash","expire","plan","status","code","code_expire",
 *    "pay_token","pay_expire","created","note"}
 *   status: pending(邮箱待验证) | verified(已验证待付款) | active(已发号)
 *
 * 需要的 Worker 变量 / Secrets：
 *   ORIGIN_HOST     源站域名
 *   SESSION_SECRET  免登录 Cookie 签名密钥
 *   USERS           KV namespace 绑定
 *   RESEND_API_KEY  Resend 发信 key（secret: put）
 *   RESEND_FROM     发信地址（subscribe@freelamp.com）
 *   ADMIN_EMAIL     管理员收款确认收件（albertxu@freelamp.com）
 *   TURNSTILE_SECRET Turnstile 服务端校验 key
 *   SITE_URL        站点主域
 */

const enc = new TextEncoder();

const PUBLIC_PREFIXES = [
  '/trial', '/subscribe', '/assets', '/static',
  '/favicon.ico', '/robots.txt', '/sitemap.xml', '/jd_root.txt',
];

const COOKIE_MAX_AGE = 7 * 24 * 3600;
const CANONICAL_HOST = 'stock.freelamp.com';
const ADMIN_EMAIL = 'albertxu@freelamp.com';
const SITE_URL = 'https://stock.freelamp.com';
const TURNSTILE_VERIFY = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';

const PLAN_DAYS = { '1m': 30, '3m': 90, '6m': 180, '1y': 365 };
const PLAN_PRICE = { '1m': '10 元', '3m': '28 元', '6m': '48 元', '1y': '88 元' };

// ---------------------------------------------------------------- 工具

async function sha256hex(s) {
  const d = await crypto.subtle.digest('SHA-256', enc.encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(msg));
  return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, '0')).join('');
}
function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}
function isPublic(pathname) {
  if (pathname === '/') return true;
  return PUBLIC_PREFIXES.some(p => pathname === p || pathname.startsWith(p + '/'));
}
function todayCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
}
function daysLeft(expire) {
  if (!expire) return -1;
  const a = Date.parse(`${todayCST()}T00:00:00Z`);
  const b = Date.parse(`${expire}T00:00:00Z`);
  if (Number.isNaN(b)) return -1;
  return Math.round((b - a) / 86400000);
}
function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...extra },
  });
}
function randToken(n = 24) {
  const a = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789';
  let s = '';
  for (let i = 0; i < n; i++) s += a[Math.floor(Math.random() * a.length)];
  return s;
}
function genPassword(n = 12) {
  const a = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789!@#$%';
  let s = '';
  for (let i = 0; i < n; i++) s += a[Math.floor(Math.random() * a.length)];
  return s;
}

// ---------------------------------------------------------------- 邮件 / Turnstile

async function sendEmail(env, to, subject, html) {
  const key = env.RESEND_API_KEY;
  if (!key) return { ok: false, err: 'RESEND_API_KEY 未配置' };
  const from = env.RESEND_FROM || 'subscribe@freelamp.com';
  const body = JSON.stringify({ from, to, subject, html });
  try {
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${key}`, 'Content-Type': 'application/json' },
      body,
    });
    const t = await r.text();
    if (r.status >= 200 && r.status < 300) return { ok: true, raw: t };
    return { ok: false, err: `Resend ${r.status}: ${t}` };
  } catch (e) {
    return { ok: false, err: String(e) };
  }
}

async function verifyTurnstile(env, token, ip) {
  if (!token) return false;
  try {
    const r = await fetch(TURNSTILE_VERIFY, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `secret=${encodeURIComponent(env.TURNSTILE_SECRET || '')}&response=${encodeURIComponent(token)}` +
        (ip ? `&remoteip=${encodeURIComponent(ip)}` : ''),
    });
    const d = await r.json();
    return !!d.success;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- 订阅 API

async function apiVerifyEmail(req, env) {
  const { email, plan, turnstile } = await req.json().catch(() => ({}));
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json({ ok: false, msg: '邮箱格式不正确' }, 400);
  if (!PLAN_DAYS[plan]) return json({ ok: false, msg: '请选择套餐' }, 400);
  const ok = await verifyTurnstile(env, turnstile, req.headers.get('CF-Connecting-IP'));
  if (!ok) return json({ ok: false, msg: '人机验证失败，请重试' }, 400);

  const code = String(Math.floor(100000 + Math.random() * 900000));
  const rec = await env.USERS.get(email, { type: 'json' }) || {};
  rec.email = email;
  rec.plan = plan;
  rec.status = 'pending';
  rec.code = code;
  rec.code_expire = Date.now() + 10 * 60 * 1000; // 10 分钟
  rec.created = rec.created || todayCST();
  await env.USERS.put(email, JSON.stringify(rec));

  const html = `<p>您的订阅验证码是：<b style="font-size:20px">${code}</b></p>
    <p>10 分钟内有效。若非本人操作请忽略。</p>`;
  const r = await sendEmail(env, email, '订阅验证码 - 外媒速览', html);
  if (!r.ok) return json({ ok: false, msg: '验证码邮件发送失败：' + r.err }, 500);
  return json({ ok: true, msg: '验证码已发送至 ' + email });
}

async function apiVerifyCode(req, env) {
  const { email, code } = await req.json().catch(() => ({}));
  if (!email || !code) return json({ ok: false, msg: '缺少邮箱或验证码' }, 400);
  const rec = await env.USERS.get(email, { type: 'json' });
  if (!rec || rec.status !== 'pending') return json({ ok: false, msg: '请先获取验证码' }, 400);
  if (!rec.code || Date.now() > (rec.code_expire || 0)) return json({ ok: false, msg: '验证码已过期，请重新获取' }, 400);
  if (rec.code !== code) return json({ ok: false, msg: '验证码错误' }, 400);

  rec.status = 'verified';
  rec.code = ''; rec.code_expire = 0;
  // 生成付款确认 token（给管理员点的链接）
  const payToken = randToken(28);
  rec.pay_token = payToken;
  rec.pay_expire = Date.now() + 7 * 24 * 3600 * 1000; // 7 天有效
  await env.USERS.put(email, JSON.stringify(rec));

  const planLabel = PLAN_PRICE[rec.plan] || rec.plan;
  const confirmUrl = `${SITE_URL}/api/confirm-pay?token=${payToken}&user=${encodeURIComponent(email)}`;
  const adminHtml = `<p><b>${email}</b> 已通过邮箱验证，申请订阅：<b>${planLabel}</b>（${rec.plan}）。</p>
    <p>请确认收款后点击下方按钮发放账号：</p>
    <p><a href="${confirmUrl}" style="display:inline-block;background:#DC2626;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none">确认收款并发号</a></p>
    <p style="color:#888;font-size:12px">该链接 7 天内有效。默认按用户所选套餐时长发放；如需调整，请先修改再点击。</p>`;
  const r = await sendEmail(env, ADMIN_EMAIL, `订阅确认：${email} - ${planLabel}`, adminHtml);
  if (!r.ok) return json({ ok: false, msg: '已验证，但通知管理员邮件失败：' + r.err }, 500);

  return json({ ok: true, msg: '邮箱验证成功。请完成付款，管理员确认后将自动发送账号。' });
}

async function apiConfirmPay(req, env) {
  const url = new URL(req.url);
  const token = url.searchParams.get('token');
  const user = url.searchParams.get('user');
  if (!token || !user) return new Response('缺少参数', { status: 400 });
  const rec = await env.USERS.get(user, { type: 'json' });
  if (!rec || rec.status !== 'verified') return new Response('该申请不存在或状态异常', { status: 400 });
  if (rec.pay_token !== token || Date.now() > (rec.pay_expire || 0)) return new Response('确认链接无效或已过期', { status: 400 });

  // 发放账号：用户名=邮箱，随机密码
  const password = genPassword(12);
  const salt = randToken(8);
  const hash = await sha256hex(`${salt}:${password}`);
  const days = PLAN_DAYS[rec.plan] || 30;
  const expire = new Date(Date.now() + days * 86400000 + 8 * 3600 * 1000).toISOString().slice(0, 10);
  rec.salt = salt; rec.hash = hash; rec.expire = expire;
  rec.status = 'active';
  rec.pay_token = ''; rec.pay_expire = 0;
  rec.note = rec.note || `自动发号(${rec.plan})`;
  await env.USERS.put(user, JSON.stringify(rec));

  const planLabel = PLAN_PRICE[rec.plan] || rec.plan;
  const userHtml = `<p>订阅已开通 ✅</p>
    <p>站点：${SITE_URL}<br>用户名：<b>${user}</b><br>密码：<b>${password}</b><br>有效期至：${expire}（${days} 天，${planLabel}）</p>
    <p>登录后在弹窗或登录页填入上述用户名和密码。登录状态记忆 7 天。</p>`;
  const r = await sendEmail(env, user, '订阅已开通 - 外媒速览账号', userHtml);
  if (!r.ok) return new Response('账号已发放，但用户邮件发送失败：' + r.err, { status: 500 });

  return new Response(`<html><body style="font-family:sans-serif;text-align:center;padding:60px">
    <h2>✅ 账号已发放</h2><p>${user} 的订阅账号（${planLabel}）已发送至此邮箱。</p>
    <p><a href="/subscribe/">返回订阅页</a></p></body></html>`,
    { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}

async function apiLogin(req, env) {
  const { user, pass } = await req.json().catch(() => ({}));
  if (!user || !pass) return json({ ok: false, msg: '缺少用户名或密码' }, 400);
  const rec = await env.USERS.get(user, { type: 'json' });
  if (!rec || rec.status !== 'active') return json({ ok: false, msg: '账号不存在或未激活' }, 401);
  if (Date.now() > (rec.code_expire || 0)) { /* noop */ }
  const left = daysLeft(rec.expire);
  if (left < 0) return json({ ok: false, msg: '账号已过期' }, 401);
  const h = await sha256hex(`${rec.salt}:${pass}`);
  if (!safeEqual(h, rec.hash || '')) return json({ ok: false, msg: '密码错误' }, 401);
  const sig = await hmac(env.SESSION_SECRET || 'x', `${user}:${rec.expire}`);
  const cookie = `sub_token=${user}.${sig}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Lax`;
  return json({ ok: true, msg: '登录成功', expire: rec.expire }, 200, { 'Set-Cookie': cookie });
}

// ---------------------------------------------------------------- 鉴权

function parseBasic(header) {
  if (!header.startsWith('Basic ')) return null;
  let raw;
  try { raw = atob(header.slice(6)); } catch { return null; }
  const i = raw.indexOf(':');
  if (i < 0) return null;
  return { user: raw.slice(0, i), pass: raw.slice(i + 1) };
}
function cookieValue(req, name) {
  for (const part of (req.headers.get('Cookie') || '').split(';')) {
    const [k, ...rest] = part.trim().split('=');
    if (k === name) return rest.join('=');
  }
  return null;
}
function unauthorized() {
  const body = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="3; url=/subscribe/">
<title>需要订阅账号</title>
<style>
body{font-family:-apple-system,'PingFang SC',sans-serif;background:#F9FAFB;color:#374151;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}
.card{background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:36px 32px;max-width:420px;text-align:center}
h1{font-size:20px;margin:0 0 10px;color:#111827}
p{font-size:14px;line-height:1.7;margin:0 0 20px;color:#6B7280}
a{display:inline-block;background:#DC2626;color:#fff;text-decoration:none;padding:10px 22px;border-radius:8px;font-size:14px}
</style></head><body><div class="card">
<h1>需要订阅账号</h1>
<p>该内容为付费订阅专属。订阅后可查看完整外媒标题速览、中文翻译与摘要。</p>
<a href="/subscribe/">查看订阅方案</a>
<p style="margin-top:16px;font-size:12px;color:#9CA3AF">3 秒后自动跳转…</p>
</div></body></html>`;
  return new Response(body, {
    status: 401,
    headers: { 'Content-Type': 'text/html; charset=utf-8',
      'WWW-Authenticate': `Basic realm="${CANONICAL_HOST}", charset="UTF-8"`, 'Cache-Control': 'no-store' },
  });
}
function expiredHTML(left) {
  const body = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>订阅已到期</title>
<style>
body{font-family:-apple-system,'PingFang SC',sans-serif;background:#F9FAFB;color:#374151;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}
.card{background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:36px 32px;max-width:420px;text-align:center}
h1{font-size:20px;margin:0 0 10px;color:#111827}
p{font-size:14px;line-height:1.7;margin:0 0 20px;color:#6B7280}
a{display:inline-block;background:#DC2626;color:#fff;text-decoration:none;padding:10px 22px;border-radius:8px;font-size:14px}
</style></head><body><div class="card">
<h1>${left < 0 ? '订阅已到期' : '订阅即将到期'}</h1>
<p>${left < 0 ? `你的账号已于 ${-left} 天前到期。` : `你的账号将在 ${left} 天后到期。`}<br>续费后即可继续访问完整内容。</p>
<a href="/subscribe/">查看订阅方案</a>
</div></body></html>`;
  return new Response(body, { status: 402, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } });
}

async function proxy(url, req, env, isPublicAsset) {
  const up = new URL(url);
  up.hostname = env.ORIGIN_HOST;
  up.protocol = 'https:';
  up.port = '';
  if (up.pathname.endsWith('/')) up.pathname += 'index.html';
  const out = await fetch(new Request(up, {
    method: req.method, headers: req.headers,
    body: ['GET', 'HEAD'].includes(req.method) ? undefined : req.body, redirect: 'follow',
  }));
  const res = new Response(out.body, out);
  res.headers.set('Cache-Control', isPublicAsset ? 'public, max-age=300' : 'private, max-age=300');
  if (!isPublicAsset) res.headers.set('X-Robots-Tag', 'noindex, nofollow');
  return res;
}

// ---------------------------------------------------------------- 主入口

export default {
  async fetch(req, env) {
    if (!env.ORIGIN_HOST) return new Response('Worker 未配置 ORIGIN_HOST', { status: 500 });
    const url = new URL(req.url);

    // 订阅系统 API
    if (url.pathname.startsWith('/api/')) {
      if (url.pathname === '/api/verify-email' && req.method === 'POST') return apiVerifyEmail(req, env);
      if (url.pathname === '/api/verify-code' && req.method === 'POST') return apiVerifyCode(req, env);
      if (url.pathname === '/api/confirm-pay' && req.method === 'GET') return apiConfirmPay(req, env);
      if (url.pathname === '/api/login' && req.method === 'POST') return apiLogin(req, env);
      return json({ ok: false, msg: '未知接口' }, 404);
    }

    // 公开区直接放行
    if (isPublic(url.pathname)) return proxy(url, req, env, true);

    if (!env.USERS) return new Response('Worker 未绑定 KV namespace: USERS', { status: 500 });

    let user = null;
    const ck = cookieValue(req, 'sub_token');
    if (ck) {
      const dot = ck.indexOf('.');
      if (dot > 0) {
        const u = ck.slice(0, dot); const sig = ck.slice(dot + 1);
        const rec = await env.USERS.get(u, { type: 'json' });
        if (rec) {
          const want = await hmac(env.SESSION_SECRET || 'x', `${u}:${rec.expire}`);
          if (safeEqual(sig, want)) user = { name: u, rec };
        }
      }
    }
    if (!user) {
      const cred = parseBasic(req.headers.get('Authorization') || '');
      if (!cred) return unauthorized();
      const rec = await env.USERS.get(cred.user, { type: 'json' });
      if (!rec) return unauthorized();
      const h = await sha256hex(`${rec.salt}:${cred.pass}`);
      if (!safeEqual(h, rec.hash || '')) return unauthorized();
      user = { name: cred.user, rec };
    }
    const left = daysLeft(user.rec.expire);
    if (left < 0) return expiredHTML(left);

    const res = await proxy(url, req, env, false);
    res.headers.set('X-Sub-Expire', user.rec.expire || '');
    res.headers.set('X-Sub-Days-Left', String(left));
    if (env.SESSION_SECRET) {
      const sig = await hmac(env.SESSION_SECRET, `${user.name}:${user.rec.expire}`);
      res.headers.append('Set-Cookie',
        `sub_token=${user.name}.${sig}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Lax`);
    }
    return res;
  },
};
