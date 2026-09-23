#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性迁移：修正历史归档里被错误标注的发布时间（漏加 8 小时）。

背景（见 scripts/fetch_news.py 的修复说明）：
  旧版 parse_news_sitemap 用 [:19] 截断了 publication_date 的时区标志（Z / +00:00），
  随后 cst_from_iso 把裸时间当成本机本地时间（Asia/Shanghai）解释，导致 UTC 墙钟被
  原样贴上 +08:00 标签 —— 于是每条时间都少了 8 小时，且按发布日归档时日期也可能错位。

本脚本对 data/news/*.json 做一次性修正：
  1) 每条 published_cst / time 统一 +8 小时（四源 publication_date 均为 UTC）；
  2) 按修正后的发布日(CST)重新分流归档文件；
  3) 同 (日, 源) 内按 url 去重，保留信息最全的一条（标题译文/摘要/正文优先）；
  4) 重建 data/news/index.json。

幂等：带已修正标记（time_basis 含 "corrected"）的文件会被跳过，可安全重复执行。

用法：
  python3 scripts/migrate_news_timezone.py --dry-run   # 只报告，不改文件
  python3 scripts/migrate_news_timezone.py --yes       # 实际写入（需显式确认）

⚠️ 这是一次性迁移脚本（已于 2026-09-23 执行完毕）。修好 fetch_news.py 后新抓的数据
本就是正确时间，且不带本脚本的标记；若对它们误跑本脚本会被重复 +8h。因此写入必须
显式传 --yes，且重复执行已迁移文件会自动跳过。
"""

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "news"
CST = timezone(timedelta(hours=8))
MARKER = "corrected"
KEEP = ("title_zh", "summary_zh", "body", "created")


def _fix_time(item: dict, day_fallback: str) -> str:
    """把条目的时间 +8h，返回新的 'YYYY-MM-DD' 归档日。"""
    pc = item.get("published_cst") or ""
    t = item.get("time") or ""
    new_day = day_fallback
    if len(pc) >= 19:
        try:
            dt = datetime.fromisoformat(pc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CST)
            dt = dt + timedelta(hours=8)
            item["published_cst"] = dt.isoformat()
            item["time"] = dt.strftime("%m-%d %H:%M")
            new_day = dt.strftime("%Y%m%d")
        except ValueError:
            pass
    elif len(t) == 11:   # 只有 mm-dd HH:MM 的兜底
        try:
            base = datetime.strptime(day_fallback + " " + t, "%Y%m%d %m-%d %H:%M")
            dt = (base + timedelta(hours=8)).replace(tzinfo=CST)
            item["published_cst"] = dt.isoformat()
            item["time"] = dt.strftime("%m-%d %H:%M")
            new_day = dt.strftime("%Y%m%d")
        except ValueError:
            pass
    return new_day


def _richness(it: dict):
    return (
        1 if it.get("title_zh") else 0,
        1 if it.get("summary_zh") else 0,
        1 if it.get("body") else 0,
        len(it.get("published_cst") or ""),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告，不落盘")
    ap.add_argument("--yes", action="store_true",
                    help="确认执行写入（一次性迁移，防误跑重复 +8h）")
    args = ap.parse_args()

    files = sorted(p for p in DATA_DIR.glob("*.json") if p.name != "index.json")
    if not files:
        print("没有归档文件，退出")
        return 0

    # 汇总所有条目，按修正后的 (日, 源) 重组
    buckets = {}          # day -> src -> {url: item}
    src_meta = {}         # src -> 源级元数据（name/home/note/...）
    gen_at = {}           # day -> 原始 generated_at
    already = 0
    moved = 0
    total = 0
    processed = []        # 实际需要修正、待删除重写的文件

    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        if MARKER in (doc.get("time_basis") or ""):
            already += 1
            continue
        processed.append(f)
        fallback_day = doc.get("date") or f.stem
        gen = doc.get("generated_at") or ""
        gen_at.setdefault(fallback_day, gen)
        for key, src in (doc.get("sources") or {}).items():
            src_meta[key] = {k: v for k, v in src.items() if k != "items"}
            for it in src.get("items", []):
                total += 1
                old_day = fallback_day
                new_day = _fix_time(it, fallback_day)
                if new_day != old_day:
                    moved += 1
                gen_at.setdefault(new_day, gen)
                slot = buckets.setdefault(new_day, {}).setdefault(key, {})
                u = it.get("url") or it.get("link") or it.get("title")
                prev = slot.get(u)
                if prev is None or _richness(it) > _richness(prev):
                    slot[u] = it

    print(f"扫描 {len(files)} 个文件，{total} 条；"
          f"跨日重分流 {moved} 条；已修正跳过 {already} 个文件")
    if not processed:
        print("没有需要修正的文件（均已处理），未做任何改动。")
        return 0
    if args.dry_run:
        print("\n[dry-run] 重分流后的归档：")
        for day in sorted(buckets, reverse=True):
            per = buckets[day]
            n = sum(len(v) for v in per.values())
            print(f"  {day}: {n} 条（{', '.join(f'{k}={len(v)}' for k, v in per.items())}）")
        return 0
    if not args.yes:
        print("\n这是写入操作，需显式确认：加 --yes 才执行（先跑 --dry-run 预览）。")
        return 1

    # 备份一次，便于回滚
    backup = DATA_DIR.with_name("news.bak_before_tzfix")
    if not backup.exists():
        shutil.copytree(DATA_DIR, backup)
        print(f"已备份原目录 → {backup}")

    # 删除除 index.json 外的旧归档，重写
    # 删除需要重写的旧归档（仅限本轮实际处理的文件；index.json 单独重建）
    for f in processed:
        f.unlink()

    now = datetime.now(CST).isoformat()
    for day, per_src in buckets.items():
        merged = {}
        for key, by_url in per_src.items():
            items = list(by_url.values())
            items.sort(key=lambda x: x.get("time", ""), reverse=True)
            meta = dict(src_meta.get(key, {}))
            meta["count"] = len(items)
            meta["items"] = items
            merged[key] = meta
        doc = {
            "date": day,
            "generated_at": gen_at.get(day) or now,
            "timezone": "Asia/Shanghai (CST, UTC+8)",
            "time_basis": "publication_date (UTC) 已换算为北京时间 —— corrected",
            "archive_rule": "按发布时间(CST)归档；同一天多次抓取按 url 合并去重",
            "sources": merged,
        }
        out = DATA_DIR / f"{day}.json"
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        n = sum(s["count"] for s in merged.values())
        print(f"💾 {day}.json：{n} 条")

    # 重建索引（与 fetch_news.update_index 逻辑一致）
    entries = []
    for f in sorted(DATA_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        entries.append({
            "date": d.get("date", f.stem),
            "generated_at": d.get("generated_at", ""),
            "total": sum(s.get("count", 0) for s in d.get("sources", {}).values()),
            "sources": {k: v.get("count", 0) for k, v in d.get("sources", {}).items()},
        })
    entries.sort(key=lambda e: e["date"], reverse=True)
    (DATA_DIR / "index.json").write_text(
        json.dumps({"archives": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("✅ 已重建 index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
