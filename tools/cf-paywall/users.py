#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stock.freelamp.com 订阅账号管理

用法：
  python3 users.py add  alice --plan 3m [--note "微信：xxx"]
  python3 users.py add  alice --days 30
  python3 users.py add  alice --expire 2026-12-31
  python3 users.py renew alice --plan 1y      # 在现有到期日基础上续期
  python3 users.py list
  python3 users.py del  alice
  python3 users.py sync                       # 把本地待写入的账号推送到 KV

套餐：1m=30天 3m=90天 6m=180天 1y=365天（对应 10/28/48/88 元）

写入 KV 的方式（按优先级）：
  1. ~/.codex/.env 里的 CF_API_TOKEN + CF_ACCOUNT_ID + CF_KV_NAMESPACE_ID  → 直接调 CF API
  2. 都没有                                                       → 落盘 pending.json，之后 sync 推送
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def load_dotenv(path=None):
    """从 ~/.codex/.env 读取 CF_* 变量注入 os.environ（不覆盖已存在的 env）。
    users.py 需要 CF_API_TOKEN / CF_ACCOUNT_ID / CF_KV_NAMESPACE_ID；
    .env 里 token 可能叫 CLOUDFLARE_API_TOKEN，这里统一映射为 CF_API_TOKEN。
    这样 users.py 无需在 shell 里 export，也不必走 wrangler。"""
    p = Path(path) if path else Path.home() / ".codex" / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        # 归一化：CLOUDFLARE_API_TOKEN -> CF_API_TOKEN
        if k == "CLOUDFLARE_API_TOKEN":
            k = "CF_API_TOKEN"
        if k in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_KV_NAMESPACE_ID") and k not in os.environ:
            os.environ[k] = v


load_dotenv()  # 启动即加载 ~/.codex/.env 的 CF_* 变量
from pathlib import Path

HERE = Path(__file__).parent
PENDING = HERE / "pending.json"

PLANS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
PRICES = {"1m": "10 元 / 1 个月", "3m": "28 元 / 3 个月", "6m": "48 元 / 6 个月", "1y": "88 元 / 1 年"}
SITE = "https://stock.freelamp.com"

# 去掉 0/O/1/l/I 等易混字符
ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


# ---------------------------------------------------------------- 工具

def today() -> dt.date:
    return dt.date.today()


def now_str() -> str:
    """当前北京时间 YYYY-MM-DD HH:MM:SS（与 Worker 端 nowCSTStr 一致）"""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def mask_email(s: str) -> str:
    """邮箱打码：albertxu@freelamp.com -> al***@freelamp.com（与 Worker 端一致）"""
    s = str(s or "")
    i = s.find("@")
    if i < 0:
        return s[:2] + "***"
    return s[:min(2, i)] + "***" + s[i:]


LOG_KEY = "_log"
LOG_MAX = 1000


def log_event(src: str, ev: str, user: str, detail: str = "") -> None:
    """把 CLI 动作追加到 KV _log（与 Worker 共用；失败不影响主流程）。"""
    try:
        # 读现有日志
        url = (f"https://api.cloudflare.com/client/v4/accounts/{os.environ.get('CF_ACCOUNT_ID')}"
               f"/storage/kv/namespaces/{os.environ.get('CF_KV_NAMESPACE_ID')}"
               f"/values/{urllib.parse.quote(LOG_KEY)}")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ.get('CF_API_TOKEN')}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                log = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log = []
            else:
                raise
        log.insert(0, {"t": now_str(), "src": src, "ev": ev,
                       "user": mask_email(user), "detail": detail})
        if len(log) > LOG_MAX:
            log = log[:LOG_MAX]
        ok = kv_put_via_api(LOG_KEY, log)
        if not ok:
            print("  ⚠️  日志写入失败（不影响本次操作）")
    except Exception as e:
        print(f"  ⚠️  日志写入异常：{e}（不影响本次操作）")


