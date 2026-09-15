/**
 * stock.freelamp.com 付费墙 Worker
 *
 * 职责：
 *   1. 公开区（/、/trial/、/subscribe/、静态资源、/jd_root.txt）直接放行
 *   2. 付费区（/latest/、/news/YYYYMMDD/）要求登录（Cookie 或 Basic Auth）
 *   3. 订阅系统 API（/api/*）：
 *      - POST /api/verify-email   邮箱验证（Turnstile + 发验证码）
 *      - POST /api/verify-code    校验验证码 → 给管理员发"确认收款"邮件
 *      - GET  /api/confirm-pay    确认页（两步，无副作用，防邮件预取误触发）
 *      - POST /api/confirm-pay    真正发号（可覆盖套餐时长）
 *      - POST /api/login          网页登录表单（Turnstile）→ Set-Cookie
 *   4. /subadmin 隐藏管理页：查看订阅信息（分页 10/页），仅 admin 可见
 *   5. 账号存 Cloudflare KV（USERS）
 *
 * KV 记录格式（key = 用户名/邮箱）：
 *   {"salt","hash","expire","plan","status","code","code_expire",
 *    "pay_token","pay_expire","created","note","role"}
 *   status: pending(邮箱待验证) | verified(已验证待付款) | active(已发号)
 *   role:   "admin" 可访问 /subadmin
 *
 * 需要的 Worker 变量 / Secrets：
 *   ORIGIN_HOST      源站域名
 *   SESSION_SECRET   免登录 Cookie 签名密钥（secret）
 *   USERS            KV namespace 绑定
 *   RESEND_API_KEY   Resend 发信 key（secret）
 *   RESEND_FROM      发信地址（subscribe@freelamp.com）
 *   ADMIN_EMAIL      管理员邮箱（albertxu@freelamp.com）
 *   ADMIN_USER       管理员登录用户名（albertxu，KV 里的既有账号）
 *   TURNSTILE_SECRET Turnstile 服务端校验 key（secret）
 *   TURNSTILE_SITE_KEY Turnstile 前端 site key
 *   SITE_URL         站点主域
 */

const enc = new TextEncoder();

const PUBLIC_PREFIXES = [
  '/trial', '/subscribe', '/assets', '/static',
  '/favicon.ico', '/robots.txt', '/sitemap.xml', '/jd_root.txt',
];

const COOKIE_MAX_AGE = 7 * 24 * 3600;
const CANONICAL_HOST = 'stock.freelamp.com';
const TURNSTILE_VERIFY = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';

const PLAN_DAYS = { '1m': 30, '3m': 90, '6m': 180, '1y': 365 };
const PLAN_LABEL = {
  '1m': '1 个月（10 元 / 30 天）',
  '3m': '3 个月（28 元 / 90 天）',
  '6m': '6 个月（48 元 / 180 天）',
  '1y': '1 年（88 元 / 365 天）',
};
const SUB_PER_PAGE = 10;

