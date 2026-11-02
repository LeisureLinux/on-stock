#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把付费页从 dist_paid/ 上传到 Cloudflare KV namespace `SITE`。

为什么需要这一步
----------------
仓库是公开的，GitHub Pages 源站、raw.githubusercontent.com、cdn.jsdelivr.net
都能直接读到仓库里的文件。所以**付费内容一旦进了仓库，就等于公开**，Worker 挡不住。
付费页因此构建到仓库外的 dist_paid/（已 gitignore），再由本脚本上传到 KV，
只有 Worker 拿得到（Worker 回源只取公开区，付费区走 KV）。

key 规范（与 worker.js 的 kvPage 一致）
--------------------------------------
  dist_paid/latest/index.html           -> latest/index.html
  dist_paid/news/20260923/index.html    -> news/20260923/index.html
  dist_paid/news/index.html             -> news/index.html

用法
----
  python3 scripts/publish_paid.py                # 全量上传（先 build.py 生成 dist_paid）
  python3 scripts/publish_paid.py --dry-run      # 只列出将要上传的 key
  python3 scripts/publish_paid.py --date 20260923  # 只传某天（外加 latest/ 与 news/ 索引）
  python3 scripts/publish_paid.py --prune        # 顺带删除 KV 里已不在 dist_paid 的 key
  python3 scripts/publish_paid.py --verify       # 只读回 KV 校验（不上传）

凭据
----
  复用 users.py 的方式：读 ~/.codex/.env
    CF_API_TOKEN / CF_ACCOUNT_ID
  namespace id 取环境变量 CF_KV_NAMESPACE_SITE_ID，
  缺省时从 tools/cf-paywall/wrangler.toml 的 binding = "SITE" 读取（单一来源）。
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAID_DIR = ROOT / "dist_paid"
WRANGLER_TOML = ROOT / "tools" / "cf-paywall" / "wrangler.toml"

# KV 单值上限 25 MiB（单文件），付费页最大约 350 KB，留个安全阈值
MAX_VALUE_BYTES = 20 * 1024 * 1024
# 并发上传数（KV 免费额度 1000 写/天，这里远低于）
WORKERS = 8

# ---- 出口选择 -----------------------------------------------------------
# Cloudflare API 在境内直连会被 TLS 重置 / 握手超时（实测 43 成功 16 失败），
# 必须走本机 sing-box socks 出口。与 fetch_news.py 保持同一套开关语义。
#
# ⚠️ 不能用 urllib 的 ProxyHandler 走 socks：urllib 不支持 socks://  scheme，
#    喂它 socks5h:// 只会得到 Connection reset。这里统一用 curl 作为传输层
#    （curl 原生支持 -x socks5h://），行为与 fetch_news.py 一致。
KV_PROXY = os.environ.get("KV_PROXY", "auto").strip().lower()
KV_SOCKS = os.environ.get("KV_SOCKS", "socks5h://127.0.0.1:1080")


def _curl(url: str, method: str, token: str, timeout: int,
          body: bytes | None = None):
    """用 curl 打一次 Cloudflare API，返回 (status, body_bytes)。

    出口顺序由 KV_PROXY 决定：
      proxy  -> 只走 socks
      direct -> 只走直连
      auto   -> 先 socks，失败再直连（默认）
    """
    if KV_PROXY == "proxy":
        order = [KV_SOCKS]
    elif KV_PROXY == "direct":
        order = [None]
    else:
        order = [KV_SOCKS, None]

    last = None
    for proxy in order:
        cmd = ["curl", "-sS", "-X", method, "--max-time", str(timeout),
               "-H", f"Authorization: Bearer {token}", "-w", "\n%{http_code}"]
        if body is not None:
            cmd += ["-H", "Content-Type: text/html; charset=utf-8",
                    "--data-binary", "@-"]
        if proxy:
            cmd += ["-x", proxy]
        cmd.append(url)
        try:
            r = subprocess.run(cmd, input=body, capture_output=True,
                               timeout=timeout + 15)
        except Exception as e:  # noqa: BLE001
            last = e
            continue
        out = r.stdout
        if r.returncode != 0 or not out:
            last = RuntimeError(
                f"curl rc={r.returncode} {r.stderr.decode('utf-8', 'replace')[:200]}")
            continue
        # 最后一行是 -w 写的 http_code，其余是响应体
        nl = out.rfind(b"\n")
        if nl < 0:
            last = RuntimeError("curl 输出异常")
            continue
        payload, code_s = out[:nl], out[nl + 1:].strip()
        try:
            return int(code_s), payload
        except ValueError:
            last = RuntimeError(f"无法解析 http_code: {code_s!r}")
            continue
    raise last if last else RuntimeError("curl 未执行")


