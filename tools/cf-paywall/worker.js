/**
 * stock.freelamp.com 付费墙 Worker
 *
 * 职责：
 *   1. 公开区（/、/trial/、/subscribe/、静态资源）直接放行
 *   2. 付费区（/latest/、/news/YYYYMMDD/）要求 Basic Auth
 *   3. 账号存 Cloudflare KV（USERS），含密码哈希与到期日
 *   4. 到期返回 402，引导到订阅页
 *
 * 说明：stock.freelamp.com 即主域，由本 Worker 直接接管，不再做老域名跳转。
 *       对外只暴露 stock.freelamp.com；源站走不对外公开的 origin-stock.freelamp.com。
 *
 * KV 记录格式（key = 用户名）：
 *   {"salt":"...","hash":"<sha256(salt:pass)>","expire":"2026-12-31","plan":"3m","note":""}
 *
 * 需要的 Worker 变量 / Secrets：
 *   ORIGIN_HOST     源站域名（Pages 绑定、不对外公开），如 origin-stock.freelamp.com
 *   SESSION_SECRET  免登录 Cookie 签名密钥
 *   USERS           KV namespace 绑定
 */

const enc = new TextEncoder();

/** 无需登录即可访问的路径前缀 */
const PUBLIC_PREFIXES = [
  '/trial', '/subscribe', '/assets', '/static',
  '/favicon.ico', '/robots.txt', '/sitemap.xml', '/jd_root.txt',
];

/** 免登录 Cookie 有效期（秒） */
const COOKIE_MAX_AGE = 7 * 24 * 3600;

/** 主域（仅用于 Basic Auth realm 显示与注释，无跳转行为） */
const CANONICAL_HOST = 'stock.freelamp.com';


async function sha256hex(s) {
  const d = await crypto.subtle.digest('SHA-256', enc.encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('');
}

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
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

/** 今天（北京时间）YYYY-MM-DD */
function todayCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

/** 距到期还剩几天，负数表示已过期 */
function daysLeft(expire) {
  if (!expire) return -1;
  const a = Date.parse(`${todayCST()}T00:00:00Z`);
  const b = Date.parse(`${expire}T00:00:00Z`);
  if (Number.isNaN(b)) return -1;
  return Math.round((b - a) / 86400000);
}

function unauthorized() {
  // 保留 401 + Basic Auth 挑战（否则浏览器不再弹登录框，已付费用户无法登录）；
  // 同时返回引导页：未登录游客取消弹窗后自动跳转 /subscribe/。
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
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'WWW-Authenticate': `Basic realm="${CANONICAL_HOST}", charset="UTF-8"`,
      'Cache-Control': 'no-store',
    },
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
<p>${left < 0
    ? `你的账号已于 ${-left} 天前到期。`
    : `你的账号将在 ${left} 天后到期。`}<br>续费后即可继续访问完整内容。</p>
<a href="/subscribe/">查看订阅方案</a>
</div></body></html>`;
  return new Response(body, {
    status: 402,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}

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

async function proxy(url, req, env, isPublicAsset) {
  const up = new URL(url);
  up.hostname = env.ORIGIN_HOST;
  up.protocol = 'https:';
  up.port = '';
  // GitHub Pages 在 origin-stock 子域下目录索引（/latest/ → /latest/index.html）
  // 偶发不生效，这里显式补全，避免回源 404。
  if (up.pathname.endsWith('/')) {
    up.pathname += 'index.html';
  }
  const out = await fetch(new Request(up, {
    method: req.method,
    headers: req.headers,
    body: ['GET', 'HEAD'].includes(req.method) ? undefined : req.body,
    redirect: 'follow',
  }));
  const res = new Response(out.body, out);
  res.headers.set('Cache-Control', isPublicAsset ? 'public, max-age=300' : 'private, max-age=300');
  if (!isPublicAsset) res.headers.set('X-Robots-Tag', 'noindex, nofollow');
  return res;
}

export default {
  async fetch(req, env) {
    if (!env.ORIGIN_HOST) {
      return new Response('Worker 未配置 ORIGIN_HOST', { status: 500 });
    }
    const url = new URL(req.url);

    // stock.freelamp.com 即主域，直接在此处理，不做跨域跳转。

    // 公开区直接放行
    if (isPublic(url.pathname)) return proxy(url, req, env, true);

    if (!env.USERS) {
      return new Response('Worker 未绑定 KV namespace: USERS', { status: 500 });
    }

    let user = null;

    // 1) 免登录 Cookie（值格式：user.hmac）
    const ck = cookieValue(req, 'sub_token');
    if (ck) {
      const dot = ck.indexOf('.');
      if (dot > 0) {
        const u = ck.slice(0, dot);
        const sig = ck.slice(dot + 1);
        const rec = await env.USERS.get(u, { type: 'json' });
        if (rec) {
          const want = await hmac(env.SESSION_SECRET || 'x', `${u}:${rec.expire}`);
          if (safeEqual(sig, want)) user = { name: u, rec };
        }
      }
    }

    // 2) Basic Auth
    if (!user) {
      const cred = parseBasic(req.headers.get('Authorization') || '');
      if (!cred) return unauthorized();
      const rec = await env.USERS.get(cred.user, { type: 'json' });
      if (!rec) return unauthorized();
      const h = await sha256hex(`${rec.salt}:${cred.pass}`);
      if (!safeEqual(h, rec.hash || '')) return unauthorized();
      user = { name: cred.user, rec };
    }

    // 3) 到期检查
    const left = daysLeft(user.rec.expire);
    if (left < 0) return expiredHTML(left);

    // 4) 放行
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
