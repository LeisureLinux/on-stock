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
import os
import re
import subprocess
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape as html_unescape
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
        # 2026-11-14: wpad-02 的透明代理出口访问 www.ft.com 时 TLS Client Hello
        # 被 RST（curl 35），但同一台机器 sing-box 的本地 socks 入站可拿到完整
        # 官方 sitemap（实测 200 / 177 KB / 321 条）。只在直连失败时作为最后一跳，
        # 不改环境变量、不影响其他源。设 NEWS_FALLBACK_SOCKS=none 可整体关闭。
        "fallback_socks": True,
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
        # 官方 sitemap 自 2026-11 起被 DataDome 挡成 401（"Please enable JS
        # and disable any ad blocker"），直连 / socks / 换出口 IP 都无效。
        # 备用通道：Google News RSS 拿标题+精确时间，Bing News RSS 的 url= 参数
        # 解出真实 reuters.com 链接。代价是数量与时间精度不如官方 sitemap，
        # 少量条目链接会落到 news.google.com 跳转页，item 上打 via 标记。
        # 设 NEWS_RT_FALLBACK=0 可退回「只认官方 sitemap」。
        "note": "官方 sitemap 被 DataDome 拦截；标题经 Google/Bing News RSS 兜底",
        "alt_feeds": [
            {"kind": "bing",
             "url": "https://www.bing.com/news/search?q=site%3Areuters.com&format=rss"},
            {"kind": "gnews",
             "url": ("https://news.google.com/rss/search?q=site%3Areuters.com"
                     "%20when%3A1d&hl=en-US&gl=US&ceid=US%3Aen")},
        ],
        "skip_sections": ["/sports/"],   # 体育新闻不收录
    },
}


# ---- 出口 ---------------------------------------------------------------
# 默认不设置任何显式代理：wpad 上非 root 进程的流量由 sing-box 透明代理接管
# （nft output-tproxy 全量标记 → tproxy → sing-box → urltest: hy2 主 / mieru 备）。
#
# 唯一例外：FT 的官方 sitemap 在这条透明路径上 TLS 被 RST，而同一台机器
# sing-box 的**本地 socks 入站**可用。注意这不是已停用的 wpad.lan:8888，
# 也不写 http_proxy 环境变量；只是「单源、直连失败后的最后一跳」，
# 可用 NEWS_FALLBACK_SOCKS=none 彻底关掉。
FALLBACK_SOCKS = os.environ.get(
    "NEWS_FALLBACK_SOCKS", "socks5h://127.0.0.1:1080").strip()
# 本地 socks 入站偶发一次空响应（实测 4 次里 1 次），重试一次即可。
FALLBACK_TRIES = max(1, int(os.environ.get("NEWS_FALLBACK_TRIES", "2") or 2))

# Reuters 兜底开关：默认开（用户希望恢复 RT 标题），可显式关。
RT_FALLBACK = os.environ.get("NEWS_RT_FALLBACK", "1").strip().lower() not in (
    "0", "false", "no", "none", "")


def _fetch_curl(url: str, timeout: int, socks: str = "") -> str:
    """用 curl 抓一次。socks 为空走系统默认路由 / 透明代理。"""
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", UA,
           "-H", "Accept-Language: en-US,en;q=0.9"]
    if socks:
        cmd += ["--socks5-hostname", socks.split("://", 1)[-1]]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout + 15)
    if not r.stdout.strip():
        raise RuntimeError(f"抓取失败: {url}" + (f" (via {socks})" if socks else ""))
    return r.stdout


def http_get(url: str, timeout: int = 30, allow_fallback: bool = False) -> str:
    """GET 返回文本。默认直连；仅显式允许的源在直连失败时回退本地 socks。"""
    try:
        return _fetch_curl(url, timeout)
    except Exception as e:
        usable = FALLBACK_SOCKS and FALLBACK_SOCKS.lower() != "none"
        if not (allow_fallback and usable):
            raise
        print(f"  ↪️  直连失败，改走本机 sing-box socks 入站: {e}", file=sys.stderr)
        import time as _time
        last = None
        for attempt in range(1, FALLBACK_TRIES + 1):
            try:
                return _fetch_curl(url, timeout, socks=FALLBACK_SOCKS)
            except Exception as fe:
                last = fe
                print(f"  ↪️  socks 第 {attempt}/{FALLBACK_TRIES} 次失败: {fe}",
                      file=sys.stderr)
                _time.sleep(1)
        raise last


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
    """解析 Google News 格式 sitemap → [(iso, title, url), ...]

    注意：Reuters 官方 sitemap 被 DataDome 拦成 401 时返回的是一段 HTML
    （"Please enable JS and disable any ad blocker"）。ET 能解析它，
    但 findall('s:url') 只会得到空列表 —— 表现为静默的「0 条」。
    这里显式校验根节点，让上层能识别失败并启用备用通道。
    """
    root = ET.fromstring(xml_text)
    if not (root.tag.endswith("urlset") or root.tag.endswith("sitemapindex")):
        raise RuntimeError(f"非 news sitemap XML（疑似反爬/错误页，根节点 <{root.tag}>）")
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


# ---- 备用通道：RSS 标题（目前只用于 Reuters） ---------------------------------
# 官方 sitemap 挂掉时，至少保住「今天发生了什么」；不追求与官方源等量等精度。
ALT_MAX_ITEMS = 60


def _alt_norm_title(t: str) -> str:
    """标题归一化，用于 Bing/GNews 同一条新闻配对。"""
    t = html_unescape(t or "").lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", t).strip()


