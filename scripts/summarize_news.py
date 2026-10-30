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
import urllib.error
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

# 摘要指令同时写进 user 消息（与 translate_news.py 同理：网关 prompt.mode=custom
# 会删掉客户端 system 消息，只有 user 能保证到达模型）。
USER_TEMPLATE = "把下面英文新闻正文浓缩成 1-2 句中文摘要，只输出中文摘要，不要解释：\n{}\n"

# 摘要后端：workbuddy 优先（hy3 免费）→ deepseek-v4.1-flash → 官方 DeepSeek。
WORKBUDDY_MODELS = [m.strip() for m in os.environ.get(
    "WORKBUDDY_MODELS",
    "hy3,deepseek-v4.1-flash").split(",") if m.strip()]
# 网关对长 prompt 间歇性返回空/截断，正文截到这里再送（实测 1500 字符足够写 40 字摘要）。
WORKBUDDY_BODY_CHARS = int(os.environ.get("WORKBUDDY_BODY_CHARS", "1500"))

_DEEPSEEK_DOWN = False


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


def gen_summary(body: list, timeout: int = 40) -> str:
    """workbuddy（hy3 免费）为主 → 官方 DeepSeek 为备。

    DeepSeek 欠费/鉴权失败（401/402/403）后 _DEEPSEEK_DOWN 置位，本轮不再撞墙。
    """
    global _DEEPSEEK_DOWN
    if not body:
        return ""
    text = "\n".join(body[:8])  # 取前 8 段足够摘要
    zh = _summarize_workbuddy(text, timeout)
    if zh:
        return zh
    if _DEEPSEEK_DOWN:
        return ""
    return _summarize_deepseek(text, timeout)


def _summarize_deepseek(text: str, timeout: int = 40) -> str:
    global _DEEPSEEK_DOWN
    key = os.environ.get("DEEPSEEK_API_KEY") or _read_env_file().get("DEEPSEEK_API_KEY", "")
    if not key:
        return ""
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(text)},
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
    except urllib.error.HTTPError as e:
        if e.code in (401, 402, 403):
            _DEEPSEEK_DOWN = True
            print(f"    ⚠️  DeepSeek 不可用（HTTP {e.code}：欠费/鉴权），"
                  f"本轮剩余摘要不再尝试官方后端", file=sys.stderr)
        else:
            print(f"    ⚠️  摘要失败（deepseek）-> {e}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"    ⚠️  摘要失败（deepseek）-> {e}", file=sys.stderr)
        return ""


def _summarize_workbuddy(text: str, timeout: int = 25) -> str:
    """按 WORKBUDDY_MODELS 顺序试模型；长正文先截断（网关长 prompt 不稳定）。"""
    key = os.environ.get("WORKBUDDY_API_KEY") or _read_env_file().get("CODEBUDDY_API_KEY", "")
    if not key:
        return ""
    url = os.environ.get("WORKBUDDY_BASE_URL", "http://127.0.0.1:7863/v1/chat/completions")
    text = text[:WORKBUDDY_BODY_CHARS]
    errs = []
    for model in WORKBUDDY_MODELS:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": USER_TEMPLATE.format(text)},
            ],
            "stream": False,
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode())
            zh = (d["choices"][0]["message"].get("content") or "").strip()
            if zh:
                return zh
            errs.append(f"{model}: 空回复")
        except Exception as e:
            errs.append(f"{model}: {e}")
    print("    ⚠️  摘要失败（workbuddy 全模型）-> " + " ｜ ".join(errs), file=sys.stderr)
    return ""


def _flush(path: Path, day: dict) -> dict:
    """重读磁盘→合并内存新增→写盘，返回最新 day（防并发覆盖丢数据）。"""
    try:
        fresh = json.loads(path.read_text(encoding="utf-8"))
        fresh["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        path.write_text(json.dumps(fresh, ensure_ascii=False, indent=1), encoding="utf-8")
        return fresh
    except Exception:
        return day


def process_file(path: Path, dry_run: bool = False) -> tuple:
    """BB 正文+摘要。与 translate 同样的防覆盖策略：
    每次写盘前重读磁盘最新状态，只在本条 item 上落笔。
    """
    day = json.loads(path.read_text(encoding="utf-8"))
    # 收集待处理清单（url + 待做事项），避免迭代中重读失效
    pending = []
    for s in day.get("sources", {}).values():
        if s.get("name") != "Bloomberg":
            continue
        for it in s.get("items", []):
            todo = []
            if not it.get("body"):
                todo.append("body")
            if it.get("body") and not it.get("summary_zh"):
                todo.append("summary")
            if todo:
                pending.append((it.get("url", ""), todo))
    total = sum(len(s.get("items", [])) for s in day.get("sources", {}).values()
                if s.get("name") == "Bloomberg")
    if dry_run:
        return total, 0, 0

    new_body = new_sum = 0
    for url, todo in pending:
        body = None
        if "body" in todo:
            try:
                body = fn.fetch_bloomberg_body(url)
            except Exception:
                body = None
        if body:
            new_body += 1
        time.sleep(0.3)
        summ = None
        if body or "summary" in todo:
            cur_body = body
            if not cur_body:
                # 重读磁盘取现有 body（可能已被其它进程写入）
                try:
                    disk_it = _find_url(path, url)
                    cur_body = (disk_it or {}).get("body")
                except Exception:
                    cur_body = None
            if cur_body:
                summ = gen_summary(cur_body)
                time.sleep(0.3)
        # 落盘：重读磁盘最新状态，只改本条
        try:
            day = json.loads(path.read_text(encoding="utf-8"))
            it = _find_url_in_day(day, url)
            if it is not None:
                if body and not it.get("body"):
                    it["body"] = body
                if summ and not it.get("summary_zh"):
                    it["summary_zh"] = summ
                    new_sum += 1
            day["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
            path.write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print(f"    ⚠️  写回失败：{e}", file=sys.stderr)
    return total, new_body, new_sum


def _find_url(path: Path, url: str):
    try:
        day = json.loads(path.read_text(encoding="utf-8"))
        return _find_url_in_day(day, url)
    except Exception:
        return None


def _find_url_in_day(day: dict, url: str):
    for s in day.get("sources", {}).values():
        if s.get("name") != "Bloomberg":
            continue
        for it in s.get("items", []):
            if it.get("url") == url:
                return it
    return None


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
