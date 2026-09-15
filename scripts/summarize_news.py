#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bloomberg 正文抓取 + 中文摘要生成。

流程：
  * 对 BB 源每条：若 item 无 body，则从 envoy.cirrus 镜像域名抓取 Bloomberg 正文；
  * 用 DeepSeek 把正文浓缩成 1-2 句中文摘要，写入 summary_zh；
  * 按 url 增量写回，已抓/已摘要不重做。

只处理 BB（其镜像站可直连抓正文）；WSJ/FT/Reuters 正文在 Paywall 后暂不可达，跳过。

用法：
  python3 scripts/summarize_news.py --date 20260915   # 处理当天
  python3 scripts/summarize_news.py --all               # 处理全部归档
  python3 scripts/summarize_news.py --dry-run           # 只统计
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "news"
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_news as fn

SUMMARY_PROMPT = (
    "你是财经新闻摘要器。把下面英文新闻正文浓缩成 1-2 句中文摘要，"
    "要求：只输出中文摘要，不要解释、不要加引号、不要加序号；"
    "突出数字、主体、事件结果；约 40 字以内。")

DEEPSEEK_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions")


def _read_env_file() -> dict:
    out = {}
    p = Path.home() / ".codex" / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip("'\"")
    return out


def gen_summary(body: list, timeout: int = 25) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY") or _read_env_file().get("DEEPSEEK_API_KEY", "")
    if not key or not body:
        return ""
    text = "\n".join(body[:8])  # 取前 8 段足够摘要
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_URL, data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    ⚠️  摘要失败 -> {e}", file=sys.stderr)
        return ""


def process_file(path: Path, dry_run: bool = False) -> tuple:
    day = json.loads(path.read_text(encoding="utf-8"))
    total = new_body = new_sum = 0
    for s in day.get("sources", {}).values():
        if s.get("name") != "Bloomberg":
            continue
        for it in s.get("items", []):
            total += 1
            # 1) 抓正文（若无）
            if not it.get("body"):
                if dry_run:
                    continue
                try:
                    body = fn.fetch_bloomberg_body(it.get("url", ""))
                except Exception:
                    body = None
                if body:
                    it["body"] = body
                    new_body += 1
                    day["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
                    path.write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
                time.sleep(0.3)
            # 2) 生成摘要（若有正文且无摘要）
            if it.get("body") and not it.get("summary_zh"):
                if dry_run:
                    continue
                summ = gen_summary(it["body"])
                if summ:
                    it["summary_zh"] = summ
                    new_sum += 1
                    day["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
                    path.write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
                time.sleep(0.3)
    return total, new_body, new_sum


def main():
    ap = argparse.ArgumentParser(description="Bloomberg 正文抓取 + 中文摘要")
    ap.add_argument("--date", default=None, help="YYYYMMDD，默认今天")
    ap.add_argument("--all", action="store_true", help="处理 data/news 下全部")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不调用")
    args = ap.parse_args()

    if args.all:
        files = sorted(DATA_DIR.glob("*.json"))
    else:
        date = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
        files = [DATA_DIR / f"{date}.json"]
        if not files[0].exists():
            sys.exit(f"无数据文件：{files[0]}")

    print(f"模式：Bloomberg 正文+摘要 ｜ dry_run={args.dry_run}")
    tot = nb = ns = 0
    for f in files:
        if f.name == "index.json":
            continue
        t, b, s = process_file(f, args.dry_run)
        tot += t; nb += b; ns += s
        print(f"  {f.name}: BB {t} 条，新抓正文 {b}，新增摘要 {s}")
    print(f"\n合计：BB {tot} 条，新抓正文 {nb}，新增摘要 {ns}" +
          ("（dry-run，未写入）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