def load_dotenv(path=None):
    """从 ~/.codex/.env 读取 CF_* 变量注入 os.environ（不覆盖已存在的 env）。
    与 tools/cf-paywall/users.py 的 load_dotenv 保持同一行为。"""
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
        if k == "CLOUDFLARE_API_TOKEN":
            k = "CF_API_TOKEN"
        if k in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_KV_NAMESPACE_SITE_ID") and k not in os.environ:
            os.environ[k] = v


def site_namespace_id() -> str:
    """SITE namespace id：优先环境变量，其次 tools/cf-paywall/wrangler.toml（单一来源）。"""
    env = os.environ.get("CF_KV_NAMESPACE_SITE_ID")
    if env:
        return env.strip()
    if not WRANGLER_TOML.exists():
        return ""
    # wrangler.toml 里每个 [[kv_namespaces]] 块形如：
    #   [[kv_namespaces]]
    #   binding = "SITE"
    #   id = "..."
    # 按块切分，找 binding == "SITE" 的那块的 id。
    for block in WRANGLER_TOML.read_text(encoding="utf-8").split("[[kv_namespaces]]")[1:]:
        binding = block_id = ""
        for raw in block.splitlines():
            line = raw.strip()
            if line.startswith("["):      # 进入下一个 section，本块结束
                break
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"')
            if k == "binding":
                binding = v
            elif k == "id":
                block_id = v
        if binding == "SITE":
            return block_id
    return ""


def api_creds():
    token = os.environ.get("CF_API_TOKEN")
    acct = os.environ.get("CF_ACCOUNT_ID")
    ns = site_namespace_id()
    missing = [n for n, v in (("CF_API_TOKEN", token), ("CF_ACCOUNT_ID", acct),
                              ("namespace id", ns)) if not v]
    if missing:
        print(f"❌ 缺少凭证：{', '.join(missing)}")
        print("   把 CF_API_TOKEN / CF_ACCOUNT_ID 放进 ~/.codex/.env，")
        print("   namespace id 可放 CF_KV_NAMESPACE_SITE_ID 或由 wrangler.toml 提供。")
        return None
    return token, acct, ns


def kv_url(acct: str, ns: str, suffix: str) -> str:
    return (f"https://api.cloudflare.com/client/v4/accounts/{acct}"
            f"/storage/kv/namespaces/{ns}/{suffix}")


def kv_put(token: str, acct: str, ns: str, key: str, body: bytes) -> tuple:
    """上传一个 key。返回 (key, ok, err)。"""
    url = kv_url(acct, ns, "values/" + urllib.parse.quote(key, safe=""))
    try:
        status, _ = _curl(url, "PUT", token, 60, body=body)
    except Exception as e:  # noqa: BLE001
        return key, False, str(e)
    if status in (200, 201):
        return key, True, None
    return key, False, f"HTTP {status}"


def kv_get(token: str, acct: str, ns: str, key: str):
    """读回一个 key 的字节；不存在返回 None。"""
    url = kv_url(acct, ns, "values/" + urllib.parse.quote(key, safe=""))
    try:
        status, payload = _curl(url, "GET", token, 30)
    except Exception as e:  # noqa: BLE001
        raise
    if status == 404:
        return None
    return payload


def kv_delete(token: str, acct: str, ns: str, key: str) -> bool:
    url = kv_url(acct, ns, "values/" + urllib.parse.quote(key, safe=""))
    try:
        status, _ = _curl(url, "DELETE", token, 30)
    except Exception:  # noqa: BLE001
        return False
    return status in (200, 204, 404)