function adminEmail(env) { return env.ADMIN_EMAIL || 'albertxu@freelamp.com'; }
function adminUser(env) { return env.ADMIN_USER || 'albertxu'; }
function siteUrl(env) { return env.SITE_URL || 'https://stock.freelamp.com'; }
function isAdmin(name, rec, env) {
  if (!name) return false;
  if (name === adminEmail(env) || name === adminUser(env)) return true;
  return !!(rec && rec.role === 'admin');
}

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
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
function htmlRes(body, status = 200, extra = {}) {
  return new Response(body, {
    status, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', ...extra },
  });
}
/** 随机串（crypto 级） */
function randStr(n, alphabet) {
  const buf = new Uint32Array(n);
  crypto.getRandomValues(buf);
  let s = '';
  for (let i = 0; i < n; i++) s += alphabet[buf[i] % alphabet.length];
  return s;
}
function randToken(n = 28) {
  return randStr(n, 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789');
}
function genPassword(n = 12) {
  return randStr(n, 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789');
}

// ---------------------------------------------------------------- 操作日志（KV `_log`）

const LOG_KEY = '_log';
const LOG_MAX = 1000;   // 上限，防无限增长
const LOG_SHOW = 50;    // /subadmin 页展示最近 N 条

/** 当前北京时间 YYYY-MM-DD HH:MM:SS */
function nowCSTStr() {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 19).replace('T', ' ');
}

/** 邮箱打码：albertxu@freelamp.com -> al***@freelamp.com（无@则取前两位） */
function maskEmail(s) {
  s = String(s || '');
  const i = s.indexOf('@');
  if (i < 0) return s.slice(0, 2) + '***';
  const local = s.slice(0, i);
  return local.slice(0, Math.min(2, local.length)) + '***' + s.slice(i);
}

/** 记录一条操作日志。失败不影响主流程。敏感数据（密码/完整邮箱）永不入日志。 */
async function logEvent(env, src, ev, user, detail) {
  try {
    const entry = { t: nowCSTStr(), src, ev, user: maskEmail(user), detail: detail || '' };
    const log = (await env.USERS.get(LOG_KEY, { type: 'json' })) || [];
    log.unshift(entry);
    if (log.length > LOG_MAX) log.length = LOG_MAX;
    await env.USERS.put(LOG_KEY, JSON.stringify(log));
  } catch { /* 忽略 */ }
}

// ---------------------------------------------------------------- 邮件 / Turnstile

async function sendEmail(env, to, subject, html) {
  const key = env.RESEND_API_KEY;
  if (!key) return { ok: false, err: 'RESEND_API_KEY 未配置' };
  const from = env.RESEND_FROM || 'subscribe@freelamp.com';
  try {
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from, to, subject, html }),
    });
    const t = await r.text();
    if (r.status >= 200 && r.status < 300) return { ok: true, raw: t };
    return { ok: false, err: `Resend ${r.status}: ${t}` };
  } catch (e) {
    return { ok: false, err: String(e) };
  }
}

