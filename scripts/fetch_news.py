#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外媒最新新闻抓取器 —— 本机 cron 运行，产物提交到仓库由 CI 构建发布。

设计原则：
  * 只抓"官方 news sitemap" —— 这类路径不设人机验证，稳定可用。
  * 官网正文页直连全部不可用（反爬/付费墙），仅 Bloomberg 有镜像通道可抓全文。
  * 抓取与构建分离：本脚本只产出 JSON，页面由 build.py 在 CI 里生成。

数据源（均为 robots.txt 官方声明的 sitemap）：
  Bloomberg  https://www.bloomberg.com/sitemaps/news/latest.xml
  FT         https://www.ft.com/sitemaps/news.xml
  WSJ        https://www.wsj.com/wsjsitemaps/wsj_google_news.xml
  Reuters    https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml

用法：
  python3 scripts/fetch_news.py                      # 抓当天四家标题
  python3 scripts/fetch_news.py --with-body          # 额外抓 Bloomberg 正文
  python3 scripts/fetch_news.py --sources bb,wsj     # 只抓指定源
  python3 scripts/fetch_news.py --pages 2            # Reuters 翻页数（每页 50）
  python3 scripts/fetch_news.py --skip-letters       # 过滤 FT 的 Letter 来信
  python3 scripts/fetch_news.py --date 20260907      # 指定归档日期，默认今天

产物：
  data/news/<YYYYMMDD>.json   当日数据
  data/news/index.json        归档索引（日期倒序）
"""

import argparse
import gzip
import io
import json
import re
import subprocess
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "news"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
CST = timezone(timedelta(hours=8))
NS = {
    "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "n": "http://www.google.com/schemas/sitemap-news/0.9",
}

SOURCES = {
    "bb": {
        "name": "Bloomberg",
        "home": "https://www.bloomberg.com",
        "sitemap": "https://www.bloomberg.com/sitemaps/news/latest.xml",
        "mirror": "www.envoy.cirrus.bloomberg.com",   # 仅用于抓取正文（读 __NEXT_DATA__），展示链接仍用官网
        "can_fetch_body": True,
        "note": "正文经镜像域名抓取（envoy.cirrus）；展示链接走官网 bloomberg.com",
    },
    "ft": {
        "name": "Financial Times",
        "home": "https://www.ft.com",
        "sitemap": "https://www.ft.com/sitemaps/news.xml",
        "can_fetch_body": False,
        "note": "正文受 Cloudflare 验证页拦截，暂无自动通道",
    },
    "wsj": {
        "name": "The Wall Street Journal",
        "home": "https://www.wsj.com",
        "sitemap": "https://www.wsj.com/wsjsitemaps/wsj_google_news.xml",
        "can_fetch_body": False,
        "note": "正文可经 TradingView 道琼斯通讯社转载获取（需搜索）",
        "skip_sections": ["/sports/"],   # 体育新闻不收录
    },
    "rt": {
        "name": "Reuters",
        "home": "https://www.reuters.com",
        "sitemap": "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml",
        "paged": True,
        "can_fetch_body": False,
        "note": "正文可经 CNA 等授权转载站获取（需搜索）",
        "skip_sections": ["/sports/"],   # 体育新闻不收录
    },
}


def http_get(url: str, timeout: int = 30) -> str:
    """GET 返回文本。优先 urllib，失败回退 curl（部分环境 Python 无外网权限）。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        pass
    r = subprocess.run(
        ["curl", "-sL", "--max-time", str(timeout), "-A", UA,
         "-H", "Accept-Language: en-US,en;q=0.9", url],
        capture_output=True, text=True, timeout=timeout + 15)
    if not r.stdout.strip():
        raise RuntimeError(f"抓取失败: {url}")
    return r.stdout


def cst_from_iso(s: str) -> dict:
    """ISO 时间 → 北京时间，返回 {iso, mmdd_hm}

    注意：Google News sitemap 的 publication_date 是带时区标志的 W3C 格式
    （Z / +00:00 / ±hh:mm）。不可截断掉时区，否则会被当成本地时间（主机 TZ=Asia/Shanghai）
    而少加 8 小时。无时区的裸时间按 UTC 处理（符合 Google 规范的 UTC 缺省）。
    """
    if not s:
        return {"iso": "", "mmdd_hm": ""}
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return {"iso": s, "mmdd_hm": ""}
    if dt.tzinfo is None:          # 裸时间：按 UTC 解释（不要用主机本地时区）
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(CST)
    return {"iso": dt.isoformat(), "mmdd_hm": dt.strftime("%m-%d %H:%M")}


def parse_news_sitemap(xml_text: str) -> list:
    """解析 Google News 格式 sitemap → [(iso, title, url), ...]"""
    root = ET.fromstring(xml_text)
    rows = []
    for u in root.findall("s:url", NS):
        loc = u.find("s:loc", NS)
        title = u.find("n:news/n:title", NS)
        if loc is None or title is None:
            continue
        d = u.find("n:news/n:publication_date", NS)
        t = re.sub(r"\s+", " ", (title.text or "")).strip()
        # 保留完整 W3C 串（含时区标志），交给 cst_from_iso 统一换算
        rows.append((((d.text or "").strip()) if d is not None else "", t, loc.text))
    rows.sort(reverse=True)
    return rows