def kv_list_keys(token: str, acct: str, ns: str) -> list:
    """列出全部 key（自动翻页）。"""
    keys, cursor = [], None
    while True:
        suffix = "keys?limit=1000"
        if cursor:
            suffix += "&cursor=" + urllib.parse.quote(cursor, safe="")
        status, payload = _curl(kv_url(acct, ns, suffix), "GET", token, 30)
        if status != 200:
            raise RuntimeError(f"列举 KV 失败: HTTP {status}")
        data = json.loads(payload.decode("utf-8", "replace"))
        result = data.get("result", [])
        keys.extend(k["name"] for k in result)
        info = data.get("result_info", {}) or {}
        cursor = info.get("cursor")
        if not cursor or not result:
            break
    return keys


def collect_local(only_date: str = None) -> dict:
    """扫描 dist_paid/，返回 {kv_key: 绝对路径}。only_date 非空时只取该天。"""
    out = {}
    if not PAID_DIR.exists():
        return out
    for f in sorted(PAID_DIR.rglob("*")):
        if not f.is_file():
            continue
        key = f.relative_to(PAID_DIR).as_posix()
        if only_date:
            # only_date 时保留 latest/ 与 news/ 索引（它们随最新一天变化）
            if key.startswith("news/") and not key.startswith(f"news/{only_date}/"):
                if key != "news/index.html":
                    continue
            if key.startswith("latest/") and key != "latest/index.html":
                continue
        out[key] = f
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="上传付费页到 Cloudflare KV (SITE)")
    ap.add_argument("--dry-run", action="store_true", help="只列出将上传的 key，不写 KV")
    ap.add_argument("--prune", action="store_true", help="删除 KV 中已不在 dist_paid 的 key")
    ap.add_argument("--verify", action="store_true", help="只读回 KV 校验存在性，不上传")
    ap.add_argument("--date", help="只上传某个归档日（YYYYMMDD），仍会更新 latest/ 与 news/ 索引")
    args = ap.parse_args()

    load_dotenv()

    files = collect_local(args.date)
    if not files:
        print(f"❌ dist_paid/ 为空或不存在（先跑 python3 build.py）: {PAID_DIR}")
        return 1

    total_bytes = sum(p.stat().st_size for p in files.values())
    print(f"📦 待上传 {len(files)} 个文件，共 {total_bytes / 1024:.0f} KB")

    for key, path in sorted(files.items()):
        size = path.stat().st_size
        flag = "  ⚠️ 超过 20MiB" if size > MAX_VALUE_BYTES else ""
        if args.dry_run:
            print(f"   {key:44s} {size / 1024:8.1f} KB{flag}")

    if args.dry_run:
        print("(--dry-run：未写 KV)")
        return 0

    creds = api_creds()
    if not creds:
        return 1
    token, acct, ns = creds
    print(f"🔑 namespace SITE = {ns}")

    # --verify：只比大小
    if args.verify:
        bad = 0
        for key, path in sorted(files.items()):
            try:
                body = kv_get(token, acct, ns, key)
            except urllib.error.URLError as e:
                print(f"   ❌ {key}: 读取失败 {e}")
                bad += 1
                continue
            if body is None:
                print(f"   ❌ {key}: 不存在")
                bad += 1
            else:
                print(f"   ✅ {key}: {len(body) / 1024:.1f} KB")
        print(f"校验完成：{len(files) - bad}/{len(files)} 存在")
        return 1 if bad else 0

    for key, path in files.items():
        if path.stat().st_size > MAX_VALUE_BYTES:
            print(f"❌ {key} 超过 KV 单值上限 20MiB，中止")
            return 1

    ok = fail = 0
    errs = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(kv_put, token, acct, ns, key, path.read_bytes()): key
                for key, path in files.items()}
        for fut in as_completed(futs):
            key, good, err = fut.result()
            if good:
                ok += 1
                print(f"   ✅ {key} ({files[key].stat().st_size / 1024:.0f} KB)")
            else:
                fail += 1
                errs.append((key, err))
                print(f"   ❌ {key}: {err}")

    if args.prune:
        try:
            remote = kv_list_keys(token, acct, ns)
        except urllib.error.URLError as e:
            print(f"⚠️  列举 KV 失败，跳过 prune：{e}")
            remote = []
        stale = [k for k in remote if k not in files]
        if stale:
            print(f"🧹 清理 {len(stale)} 个陈旧 key：")
            for k in stale:
                print(f"   {'🗑️ ' if kv_delete(token, acct, ns, k) else '⚠️ '} {k}")
        else:
            print("🧹 无陈旧 key")

    print(f"完成：成功 {ok}，失败 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
