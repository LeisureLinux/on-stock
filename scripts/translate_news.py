#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻标题中英翻译 —— 调用翻译后端把标题译成中文，写入 title_zh 字段。

后端（TRANSLATE_BACKEND 环境变量切换）：
  * deepseek  （默认）DeepSeek 官方 API，国内直连可达、免费额度充足、译文干净。
  * workbuddy  workbuddy2api 本地代理（glm-5.1）；其账号池混编程模型，翻译质量
              随机，仅作备用。

设计：
  * 只翻译标题（摘要暂不做，WSJ/FT/Reuters 正文在 Paywall 后抓不到）。
  * 结果写入每条 item 的 title_zh 字段；按 url 去重缓存，已译不重译。
  * 翻译失败/超时不影响主流程，title_zh 留空（页面 fallback 显示原文）。

用法：
  python3 scripts/translate_news.py                 # 翻译当天（默认今天）
  python3 scripts/translate_news.py --date 20260914 # 指定归档
  python3 scripts/translate_news.py --all            # 翻译 data/news 下全部
  python3 scripts/translate_news.py --dry-run        # 只统计待译条数，不调用 API
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "news"

BACKEND = os.environ.get("TRANSLATE_BACKEND", "deepseek")
DEEPSEEK_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions")
SYSTEM_PROMPT = (
    "你是财经新闻标题翻译器。把英文新闻标题翻译成中文，要求："
    "只输出中文译文，不要解释、不要加引号、不要加序号；"
    "财经术语准确（如 Fed=美联储、Treasury=美债、yen intervention=日元干预）；"
    "保持简洁，不超过原文字数。")


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


def _translate_deepseek(title: str, timeout: int) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY") or _read_env_file().get("DEEPSEEK_API_KEY", "")
    if not key:
        return ""
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": title},
        ],
        "stream": False,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    ⚠️  翻译失败：{title[:40]}… -> {e}", file=sys.stderr)
        return ""


def _translate_workbuddy(title: str, timeout: int) -> str:
    key = os.environ.get("WORKBUDDY_API_KEY") or _read_env_file().get("CODEBUDDY_API_KEY", "")
    if not key:
        return ""
    url = os.environ.get("WORKBUDDY_BASE_URL", "http://127.0.0.1:7863/v1/chat/completions")
    model = os.environ.get("WORKBUDDY_MODEL", "glm-5.1")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": title},
        ],
        "stream": False,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    ⚠️  翻译失败：{title[:40]}… -> {e}", file=sys.stderr)
        return ""


def translate_one(title: str, timeout: int = 25) -> str:
    if not title:
        return ""
    if BACKEND == "workbuddy":
        return _translate_workbuddy(title, timeout)
    return _translate_deepseek(title, timeout)


def process_file(path: Path, dry_run: bool = False) -> tuple:
    day = json.loads(path.read_text(encoding="utf-8"))
    total = new = 0
    for s in day.get("sources", {}).values():
        for it in s.get("items", []):
            title = it.get("title", "")
            if not title:
                continue
            total += 1
            if it.get("title_zh"):
                continue
            if dry_run:
                continue
            zh = translate_one(title)
            if zh:
                it["title_zh"] = zh
                new += 1
                # 每条增量写回，避免中途崩溃丢失进度
                day["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
                path.write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(0.3)  # 付费档 RPM 充足
    return total, new


def main():
    ap = argparse.ArgumentParser(description="翻译新闻标题")
    ap.add_argument("--date", default=None, help="YYYYMMDD，默认今天")
    ap.add_argument("--all", action="store_true", help="翻译 data/news 下全部")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不调用 API")
    args = ap.parse_args()

    if args.all:
        files = sorted(DATA_DIR.glob("*.json"))
    else:
        date = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
        files = [DATA_DIR / f"{date}.json"]
        if not files[0].exists():
            sys.exit(f"无数据文件：{files[0]}")

    print(f"后端：{BACKEND} ｜ dry_run={args.dry_run}")
    tot_total = tot_new = 0
    for f in files:
        if f.name == "index.json":
            continue
        t, n = process_file(f, args.dry_run)
        tot_total += t
        tot_new += n
        print(f"  {f.name}: 共 {t} 条，新增翻译 {n} 条")
    print(f"\n合计：{tot_total} 条，新增 {tot_new} 条" +
          ("（dry-run，未写入）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