def gen_password(n: int = 12) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def make_record(password: str, expire: str, plan: str = "", note: str = "") -> dict:
    salt = secrets.token_hex(8)
    return {
        "salt": salt,
        "hash": hashlib.sha256(f"{salt}:{password}".encode()).hexdigest(),
        "expire": expire,
        "plan": plan,
        "status": "active",   # 新发账号均可用；pending/verified 为订阅流程中间态
        "note": note,
        "created": now_str(),
    }


def load_pending() -> dict:
    if PENDING.exists():
        try:
            return json.loads(PENDING.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_pending(d: dict) -> None:
    PENDING.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- KV 写入

def kv_put_via_api(user: str, rec: dict) -> bool:
    token = os.environ.get("CF_API_TOKEN")
    acct = os.environ.get("CF_ACCOUNT_ID")
    ns = os.environ.get("CF_KV_NAMESPACE_ID")
    if not (token and acct and ns):
        return False
    url = (f"https://api.cloudflare.com/client/v4/accounts/{acct}"
           f"/storage/kv/namespaces/{ns}/values/{urllib.parse.quote(user)}")
    req = urllib.request.Request(url, data=json.dumps(rec).encode(), method="PUT", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "text/plain",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status in (200, 201)
    except urllib.error.URLError as e:
        print(f"  ⚠️  CF API 写入失败：{e}")
        return False


def kv_get_via_api(user: str):
    """从 KV 读取单账号记录；不存在返回 None。"""
    token = os.environ.get("CF_API_TOKEN")
    acct = os.environ.get("CF_ACCOUNT_ID")
    ns = os.environ.get("CF_KV_NAMESPACE_ID")
    if not (token and acct and ns):
        return None
    url = (f"https://api.cloudflare.com/client/v4/accounts/{acct}"
           f"/storage/kv/namespaces/{ns}/values/{urllib.parse.quote(user)}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"  ⚠️  CF API 读取失败：{e}")
        return None


def kv_list_via_api() -> dict:
    """列出 KV 全部账号（用户名 -> 记录）。无凭据返回空 dict。"""
    token = os.environ.get("CF_API_TOKEN")
    acct = os.environ.get("CF_ACCOUNT_ID")
    ns = os.environ.get("CF_KV_NAMESPACE_ID")
    if not (token and acct and ns):
        return {}
    url = (f"https://api.cloudflare.com/client/v4/accounts/{acct}"
           f"/storage/kv/namespaces/{ns}/keys?limit=1000")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            keys = json.loads(r.read().decode()).get("result", [])
    except urllib.error.URLError as e:
        print(f"  ⚠️  CF API 列举失败：{e}")
        return {}
    out = {}
    for k in keys:
        rec = kv_get_via_api(k["name"])
        if rec:
            out[k["name"]] = rec
    return out


def kv_delete_via_api(user: str) -> bool:
    """从 KV 删除账号。成功/不存在均返回 True。"""
    token = os.environ.get("CF_API_TOKEN")
    acct = os.environ.get("CF_ACCOUNT_ID")
    ns = os.environ.get("CF_KV_NAMESPACE_ID")
    if not (token and acct and ns):
        return False
    url = (f"https://api.cloudflare.com/client/v4/accounts/{acct}"
           f"/storage/kv/namespaces/{ns}/values/{urllib.parse.quote(user)}")
    req = urllib.request.Request(url, method="DELETE",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        urllib.request.urlopen(req, timeout=20).status
        return True
    except urllib.error.URLError as e:
        print(f"  ⚠️  CF API 删除失败：{e}")
        return False


def kv_put(user: str, rec: dict) -> str:
    """返回 'api' / 'pending'。优先直连 CF API（读取 ~/.codex/.env 的 CF_* 变量），
    失败则落盘 pending.json 待 sync，不再走 wrangler（其经代理写入不可靠）。"""
    if kv_put_via_api(user, rec):
        return "api"
    pending = load_pending()
    pending[user] = rec
    save_pending(pending)
    return "pending"


# ---------------------------------------------------------------- 命令

def cmd_add(args):
    if args.plan:
        days = PLANS[args.plan]
        expire = today() + dt.timedelta(days=days)
    elif args.days:
        days = args.days
        expire = today() + dt.timedelta(days=days)
    else:
        expire = dt.date.fromisoformat(args.expire)
        days = (expire - today()).days

    password = args.password or gen_password()
    user = args.user
    rec = make_record(password, expire.isoformat(), args.plan or "", args.note or "")

    where = kv_put(user, rec)

    log_event("cli", "新增账号", user,
              f"套餐={args.plan or str(days)+'天'} 到期={expire.isoformat()} 方式={where}")

    print()
    print("=" * 52)
    print(f"  用户名：{user}")
    print(f"  密　码：{password}")
    print(f"  有效期：{expire.isoformat()}（{days} 天）")
    if args.plan:
        print(f"  套　餐：{PRICES[args.plan]}")
    if args.note:
        print(f"  备　注：{args.note}")
    print(f"  写入方式：{where}")
    print("=" * 52)
    print()
    print("--- 发给用户的微信文案（可直接复制）---")
    print(wechat_message(user, password, expire.isoformat(), days))
    print("---------------------------------------")
    if where == "pending":
        print(f"\n⚠️  未配置 CF 凭据，已落盘 {PENDING.name}。"
              f"配好 CF_API_TOKEN / CF_ACCOUNT_ID / CF_KV_NAMESPACE_ID 后跑 sync 推送。")


def cmd_renew(args):
    pending = load_pending()
    known_expire = None
    existing = pending.get(args.user)
    if existing:
        known_expire = dt.date.fromisoformat(existing["expire"])
    if args.expire:
        new_expire = dt.date.fromisoformat(args.expire)
    else:
        days = PLANS[args.plan] if args.plan else args.days
        base = max(known_expire or today(), today())
        new_expire = base + dt.timedelta(days=days)
    password = args.password or gen_password()
    rec = make_record(password, new_expire.isoformat(),
                      args.plan or (existing or {}).get("plan", ""),
                      args.note or (existing or {}).get("note", ""))
    where = kv_put(args.user, rec)
    log_event("cli", "续期", args.user,
              f"新到期={new_expire.isoformat()} 套餐={args.plan or str(days)+'天'} 方式={where}")
    print(f"✅ 续期 {args.user} → {new_expire.isoformat()}（写入：{where}）")
    print()
    print(wechat_message(args.user, password, new_expire.isoformat(),
                         (new_expire - today()).days))


def cmd_list(args):
    d = kv_list_via_api()
    if not d:
        print("KV 内暂无账号（或 CF 凭据未配置）。")
        return
    print(f"{'用户名':<20}{'到期日':<14}{'剩余':<8}{'套餐':<6}{'创建':<21}备注")
    print("-" * 84)
    for u, r in sorted(d.items(), key=lambda x: x[1]["expire"]):
        exp = dt.date.fromisoformat(r["expire"])
        left = (exp - today()).days
        flag = "已过期" if left < 0 else f"{left} 天"
        created = r.get("created", "")
        if len(created) == 10:
            created += " 00:00:00"
        print(f"{u:<20}{r['expire']:<14}{flag:<8}{r.get('plan',''):<6}{created:<21}{r.get('note','')}")


def cmd_del(args):
    ok = kv_delete_via_api(args.user)
    # 同步清掉本地 pending（若有）
    d = load_pending()
    if args.user in d:
        d.pop(args.user)
        save_pending(d)
    if ok:
        log_event("cli", "删除账号", args.user, "")
        print(f"🗑️  已删除 KV 账号 {args.user}")
    else:
        print(f"⚠️  KV 删除失败（检查 CF 凭据）；本地 pending 已清理。")


def cmd_passwd(args):
    """重置密码：只改 salt/hash，保留 expire/plan/note 等其他字段。
    可选 --role admin 给账号挂管理员角色（/subadmin 可见）。"""
    rec = kv_get_via_api(args.user)
    if not rec:
        sys.exit(f"账号不存在：{args.user}（先跑 list 查看）")
    old = rec.get("expire", "?")
    password = args.password or gen_password()
    rec["salt"] = secrets.token_hex(8)
    rec["hash"] = hashlib.sha256(f"{rec['salt']}:{password}".encode()).hexdigest()
    if args.role:
        rec["role"] = args.role
    if not rec.get("status"):
        rec["status"] = "active"   # 老记录无 status 字段，补齐为可用
    ok = kv_put_via_api(args.user, rec)
    if not ok:
        sys.exit("❌ KV 写入失败（检查 CF 凭据/网络；必要时加 HTTPS_PROXY=http://wpad.lan:8888 前缀）")
    log_event("cli", "重置密码", args.user, f"到期不变={old}" + (f" 角色={args.role}" if args.role else ""))
    print()
    print("=" * 52)
    print(f"  已重置密码：{args.user}")
    print(f"  新密码：{password}")
    print(f"  到期日不变：{old}")
    if args.role:
        print(f"  角色：{args.role}")
    print("=" * 52)


def cmd_sync(args):
    d = load_pending()
    if not d:
        print("pending.json 为空，无需同步")
        return
    ok, fail = 0, []
    for u, rec in d.items():
        if kv_put_via_api(u, rec):
            ok += 1
        else:
            fail.append(u)
    print(f"✅ 同步成功 {ok} 个" + (f"，失败 {len(fail)}：{fail}" if fail else ""))
    if not fail:
        # 全部同步成功，清空 pending
        PENDING.unlink(missing_ok=True)


def wechat_message(user: str, password: str, expire: str, days: int) -> str:
    return (
        f"订阅已开通 ✅\n\n"
        f"站点：{SITE}\n"
        f"用户名：{user}\n"
        f"密码：{password}\n"
        f"有效期至：{expire}（{days} 天）\n\n"
        f"用法：浏览器打开站点，在弹出的登录框填入上面的用户名和密码即可，"
        f"登录状态会记住 7 天。\n"
        f"到期前续费可无缝衔接，账号密码不变。\n\n"
        f"请勿转发给他人，谢谢 🙏"
    )


# ---------------------------------------------------------------- 入口

def main():
    p = argparse.ArgumentParser(description="stock.freelamp.com 订阅账号管理")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="新建账号")
    a.add_argument("user")
    g = a.add_mutually_exclusive_group()
    g.add_argument("--plan", choices=list(PLANS))
    g.add_argument("--days", type=int)
    g.add_argument("--expire")
    a.add_argument("--password", help="不指定则自动生成 12 位随机密码")
    a.add_argument("--note")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("renew", help="续期")
    r.add_argument("user")
    g2 = r.add_mutually_exclusive_group()
    g2.add_argument("--plan", choices=list(PLANS))
    g2.add_argument("--days", type=int)
    g2.add_argument("--expire")
    r.add_argument("--password")
    r.add_argument("--note")
    r.set_defaults(func=cmd_renew)

    l = sub.add_parser("list", help="查看 KV 全部账号（真实线上）")
    l.set_defaults(func=cmd_list)

    d = sub.add_parser("del", help="删除 KV 账号（直连，非仅本地）")
    d.add_argument("user")
    d.set_defaults(func=cmd_del)

    pw = sub.add_parser("passwd", help="重置密码（到期日/套餐不变；可--role admin）")
    pw.add_argument("user")
    pw.add_argument("--password", help="不指定则自动生成 12 位随机密码")
    pw.add_argument("--role", help="设置角色，如 admin")
    pw.set_defaults(func=cmd_passwd)

    s = sub.add_parser("sync", help="把 pending.json 推送到 KV")
    s.set_defaults(func=cmd_sync)

    args = p.parse_args()
    if args.cmd in ("add", "renew") and not (args.plan or args.days or args.expire):
        p.error("需要指定 --plan / --days / --expire 之一")
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