def _strip_source_suffix(title: str, source: str) -> str:
    """Google News 标题形如 'xxx - Reuters'，去掉尾部的来源名。"""
    title = re.sub(r"\s+", " ", html_unescape(title or "")).strip()
    pat = re.compile(r"\s+[-–—]\s+" + re.escape(source) + r"\s*$", re.I)
    return pat.sub("", title).strip()


def _cst_from_any(s: str) -> dict:
    """RSS pubDate(RFC 822) 或 sitemap W3C 时间 → 北京时间 {iso, mmdd_hm}。"""
    s = (s or "").strip()
    if not s:
        return {"iso": "", "mmdd_hm": ""}
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(CST)
        return {"iso": dt.isoformat(), "mmdd_hm": dt.strftime("%m-%d %H:%M")}
    except (TypeError, ValueError, OverflowError):
        return cst_from_iso(s)


def parse_rss_feed(xml_text: str, kind: str, source_name: str,
                   expect_host: str = "") -> list:
    """解析 Bing News / Google News 的 RSS → [item dict, ...]

    Bing 的 <link> 是 apiclick 跳转页，真实原文 URL 藏在 query 的 url= 参数里；
    Google News 的 <link> 是 news.google.com/rss/articles/... 跳转页，
    新版 base64 里已不含原文 URL，只能保留跳转链接（item 上打 via 标记）。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise RuntimeError(f"RSS 解析失败: {e}")
    items = []
    for el in root.iter():
        if el.tag.split("}")[-1] != "item":
            continue
        title = (el.findtext("title") or "").strip()
        link = (el.findtext("link") or "").strip()
        pub = (el.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        via = kind
        if kind == "bing":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
            real = (q.get("url") or [""])[0]
            if not real.startswith("http"):
                continue
            # Bing 会混入 markets.ft.com / 其他站的结果，只留目标站域名
            host = urllib.parse.urlparse(real).netloc.lower()
            if expect_host and expect_host not in host:
                continue
            link, url = real, real
        else:
            title = _strip_source_suffix(title, source_name)
            url = link
        t = _cst_from_any(pub)
        items.append({
            "title": re.sub(r"\s+", " ", title).strip(),
            "url": url,
            "link": link,
            "published_cst": t["iso"],
            "time": t["mmdd_hm"],
            "body": None,
            "via": via,
        })
    return items


def fetch_alt_source(key: str) -> list:
    """抓备用 RSS，Bing 的真实链接优先；Google News 补精确时间与更多标题。"""
    cfg = SOURCES[key]
    bing, gnews = [], []
    for feed in cfg.get("alt_feeds", []):
        try:
            text = http_get(feed["url"], 25, allow_fallback=True)
            rows = parse_rss_feed(
                text, feed["kind"], cfg["name"],
                expect_host=urllib.parse.urlparse(cfg["home"]).netloc.lower().removeprefix("www."))
        except Exception as e:
            print(f"  ⚠️  {cfg['name']} 备用 {feed['kind']} 失败: {e}", file=sys.stderr)
            continue
        (bing if feed["kind"] == "bing" else gnews).extend(rows)
        print(f"  ↪️  {cfg['name']} {feed['kind']} 备用通道: {len(rows)} 条")

    by_url, by_title = {}, {}
    for it in bing:                       # 先把能解出原文链接的放进去
        if it["url"] in by_url:
            continue
        by_url[it["url"]] = it
        by_title.setdefault(_alt_norm_title(it["title"]), it)
    for it in gnews:
        norm = _alt_norm_title(it["title"])
        hit = by_title.get(norm)
        if hit is not None:               # 同一条：用 GNews 的精确发布时间补 Bing
            hit["published_cst"] = it["published_cst"] or hit["published_cst"]
            hit["time"] = it["time"] or hit["time"]
            hit["via"] = "gnews+bing"
            continue
        if it["url"] in by_url:
            continue
        by_url[it["url"]] = it
        by_title[norm] = it
    items = sorted(by_url.values(),
                   key=lambda x: x.get("published_cst") or "", reverse=True)
    return items[:ALT_MAX_ITEMS]


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
            # FT 直连被 RST 时，http_get 内部自动改走本机 sing-box socks 入站；
            # 其他源完全不碰代理设置。
            rows = parse_news_sitemap(
                http_get(sm_url, allow_fallback=bool(cfg.get("fallback_socks"))))
        except Exception as e:
            print(f"  ⚠️  {cfg['name']} sitemap 失败: {e}", file=sys.stderr)
            print("      (默认透明代理；FT 会再试本机 sing-box socks 入站)", file=sys.stderr)
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

    # 官方 sitemap 抓不到条目时，启用聚合站备用通道（目前仅 Reuters）。
    # 只在「空」时启用：一旦 DataDome 解除，自动恢复成官方全量 sitemap。
    if not items and cfg.get("alt_feeds") and RT_FALLBACK:
        print(f"  ⚠️  {cfg['name']} 官方源 0 条（DataDome?），启用备用 RSS",
              file=sys.stderr)
        items = fetch_alt_source(key)
        if items:
            print(f"  ↪️  {cfg['name']} 备用合计 {len(items)} 条", file=sys.stderr)

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
            # cst_from_iso 已把 publication_date(UTC) 正确换算为北京时间；
            # 写入该标记使 scripts/migrate_news_timezone.py 跳过本文件，
            # 避免其把已正确的时间再次 +8h（它按 time_basis 含 "corrected" 判断）。
            "time_basis": "publication_date (UTC) 已换算为北京时间 —— corrected",
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