async function verifyTurnstile(env, token, ip) {
  if (!env.TURNSTILE_SECRET) return true;  // 未配置则跳过（本地/降级）
  if (!token) return false;
  try {
    const r = await fetch(TURNSTILE_VERIFY, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `secret=${encodeURIComponent(env.TURNSTILE_SECRET)}&response=${encodeURIComponent(token)}` +
        (ip ? `&remoteip=${encodeURIComponent(ip)}` : ''),
    });
    const d = await r.json();
    return !!d.success;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- Cookie / 鉴权

function parseBasic(header) {
  if (!header || !header.startsWith('Basic ')) return null;
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
/** 从 sub_token cookie 还原用户。注意：用户名可能是邮箱（含 '.'），
 *  签名本身不含 '.'，因此按【最后一个】'.' 切分。 */
async function getUserFromCookie(req, env) {
  const ck = cookieValue(req, 'sub_token');
  if (!ck) return null;
  const dot = ck.lastIndexOf('.');
  if (dot <= 0) return null;
  const u = ck.slice(0, dot), sig = ck.slice(dot + 1);
  const rec = await env.USERS.get(u, { type: 'json' });
  if (!rec) return null;
  const want = await hmac(env.SESSION_SECRET || 'x', `${u}:${rec.expire}`);
  if (!safeEqual(sig, want)) return null;
  return { name: u, rec };
}

const PAGE_STYLE = `
body{font-family:-apple-system,'PingFang SC',sans-serif;background:#F9FAFB;color:#374151;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}
.card{background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:36px 32px;max-width:440px;width:100%;text-align:center}
h1{font-size:20px;margin:0 0 10px;color:#111827}
p{font-size:14px;line-height:1.7;margin:0 0 20px;color:#6B7280}
a.btn,.btn{display:inline-block;background:#DC2626;color:#fff;text-decoration:none;padding:10px 22px;border:0;border-radius:8px;font-size:14px;cursor:pointer}
a.btn:hover,.btn:hover{background:#B91C1C}
input,select{padding:10px 12px;border:1px solid #D1D5DB;border-radius:8px;font-size:14px;width:100%;box-sizing:border-box;margin:6px 0}
.msg{font-size:13px;min-height:18px;margin-top:6px;color:#6B7280}`;

function unauthorized() {
  const body = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="refresh" content="3; url=/subscribe/">
<title>需要订阅账号</title><style>${PAGE_STYLE}</style></head><body><div class="card">
<h1>需要订阅账号</h1>
<p>该内容为付费订阅专属。订阅后可查看完整外媒标题速览、中文翻译与摘要。</p>
<a class="btn" href="/subscribe/">查看订阅方案</a>
<p style="margin-top:16px;font-size:12px;color:#9CA3AF">3 秒后自动跳转…</p>
</div></body></html>`;
  return htmlRes(body, 401, {
    'WWW-Authenticate': `Basic realm="${CANONICAL_HOST}", charset="UTF-8"`,
  });
}

function expiredHTML(left) {
  const body = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>订阅已到期</title><style>${PAGE_STYLE}</style></head><body><div class="card">
<h1>${left < 0 ? '订阅已到期' : '订阅即将到期'}</h1>
<p>${left < 0 ? `你的账号已于 ${-left} 天前到期。` : `你的账号将在 ${left} 天后到期。`}<br>续费后即可继续访问完整内容。</p>
<a class="btn" href="/subscribe/">查看订阅方案</a>
</div></body></html>`;
  return htmlRes(body, 402);
}

async function proxy(url, req, env, isPublicAsset) {
  const up = new URL(url);
  up.hostname = env.ORIGIN_HOST;
  up.protocol = 'https:';
  up.port = '';
  // GitHub Pages 在 origin-stock 子域下目录索引（/latest/ → /latest/index.html）
  // 偶发不生效，这里显式补全，避免回源 404。
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

// ---------------------------------------------------------------- 订阅 API

async function apiVerifyEmail(req, env) {
  const { email, plan, turnstile } = await req.json().catch(() => ({}));
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json({ ok: false, msg: '邮箱格式不正确' }, 400);
  if (!PLAN_DAYS[plan]) return json({ ok: false, msg: '请选择套餐' }, 400);
  if (!await verifyTurnstile(env, turnstile, req.headers.get('CF-Connecting-IP'))) {
    return json({ ok: false, msg: '人机验证失败，请重试' }, 400);
  }

  const code = String(Math.floor(100000 + Math.random() * 900000));
  const rec = await env.USERS.get(email, { type: 'json' }) || {};
  if (rec.status === 'active') return json({ ok: false, msg: '该邮箱已有生效账号，请直接登录' }, 400);
  rec.email = email;
  rec.plan = plan;
  rec.status = 'pending';
  rec.code = code;
  rec.code_expire = Date.now() + 10 * 60 * 1000;
  rec.created = rec.created || nowCSTStr();
  await env.USERS.put(email, JSON.stringify(rec));

  const html = `<p>您的订阅验证码是：<b style="font-size:20px">${code}</b></p>
    <p>10 分钟内有效。若非本人操作请忽略。</p>`;
  const r = await sendEmail(env, email, '订阅验证码 - 外媒速览', html);
  if (!r.ok) return json({ ok: false, msg: '验证码邮件发送失败：' + r.err }, 500);
  await logEvent(env, 'web', '发送验证码', email, `套餐=${plan}`);
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
  const payToken = randToken(28);
  rec.pay_token = payToken;
  rec.pay_expire = Date.now() + 7 * 24 * 3600 * 1000;
  await env.USERS.put(email, JSON.stringify(rec));
  await logEvent(env, 'web', '邮箱验证通过', email, `套餐=${rec.plan}`);

  const planLabel = PLAN_LABEL[rec.plan] || rec.plan;
  const confirmUrl = `${siteUrl(env)}/api/confirm-pay?token=${payToken}&user=${encodeURIComponent(email)}`;
  const adminHtml = `<p><b>${esc(email)}</b> 已通过邮箱验证，申请订阅：<b>${planLabel}</b>。</p>
    <p>请确认收款后打开下方链接发放账号（页面上可按实际付款调整套餐时长）：</p>
    <p><a href="${confirmUrl}">${confirmUrl}</a></p>
    <p style="color:#888;font-size:12px">链接 7 天内有效，打开后需再次点击确认按钮才会发号。</p>`;
  const r = await sendEmail(env, adminEmail(env), `订阅确认：${email} - ${planLabel}`, adminHtml);
  if (!r.ok) return json({ ok: false, msg: '已验证，但通知管理员邮件失败：' + r.err }, 500);

  return json({ ok: true, msg: '邮箱验证成功。请完成付款，管理员确认后将自动发送账号。' });
}

/** 校验确认请求（token 一次性、7 天有效、状态 verified） */
async function loadPayRequest(env, token, user) {
  if (!token || !user) return { err: '缺少参数' };
  const rec = await env.USERS.get(user, { type: 'json' });
  if (!rec || rec.status !== 'verified') return { err: '该申请不存在或状态异常' };
  if (rec.pay_token !== token || Date.now() > (rec.pay_expire || 0)) return { err: '确认链接无效或已过期' };
  return { rec };
}

/** 第一步：确认页（只展示，无副作用 —— 防邮件客户端预取误触发） */
async function apiConfirmPayPage(req, env) {
  const url = new URL(req.url);
  const token = url.searchParams.get('token');
  const user = url.searchParams.get('user');
  const { rec, err } = await loadPayRequest(env, token, user);
  if (err) {
    return htmlRes(`<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>确认失败</title><style>${PAGE_STYLE}</style></head><body><div class="card">
<h1>无法确认</h1><p>${esc(err)}</p><a class="btn" href="/subscribe/">返回订阅页</a>
</div></body></html>`, 400);
  }
  const opts = Object.keys(PLAN_DAYS).map(k =>
    `<option value="${k}" ${k === rec.plan ? 'selected' : ''}>${PLAN_LABEL[k]}</option>`).join('');
  const body = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>确认收款</title><style>${PAGE_STYLE}</style></head><body><div class="card">
<h1>✅ 确认收款并发号</h1>
<p>申请邮箱：<b>${esc(user)}</b><br>申请套餐：${PLAN_LABEL[rec.plan] || esc(rec.plan)}</p>
<p style="text-align:left">如实际付款与申请套餐不符，请先调整时长：</p>
<form method="post" action="/api/confirm-pay">
  <input type="hidden" name="token" value="${esc(token)}">
  <input type="hidden" name="user" value="${esc(user)}">
  <select name="plan">${opts}</select>
  <button class="btn" type="submit">确认收款，立即发号</button>
</form>
<p style="margin-top:14px;font-size:12px;color:#9CA3AF">点击后将立即生成账号并邮件通知用户，不可撤销。</p>
</div></body></html>`;
  return htmlRes(body);
}

/** 第二步：真正发号 */
async function apiConfirmPayExec(req, env) {
  const form = await req.formData().catch(() => null);
  if (!form) return new Response('表单解析失败', { status: 400 });
  const token = form.get('token');
  const user = form.get('user');
  const planSel = form.get('plan');
  const { rec, err } = await loadPayRequest(env, token, user);
  if (err) return new Response(err, { status: 400 });

  const plan = PLAN_DAYS[planSel] ? planSel : (PLAN_DAYS[rec.plan] ? rec.plan : '1m');
  const password = genPassword(12);
  const salt = randToken(8);
  const hash = await sha256hex(`${salt}:${password}`);
  const days = PLAN_DAYS[plan];
  const expire = new Date(Date.now() + days * 86400000 + 8 * 3600 * 1000).toISOString().slice(0, 10);
  rec.plan = plan;
  rec.salt = salt; rec.hash = hash; rec.expire = expire;
  rec.status = 'active';
  rec.pay_token = ''; rec.pay_expire = 0;
  rec.issued_at = nowCSTStr();
  rec.expire_at = `${expire}T23:59:59+08:00`;   // 订阅有效期到到期日 23:59:59
  rec.note = rec.note || `自动发号(${plan})`;
  await env.USERS.put(user, JSON.stringify(rec));
  await logEvent(env, 'web', '确认收款发号', user, `套餐=${plan} 到期=${expire}`);

  const userHtml = `<p>订阅已开通 ✅</p>
    <p>站点：${esc(siteUrl(env))}<br>用户名：<b>${esc(user)}</b><br>密码：<b>${esc(password)}</b><br>有效期至：${expire}（${days} 天，${PLAN_LABEL[plan]}）</p>
    <p>打开 <a href="${esc(siteUrl(env))}/subscribe/">登录页</a>，填入上述用户名和密码即可。登录状态记忆 7 天。请勿转发给他人。</p>`;
  const r = await sendEmail(env, user, '订阅已开通 - 外媒速览账号', userHtml);
  if (!r.ok) return new Response('账号已发放，但用户邮件发送失败：' + r.err, { status: 500 });

  return htmlRes(`<html><body style="font-family:sans-serif;text-align:center;padding:60px">
    <h2>✅ 账号已发放</h2><p>${esc(user)} 的订阅账号（${PLAN_LABEL[plan]}）已发送至其邮箱。</p>
    <p><a href="/subscribe/">返回订阅页</a></p></body></html>`);
}

async function apiLogin(req, env) {
  const { user, pass, turnstile, redirect } = await req.json().catch(() => ({}));
  if (!user || !pass) return json({ ok: false, msg: '缺少用户名或密码' }, 400);
  if (!await verifyTurnstile(env, turnstile, req.headers.get('CF-Connecting-IP'))) {
    return json({ ok: false, msg: '人机验证失败，请重试' }, 400);
  }
  const rec = await env.USERS.get(user, { type: 'json' });
  if (!rec || (rec.status || 'active') !== 'active') {
    await logEvent(env, 'web', '登录失败', user, '账号不存在或未激活');
    return json({ ok: false, msg: '账号不存在或未激活' }, 401);
  }
  const left = daysLeft(rec.expire);
  if (left < 0) {
    await logEvent(env, 'web', '登录失败', user, '账号已过期');
    return json({ ok: false, msg: '账号已过期' }, 401);
  }
  const h = await sha256hex(`${rec.salt}:${pass}`);
  if (!safeEqual(h, rec.hash || '')) {
    await logEvent(env, 'web', '登录失败', user, '密码错误');
    return json({ ok: false, msg: '密码错误' }, 401);
  }
  const sig = await hmac(env.SESSION_SECRET || 'x', `${user}:${rec.expire}`);
  const cookie = `sub_token=${user}.${sig}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Lax`;
  // 只允许站内相对路径，防开放跳转
  const rd = (typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//')) ? redirect : '/latest/';
  await logEvent(env, 'web', '登录成功', user, `到期=${rec.expire}`);
  return json({ ok: true, msg: '登录成功', expire: rec.expire, redirect: rd }, 200, { 'Set-Cookie': cookie });
}

// ---------------------------------------------------------------- /subadmin 管理页

async function listAllUsers(env) {
  const names = [];
  let cursor;
  do {
    const page = await env.USERS.list({ limit: 500, cursor });
    for (const k of page.keys) {
      if (k.name.startsWith('_')) continue;   // 跳过 _log 等内部键
      names.push(k.name);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  const recs = await Promise.all(names.map(async name => {
    try {
      const rec = await env.USERS.get(name, { type: 'json' });
      return rec ? { name, rec } : null;
    } catch { return null; }
  }));
  return recs.filter(Boolean);
}

function statusBadge(status) {
  if (status === 'active') return '<span style="color:#059669;font-weight:700">已开通</span>';
  if (status === 'verified') return '<span style="color:#D97706;font-weight:700">待确认收款</span>';
  if (status === 'pending') return '<span style="color:#9CA3AF">待验证邮箱</span>';
  return '<span style="color:#9CA3AF">未知</span>';
}

async function handleSubadmin(req, env) {
  if (!env.USERS) return new Response('Worker 未绑定 KV namespace: USERS', { status: 500 });
  const url = new URL(req.url);

  if (url.searchParams.get('logout')) {
    return htmlRes(`<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="robots" content="noindex"><meta http-equiv="refresh" content="0; url=/subadmin">
</head><body></body></html>`, 200, {
      'Set-Cookie': 'sub_token=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax',
    });
  }

  const user = await getUserFromCookie(req, env);
  if (!user || !isAdmin(user.name, user.rec, env)) return subadminLogin(env);
  return subadminDashboard(req, env, user);
}

function subadminLogin(env) {
  const key = esc(env.TURNSTILE_SITE_KEY || '');
  const body = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>管理登录</title><style>${PAGE_STYLE}</style></head><body><div class="card">
<h1>管理登录</h1>
<form onsubmit="return false">
  <input id="u" type="text" placeholder="用户名" autocomplete="username">
  <input id="p" type="password" placeholder="密码" autocomplete="current-password">
  <div id="ts"></div>
  <button class="btn" onclick="doLogin()">登录</button>
  <div class="msg" id="m"></div>
</form>
</div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onloadTs" async defer></script>
<script>
var tsId = null;
function onloadTs() {
  if (!(window.turnstile && '${key}')) return;
  tsId = turnstile.render('#ts', { sitekey: '${key}', callback: function (t) { window._tsT = t; } });
}
async function doLogin() {
  var u = document.getElementById('u').value.trim();
  var p = document.getElementById('p').value;
  var r = await fetch('/api/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user: u, pass: p, turnstile: window._tsT || '', redirect: '/subadmin' })
  }).then(function (x) { return x.json(); });
  if (r.ok) { location.href = r.redirect || '/subadmin'; return; }
  document.getElementById('m').textContent = r.msg || '登录失败';
  window._tsT = '';
  if (window.turnstile && tsId !== null) turnstile.reset(tsId);
}
</script></body></html>`;
  return htmlRes(body);
}

async function subadminDashboard(req, env, me) {
  const all = await listAllUsers(env);
  // 排序：待确认收款 > 待验证 > 已开通（按到期升序，最先到期在前）
  const order = { verified: 0, pending: 1, active: 2 };
  all.sort((a, b) => {
    const sa = order[a.rec.status] ?? 3, sb = order[b.rec.status] ?? 3;
    if (sa !== sb) return sa - sb;
    if (sa === 2) return String(a.rec.expire || '').localeCompare(String(b.rec.expire || ''));
    return String(b.rec.created || '').localeCompare(String(a.rec.created || ''));
  });

  const total = all.length;
  const cnt = { active: 0, verified: 0, pending: 0 };
  for (const { rec } of all) if (cnt[rec.status] !== undefined) cnt[rec.status]++;

  const pages = Math.max(1, Math.ceil(total / SUB_PER_PAGE));
  let page = parseInt(new URL(req.url).searchParams.get('page') || '1', 10);
  if (!Number.isFinite(page) || page < 1) page = 1;
  if (page > pages) page = pages;
  const slice = all.slice((page - 1) * SUB_PER_PAGE, page * SUB_PER_PAGE);

  const rows = slice.map(({ name, rec }) => {
    const left = daysLeft(rec.expire);
    let expireCell = '—';
    if (rec.status === 'active' && rec.expire) {
      const exp = rec.expire_at || rec.expire;   // 优先带时分秒的 expire_at
      expireCell = `${esc(exp)}（${left >= 0 ? `剩 ${left} 天` : '<span style="color:#DC2626">已过期</span>'}）`;
    }
    return `<tr>
      <td style="max-width:230px;word-break:break-all">${esc(name)}</td>
      <td>${statusBadge(rec.status)}</td>
      <td>${esc(rec.plan || '')}</td>
      <td>${expireCell}</td>
      <td style="white-space:nowrap">${esc(rec.created || '')}</td>
      <td style="max-width:160px;word-break:break-all">${esc(rec.note || '')}</td>
    </tr>`;
  }).join('');

  const prev = page > 1 ? `<a href="/subadmin?page=${page - 1}">‹ 上一页</a>` : '<span style="color:#D1D5DB">‹ 上一页</span>';
  const next = page < pages ? `<a href="/subadmin?page=${page + 1}">下一页 ›</a>` : '<span style="color:#D1D5DB">下一页 ›</span>';

  // 操作日志（最近 LOG_SHOW 条）
  const log = (await env.USERS.get(LOG_KEY, { type: 'json' })) || [];
  const logRows = log.slice(0, LOG_SHOW).map(e =>
    `<tr><td style="white-space:nowrap">${esc(e.t)}</td><td>${esc(e.src)}</td><td>${esc(e.ev)}</td>
     <td>${esc(e.user)}</td><td>${esc(e.detail)}</td></tr>`).join('');

  const body = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>订阅管理</title>
<style>
body{font-family:-apple-system,'PingFang SC',sans-serif;background:#F9FAFB;color:#374151;margin:0;padding:24px}
.wrap{max-width:1060px;margin:0 auto}
h1{font-size:20px;color:#111827;margin:0 0 6px}
h2{font-size:16px;color:#111827;margin:28px 0 10px}
.bar{font-size:13px;color:#6B7280;margin-bottom:14px;display:flex;gap:14px;flex-wrap:wrap;align-items:center}
.bar a{color:#DC2626;text-decoration:none}
.sum{font-size:13px;color:#374151;margin-bottom:12px}
.sum b{color:#111827}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #E5E7EB;border-radius:10px;overflow:hidden;font-size:13px}
th,td{padding:8px 10px;border-bottom:1px solid #F3F4F6;text-align:left;vertical-align:top}
th{background:#F9FAFB;color:#6B7280;font-weight:600;font-size:12.5px}
tr:hover td{background:#FEF2F2}
.pager{margin-top:14px;font-size:13.5px;display:flex;gap:16px;align-items:center;color:#6B7280}
.pager a{color:#DC2626;text-decoration:none}
</style></head><body><div class="wrap">
<h1>订阅管理 <span style="font-size:12px;color:#9CA3AF;font-weight:400">/subadmin</span></h1>
<div class="bar">
  <span>登录：${esc(me.name)}</span>
  <a href="/subadmin?page=${page}">刷新</a>
  <a href="/subadmin?logout=1">退出</a>
</div>
<div class="sum">共 <b>${total}</b> ｜ 已开通 <b>${cnt.active}</b> ｜ 待确认收款 <b>${cnt.verified}</b> ｜ 待验证邮箱 <b>${cnt.pending}</b></div>
<table>
  <tr><th>用户名 / 邮箱</th><th>状态</th><th>套餐</th><th>到期（北京时间）</th><th>创建</th><th>备注</th></tr>
  ${rows || '<tr><td colspan="6" style="color:#9CA3AF;text-align:center;padding:24px">暂无记录</td></tr>'}
</table>
<div class="pager">${prev}<span>第 ${page} / ${pages} 页</span>${next}</div>

<h2>操作日志（最近 ${LOG_SHOW} 条，完整邮箱已打码）</h2>
<table>
  <tr><th>时间</th><th>来源</th><th>事件</th><th>用户</th><th>详情</th></tr>
  ${logRows || '<tr><td colspan="5" style="color:#9CA3AF;text-align:center;padding:24px">暂无日志</td></tr>'}
</table>
</div></body></html>`;
  return htmlRes(body);
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
      if (url.pathname === '/api/confirm-pay' && req.method === 'GET') return apiConfirmPayPage(req, env);
      if (url.pathname === '/api/confirm-pay' && req.method === 'POST') return apiConfirmPayExec(req, env);
      if (url.pathname === '/api/login' && req.method === 'POST') return apiLogin(req, env);
      return json({ ok: false, msg: '未知接口' }, 404);
    }

    // 隐藏管理页（自带鉴权，不回源）
    if (url.pathname === '/subadmin') return handleSubadmin(req, env);

    // 公开区直接放行
    if (isPublic(url.pathname)) return proxy(url, req, env, true);

    if (!env.USERS) return new Response('Worker 未绑定 KV namespace: USERS', { status: 500 });

    let user = await getUserFromCookie(req, env);
    if (!user) {
      const cred = parseBasic(req.headers.get('Authorization') || '');
      if (!cred) return unauthorized();
      const rec = await env.USERS.get(cred.user, { type: 'json' });
      if (!rec) return unauthorized();
      const h = await sha256hex(`${rec.salt}:${cred.pass}`);
      if (!safeEqual(h, rec.hash || '')) return unauthorized();
      if ((rec.status || 'active') === 'banned') return unauthorized();
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
