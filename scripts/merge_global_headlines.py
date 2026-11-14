#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 global_headlines 的「每站 8 条」头条并入外媒速览归档（网页可见）。

背景
----
wpad-02 每天 06:00 的 cron:

    cd ~/.openclaw/workspace/skills/qiaomu-notebooklm/scripts \
      && /usr/bin/python3 global_headlines_daily.py run

会先跑 daily_headlines.py，把结果写到
`/tmp/daily_headlines_YYYYMMDD.json`：31 个站点 × 每站最多 8 条 =
设计上限 248 条。今天实际 18 站成功 / 144 条（每个成功站点正好 8 条）。

「8 条」不是抓不到更多，而是 `daily_headlines.py` 里写死的：
  * `fetch_rss()`   `if len(results) >= 10: break`  → RSS 最多取 10 条
  * `extract_headlines()`  `return headlines[:20]`  → HTML 兜底最多 20 条
  * `fetch_site()`   `items[:8]` / `headlines[:8]`   → **每站最终只留 8 条**
  * `generate_json()` `headlines[:8]`               → 再截一次

所以它是「站点头条精选」，不是全量新闻流；`SITES` 里共配了 31 站，
失败的站（📭/🔒/⚠️）一条都没有。日志里的「128/128 标题已为中文」
是 LLM 校验报告里的链接数，不是抓取条数。

本脚本做什么
------------
只读消费上面那份 JSON（**不重跑抓取、不调 LLM、不发邮件/企微**），
把可用的英文/中文媒体标题按站点合并进 `data/news/<date>.json` 的
`sources["gh"]`，格式与 fetch_news.py 完全一致，于是自动进入现有的
dedupe → translate → summarize → build → publish_paid 链路。

限制
----
* gh 条目只在**网页归档**里可见；`news_builder.build_paid_rss()` 明确
  排除它，付费 RSS（四大财经媒体订阅）保持原有定位不变。
* 中文媒体（BBC中文 / DW / 法广 / 纽约时报中文网 / 财新国际）没有英文
  原标题需求，默认跳过；可用 --include-cn 打开。
* JSON 里没有 pubDate（daily_headlines.py 只存 title+url），时间用
  归档日 00:00 CST 占位，item 上打 `time_approx: True` / `via: global_headlines`。
* 按 (title,url) 增量合并，可每轮重复执行，不会堆重复条目。

用法
----
  python3 scripts/merge_global_headlines.py --date 20261114
  python3 scripts/merge_global_headlines.py --dry-run
  GLOBAL_HEADLINES_JSON=/var/tmp/xxx.json python3 scripts/merge_global_headlines.py
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "news"
CST = timezone(timedelta(hours=8))

DEFAULT_JSON = "/tmp/daily_headlines_{date}.json"
SRC_KEY = "gh"
SRC_NAME = "全球头条补充"
SRC_HOME = "https://stock.freelamp.com"

# 中文媒体默认不收：它们的标题本就是中文，送进英译中模型没有意义；
# 也与 global_headlines_daily.py 的 EXCLUDED_SITES 大体对齐（这里额外
# 排除了纽约时报中文网 / 财新国际）。可用 --include-cn 打开。
CN_SITES = {"BBC中文", "DW德国之声", "法广 RFI", "法广RFI",
            "纽约时报中文网", "财新国际"}
# 和四家官方源重复的，交给 fetch_news.py 的官方 sitemap，避免同一条两版
DUPLICATE_SITES = {"Bloomberg", "Reuters"}

# 明显的栏目/导航页链接（daily_headlines.py 已经过滤过一轮，这里再兜底）
SKIP_TITLE = re.compile(
    r"^(subscribe|sign up|log in|privacy|cookie|newsletter|homepage|"
    r"latest|more from|trending|advertisement)", re.I)


def _clean_title(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip()).strip()


def _site_key(name: str) -> str:
    """站点名 → 稳定短 key（只用于展示溯源，不改变 gh 源分组）。"""
    k = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return k[:32] or "site"