def collect_texts(node, buf):
    """深度收集 Portable-Text 文档里的所有 text.value（保留 entity/link 内文本）"""
    if isinstance(node, list):
        for n in node:
            collect_texts(n, buf)
    elif isinstance(node, dict):
        if node.get("type") == "text" and "value" in node:
            buf.append(node["value"])
        for k, v in node.items():
            if isinstance(v, (list, dict)):
                collect_texts(v, buf)


def fetch_bloomberg_body(url: str) -> list:
    """Bloomberg 正文：经 envoy.cirrus 镜像域名读 __NEXT_DATA__"""
    meta = SOURCES["bb"]
    mirror = re.sub(r"^https?://(www\.)?bloomberg\.com",
                    f"https://{meta['mirror']}", url)
    try:
        html = http_get(mirror)
    except Exception:
        return []
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        story = json.loads(m.group(1))["props"]["pageProps"]["story"]
    except (json.JSONDecodeError, KeyError):
        return []

    paras = []
    for nd in story.get("body", {}).get("content", []):
        if nd.get("type") == "paragraph":
            buf = []
            collect_texts(nd, buf)
            t = "".join(buf).strip()
            if t and t != "Also read:":
                paras.append(t)
    return paras


def fetch_source(key: str, with_body: bool = False, pages: int = 1,
                 skip_letters: bool = False) -> dict:
    cfg = SOURCES[key]
    items = []

    urls = [cfg["sitemap"]]
    if cfg.get("paged") and pages > 1:
        urls += [f"{cfg['sitemap']}&from={i * 100}" for i in range(1, pages)]

    for sm_url in urls:
        try:
            rows = parse_news_sitemap(http_get(sm_url))
        except Exception as e:
            print(f"  ⚠️  {cfg['name']} sitemap 失败: {e}", file=sys.stderr)
            continue
        for iso, title, url in rows:
            if skip_letters and title.startswith("Letter:"):
                continue
            skip_secs = cfg.get("skip_sections")
            if skip_secs and any(sec in url for sec in skip_secs):
                continue
            t = cst_from_iso(iso)
            link_host = cfg.get("link_host")
            link = url
            if link_host:
                p = urllib.parse.urlparse(url)
                link = f"{link_host}{p.path}{('?' + p.query) if p.query else ''}"
            items.append({
                "title": title,
                "url": url,
                "link": link,
                "published_cst": t["iso"],
                "time": t["mmdd_hm"],
                "body": None,
            })

    # 去重（同一 URL 可能跨页出现）
    seen, uniq = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        uniq.append(it)
    items = uniq

    fetched = 0
    if with_body and cfg.get("can_fetch_body"):
        for it in items:
            it["body"] = fetch_bloomberg_body(it["url"]) or None
            if it["body"]:
                fetched += 1
        print(f"  📄 {cfg['name']} 正文抓取 {fetched}/{len(items)} 篇")

    return {
        "name": cfg["name"],
        "home": cfg["home"],
        "count": len(items),
        "body_support": cfg.get("can_fetch_body", False),
        "note": cfg.get("note", ""),
        "items": items,
    }


