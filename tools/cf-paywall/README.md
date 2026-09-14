# stock.freelamp.com 付费订阅架构

> 一个人能维护的最小付费站：抓取在仓库内容侧（公开），付费墙在 Cloudflare Worker，账号存 KV，订阅收款走微信。
> 主域即 stock.freelamp.com，由 Worker 直接接管，无老域名跳转。

## 1. 全貌

```
        ┌─────────────────────────────────────────────────────────────┐
        │                公开（爬虫能进，未订阅）                     │
        │                                                             │
        │   /                        → 落地页（试读 + 订阅入口）        │
        │   /trial/                  → 今天最新 5 条标题               │
        │   /subscribe/              → 套餐 + 微信收款码 + 3 步流程    │
        │   /assets/                 → 静态资源（QR 图等）              │
        │                                                             │
        ├─────────────────────────────────────────────────────────────┤
        │                付费（要求 Basic Auth）                       │
        │                                                             │
        │   /latest/                 → 今日全部标题（约 300 条）       │
        │   /news/YYYYMMDD/          → 每日归档                        │
        │                                                             │
        ├─────────────────────────────────────────────────────────────┤
        │                兼容                                          │
        │                                                             │
        │   stock.freelamp.com/*     → 301 到 news.freelamp.com/*     │
        └─────────────────────────────────────────────────────────────┘
                                          ▲
                                          │ KV 校验 + 回源
                                          │
                              ┌────────────────────────┐
                              │ Cloudflare Worker       │
                              │   - 路径分流（公开/付费）│
                              │   - 账号校验（KV）       │
                              │   - 到期检查             │
                              │   - 7 天免登录 Cookie    │
                              └────────────────────────┘
                                          │
                                          │ fetch（对外只暴露 stock.freelamp.com）
                                          ▼
                              ┌────────────────────────┐
                              │ GitHub Pages 源站       │
                              │ origin-stock.freelamp.com│
                              │ （自定义子域，不对外）   │
                              └────────────────────────┘
```

**为什么 github.io 不会绕过**：项目页一旦绑自定义域，`username.github.io/仓库/*` 全部
301 跳回主域；用户访问 `leisurelinux.github.io/on-stock/...` 也只会撞到 Worker 401。

**为什么 stock 不再 301 到 news**：本站主域就是 stock.freelamp.com，Worker 直接接管
stock，去掉了原先 news 主域 + stock 301 跳转的设计。源站用对外不可见的
`origin-stock.freelamp.com`，避免 Worker 回源到自己造成死循环。

## 2. 流量

| 角色 | 动作 | 路径 |
|---|---|---|
| 路人 | 搜外媒信息进来 | 入口页 → 试读 5 条 → 跳订阅页 |
| 订阅者 | 微信付款后收到账号 | 访问主域 → 浏览器弹窗输账号密码 → 7 天免登录 |
| 续期 | 同一账号，再付一次 | 旧密码不变，到期日延续，无需换密码 |

## 3. 价格体系

| 套餐 | 周期 | 价格 | 日均 |
|---|---|---|---|
| 1m | 30 天 | ¥10 | 0.33 |
| 3m | 90 天 | ¥28 | 0.31 |
| 6m | 180 天 | ¥48 | 0.27 |
| 1y | 365 天 | ¥88 | 0.24 |

## 4. 部署步骤

### 4.1 仓库：把 Pages 自定义域换成源站子域

1. Cloudflare DNS 加 `origin-stock` → CNAME `leisurelinux.github.io`
2. 仓库 Settings → Pages → Custom domain 改填 `origin-stock.freelamp.com`
3. 等证书签发（通常几分钟），原 `stock.freelamp.com` 会被 GitHub 自动解绑
4. 随后在 Cloudflare 把 `stock.freelamp.com` 绑到 Worker 的 Custom Domain（见 4.3）

### 4.2 Worker：建命名空间 + 部署

```bash
# 一次性创建 KV 命名空间
npx wrangler kv namespace create USERS
# 把返回的 id 填到 wrangler.toml 的 id = 处

# 设置密钥
openssl rand -hex 32  # 生成 SESSION_SECRET
npx wrangler secret put SESSION_SECRET   # 粘贴
npx wrangler login
npx wrangler deploy
```

### 4.3 域名：Worker 绑主域

- `stock.freelamp.com` —— 主入口，由 Worker 直接接管（无 301）

Worker → Settings → Triggers → Custom Domains 加这一条即可。
（旧设计里的 `news.freelamp.com` 已废弃，不再绑定。）

### 4.4 上传微信收款码

```bash
mkdir -p docs/assets
cp ~/wechat-pay-qr.png docs/assets/wechat-pay-qr.png
git add docs/assets/wechat-pay-qr.png && git commit -m "assets: 微信收款码" && git push
```

下次 build 时检测到该文件，订阅页就显示二维码；缺图时显示占位提示。

### 4.5 发账号（运维）

不需要 `npx wrangler`，直接：

```bash
# 推荐：配 CF API token 走直连（比 wrangler 快 10×）
export CF_API_TOKEN=xxx
export CF_ACCOUNT_ID=xxx
export CF_KV_NAMESPACE_ID=xxx

# 发一个 3 个月账号
python3 tools/cf-paywall/users.py add alice --plan 3m

# 自动生成密码 + 打印可直接复制给用户的微信文案
```

## 5. KV 账号格式

```json
{
  "salt": "1f3a9b...",
  "hash": "<sha256(salt:password)>",
  "expire": "2026-12-06",
  "plan": "3m",
  "note": "",
  "created": "2026-09-07"
}
```

**安全性**：
- 密码 SHA-256 哈希存储（Worker 端做哈希比对时需要明文）
- Cookie 用 `HMAC-SHA256(SESSION_SECRET, user:expire)` 签名，7 天有效
- 续期后 expire 改变，旧 Cookie 自动失效（强制重登录走新校验）

## 6. 日常维护

```bash
# 列账号
python3 tools/cf-paywall/users.py list

# 续期
python3 tools/cf-paywall/users.py renew alice --plan 1y
# 在原到期日上再加 365 天（若已过期则从今天起算）

# 删除
python3 tools/cf-paywall/users.py del alice
# 仅删本地 pending.json；KV 需另行：npx wrangler kv key delete --binding=USERS alice
```

## 7. 升级路径

当用户多了，可以加：

- **付款自动确认**：用微信商户 API 监听回调，收到款后 `users.py` 自动 `renew`。零人工。
- **多源分发**：建第二个 Worker + 新子域（如 `worldnews.freelamp.com`），共享同一个 KV。
- **换 Zero Trust Access**：不要 Basic Auth 弹窗、要邮箱 OTP / Google 登录的话，
  Worker 删掉，CF Access 一条规则保护 `/latest/*` 即可（KV 还能复用做用户组）。

## 8. 隐私 / 脱敏

- 付款走微信：付款者微信昵称 / 微信号会出现在收款记录里，人工对账
- 账号 `note` 字段建议填付款人微信号或订单尾号，方便核对
- 密码以明文回显在终端：复制给用户后建议终端里 `clear`（工具不会自动清）
- 配置文件 `wrangler.toml` 内含子域信息，已是公开域名，**不要**塞 token