def load_global(path: Path, include_cn: bool = False) -> list:
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for cat, payload in (doc.get("categories") or {}).items():
        for site in (payload.get("sites") or []):
            name = (site.get("name") or "").strip()
            status = (site.get("status") or "").strip()
            if not name or (status and not status.startswith("✅")):
                continue           # 📭 / 🔒 / ⚠️ / ⏰ 都没抓到
            if name in DUPLICATE_SITES:
                continue
            if not include_cn and name in CN_SITES:
                continue
            key = _site_key(name)
            for hl in (site.get("headlines") or []):
                title = _clean_title(hl.get("title"))
                url = (hl.get("url") or "").strip()
                if not title or not url or not url.startswith("http"):
                    continue
                if len(title) < 12 or SKIP_TITLE.match(title):
                    continue
                out.append({
                    "title": title,
                    "url": url,
                    "link": url,
                    "site": name,
                    "site_key": key,
                    "category": cat,
                })
    return out


def merge_day(date: str, rows: list, dry_run: bool = False) -> tuple:
    path = DATA_DIR / f"{date}.json"
    if not path.exists():
        # fetch_news.py 先跑；没有归档文件时本轮直接跳过，不凭空造一天
        return 0, 0, 0, f"无 {path.name}，跳过"
    day = json.loads(path.read_text(encoding="utf-8"))
    sources = day.setdefault("sources", {})
    gh = sources.setdefault(SRC_KEY, {
        "name": SRC_NAME, "home": SRC_HOME, "count": 0,
        "body_support": False,
        "note": "来自 global_headlines_daily.py 的站点头条精选（每站最多 8 条）",
        "items": [],
    })
    items = gh.setdefault("items", [])
    seen = {(it.get("title"), it.get("url")) for it in items}
    seen_urls = {it.get("url") for it in items}
    # 与四家官方源同一 url 的条目也不重复收
    for k, s in sources.items():
        if k != SRC_KEY:
            seen_urls.update(it.get("url") for it in (s.get("items") or []))

    pub = f"{date[:4]}-{date[4:6]}-{date[6:]}T00:00:00+08:00"
    added = 0
    for r in rows:
        key = (r["title"], r["url"])
        if key in seen or r["url"] in seen_urls:
            continue
        seen.add(key)
        seen_urls.add(r["url"])
        item = {
            "title": r["title"],
            "url": r["url"],
            "link": r["link"],
            "published_cst": pub,
            "time": f"{date[4:6]}-{date[6:]} 00:00",
            "body": None,
            "via": "global_headlines",
            "time_approx": True,
            "site": r["site"],
            "site_key": r["site_key"],
            "category": r["category"],
        }
        items.append(item)
        added += 1
    gh["count"] = len(items)
    if not dry_run and added:
        day["generated_at"] = datetime.now(CST).isoformat()
        path.write_text(json.dumps(day, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return len(rows), added, gh["count"], ""


def main():
    ap = argparse.ArgumentParser(description="并入 global_headlines 站点头条")
    ap.add_argument("--date", default=None, help="YYYYMMDD，默认今天(北京时间)")
    ap.add_argument("--json", default=None, help="手工指定 daily_headlines JSON")
    ap.add_argument("--include-cn", action="store_true", help="也收中文媒体站点")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写盘")
    args = ap.parse_args()

    date = args.date or datetime.now(CST).strftime("%Y%m%d")
    jp = Path(args.json) if args.json else Path(
        os.environ.get("GLOBAL_HEADLINES_JSON", DEFAULT_JSON.format(date=date)))
    if not jp.exists():
        print(f"ℹ️  没有 {jp}（global_headlines cron 还没跑 / 已清理），跳过整合")
        return 0

    rows = load_global(jp, include_cn=args.include_cn)
    sites = len({r["site_key"] for r in rows})
    total, added, kept, note = merge_day(date, rows, args.dry_run)
    print(f"🌍 global_headlines: {jp.name} → {total} 条 / {sites} 站；"
          f"本轮新增 {added} 条，gh 源合计 {kept} 条"
          + ("（dry-run，未写盘）" if args.dry_run else "")
          + (f"；{note}" if note else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