def main():
    ap = argparse.ArgumentParser(description="抓取外媒最新新闻标题（+Bloomberg 正文）")
    ap.add_argument("--date", default=None, help="归档日期 YYYYMMDD，默认今天")
    ap.add_argument("--sources", default="bb,ft,wsj,rt", help="逗号分隔的源 key")
    ap.add_argument("--with-body", action="store_true", help="抓 Bloomberg 正文")
    ap.add_argument("--pages", type=int, default=1, help="Reuters 翻页数（每页约 100 条）")
    ap.add_argument("--skip-letters", action="store_true", help="过滤 FT 的 Letter 来信")
    ap.add_argument("--from-file", default=None,
                    help="离线模式：从本地 XML 文件解析（调试用），需配合 --sources 单个源")
    args = ap.parse_args()

    date = args.date or datetime.now(CST).strftime("%Y%m%d")
    keys = [k.strip() for k in args.sources.split(",") if k.strip()]
    for k in keys:
        if k not in SOURCES:
            sys.exit(f"未知数据源: {k}（可选 {', '.join(SOURCES)}）")

    result = {
        "date": date,
        "generated_at": datetime.now(CST).isoformat(),
        "timezone": "Asia/Shanghai (CST, UTC+8)",
        "sources": {},
    }

    if args.from_file:
        if len(keys) != 1:
            sys.exit("--from-file 需配合单个 --sources")
        xml_text = Path(args.from_file).read_text(encoding="utf-8")
        cfg = SOURCES[keys[0]]
        rows = parse_news_sitemap(xml_text)
        items = []
        for iso, title, url in rows:
            if args.skip_letters and title.startswith("Letter:"):
                continue
            t = cst_from_iso(iso)
            items.append({"title": title, "url": url,
                          "published_cst": t["iso"], "time": t["mmdd_hm"], "body": None})
        result["sources"][keys[0]] = {
            "name": cfg["name"], "home": cfg["home"], "count": len(items),
            "body_support": cfg.get("can_fetch_body", False),
            "note": cfg.get("note", ""), "items": items,
        }
        print(f"📄 离线解析 {cfg['name']}: {len(items)} 条")
    else:
        for k in keys:
            print(f"🔍 抓取 {SOURCES[k]['name']} ...")
            result["sources"][k] = fetch_source(
                k, with_body=args.with_body, pages=args.pages,
                skip_letters=args.skip_letters)
            print(f"   ✅ {SOURCES[k]['name']}: {result['sources'][k]['count']} 条")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------ 归档分流：按发布日(CST)归档
    # 规则：每条新闻按 published_cst 的日期归到对应那天的文件；
    # 无时间的条目归到抓取日(--date/今天)。老文件的翻译/摘要/正文按 url 保留。
    KEEP = ("title_zh", "summary_zh", "body", "created")
    # 陈旧过滤：发布日早于今天-7天(CST)的条目丢弃，防 sitemap 陈旧尾巴污染归档
    stale_cut = (datetime.now(CST) - timedelta(days=7)).strftime("%Y%m%d")
    by_day = {}   # day(YYYYMMDD) -> {srckey: [items]}
    stale = 0
    for key, src in result["sources"].items():
        for it in src.get("items", []):
            pc = it.get("published_cst") or ""
            day = pc[:10].replace("-", "") if len(pc) >= 10 else ""
            if len(day) != 8 or not day.isdigit():
                day = date
            if day < stale_cut:
                stale += 1
                continue
            by_day.setdefault(day, {}).setdefault(key, []).append(it)
    if stale:
        print(f"🗑️  丢弃发布日早于 {stale_cut} 的陈旧条目 {stale} 条")

    for day, per_src in sorted(by_day.items(), reverse=True):
        out = DATA_DIR / f"{day}.json"
        merged_sources = {}
        moved_note = "" if day == date else "（跨日分流）"
        if out.exists():
            try:
                prev = json.loads(out.read_text(encoding="utf-8"))
                merged_sources = prev.get("sources", {})
            except json.JSONDecodeError:
                merged_sources = {}
        total = 0
        for key, items in per_src.items():
            cfg = SOURCES[key]
            old = merged_sources.get(key) or {"items": []}
            old_by_url = {it.get("url"): it for it in old.get("items", [])}
            for it in items:
                old_it = old_by_url.get(it.get("url"))
                if old_it:
                    for f in KEEP:
                        if old_it.get(f) and not it.get(f):
                            it[f] = old_it[f]
            # 合并：本轮新条目在前 + 老文件中发布日属本日且本轮没抓到的条目，同 url 去重
            def _pubday(x):
                pc = x.get("published_cst") or ""
                d = pc[:10].replace("-", "") if len(pc) >= 10 else ""
                return d if (len(d) == 8 and d.isdigit()) else day
            new_urls = {it.get("url") for it in items}
            seen = set()
            merged_items = []
            carry = [x for x in old.get("items", [])
                     if x.get("url") not in new_urls and _pubday(x) == day]
            for it in items + carry:
                u = it.get("url")
                if u in seen:
                    continue
                seen.add(u)
                merged_items.append(it)
            merged_items.sort(key=lambda x: x.get("time", ""), reverse=True)
            merged_sources[key] = {
                "name": cfg["name"], "home": cfg["home"],
                "count": len(merged_items),
                "body_support": cfg.get("can_fetch_body", False),
                "note": cfg.get("note", ""), "items": merged_items,
            }
            total += len(merged_items)
        day_doc = {
            "date": day,
            "generated_at": datetime.now(CST).isoformat(),
            "timezone": "Asia/Shanghai (CST, UTC+8)",
            "archive_rule": "按发布时间(CST)归档；同一天多次抓取按 url 合并去重",
            "sources": merged_sources,
        }
        out.write_text(json.dumps(day_doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"💾 归档 {day}.json：{total} 条{moved_note}（源：{', '.join(per_src)}）")

    update_index()
    return 0


def update_index():
    """重建归档索引 data/news/index.json（日期倒序）"""
    entries = []
    for f in sorted(DATA_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        total = sum(s.get("count", 0) for s in d.get("sources", {}).values())
        entries.append({
            "date": d.get("date", f.stem),
            "generated_at": d.get("generated_at", ""),
            "total": total,
            "sources": {k: v.get("count", 0) for k, v in d.get("sources", {}).items()},
        })
    entries.sort(key=lambda e: e["date"], reverse=True)
    idx = DATA_DIR / "index.json"
    idx.write_text(json.dumps({"archives": entries}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"🗂️  归档索引已更新：{len(entries)} 天")


if __name__ == "__main__":
    sys.exit(main())
