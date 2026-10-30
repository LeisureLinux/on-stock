#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻标题中英翻译 —— 调用翻译后端把标题译成中文，写入 title_zh 字段。

后端（TRANSLATE_BACKEND 环境变量切换，失败自动互降）：
  * workbuddy  （默认）workbuddy2api 本地代理（:7863，走 CodeBuddy 账号池）；
              按 WORKBUDDY_MODELS 顺序试模型：默认 hy3（免费）→
              deepseek-v4.1-flash（快、更稳，按账号积分计）。
  * deepseek  DeepSeek 官方 API，国内直连可达、译文干净；余额为 0 时回
              HTTP 402，本轮剩余标题自动改走 workbuddy。

设计：
  * 只翻译标题（摘要见 summarize_news.py）。
  * 翻译指令同时写进 user 消息：网关 prompt.mode=custom 时客户端 system 会被
    整条替换掉，只有 user 消息能保证到达模型。
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

BACKEND = os.environ.get("TRANSLATE_BACKEND", "workbuddy")
DEEPSEEK_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions")
SYSTEM_PROMPT = (
    "你是财经新闻标题翻译器。把英文新闻标题翻译成中文，要求："
    "只输出中文译文，不要解释、不要加引号、不要加序号；"
    "财经术语准确（如 Fed=美联储、Treasury=美债、yen intervention=日元干预）；"
    "保持简洁，不超过原文字数。")

# 翻译指令必须同时出现在 user 消息里：网关在 prompt.mode=custom 时会把客户端的
# system/developer 消息整条删掉、换成自有提示词（internal/prompt.Rewrite），只有
# user 消息能保证原样到达模型；passthrough 模式下两种写法都生效，所以 user 里
# 也带一份是「两种模式都对」的写法。
USER_TEMPLATE = "把下面英文新闻标题翻译成中文，只输出中文译文，不要解释：\n{}"

# workbuddy（本地 CodeBuddy 反代 :7863）模型回退链：hy3 免费，先跑它；
# 它在网关里更慢（实测 ~6s/条 vs deepseek-v4.1-flash ~2.4s），但零成本；
# 质量不够时自动回退 deepseek-v4.1-flash。
# （glm-5.1 已被上游以 code=11150 "reasoning effort not supported" 拒掉、网关转
#  503，不要再写回默认链——那是 10-29 起标题全英文的直接原因。）
WORKBUDDY_MODELS = [m.strip() for m in os.environ.get(
    "WORKBUDDY_MODELS",
    "hy3,deepseek-v4.1-flash").split(",") if m.strip()]
_legacy_model = os.environ.get("WORKBUDDY_MODEL", "").strip()
if _legacy_model:  # 兼容旧变量：指定值排到最前
    WORKBUDDY_MODELS = [_legacy_model] + [m for m in WORKBUDDY_MODELS if m != _legacy_model]

# DeepSeek 401/402/403（欠费、key 失效）后置位：本轮剩余标题直接走 workbuddy，
# 不再逐条撞同一堵墙（曾经一天刷出 2868 条 402 告警）。
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


def _translate_deepseek(title: str, timeout: int) -> str:
    global _DEEPSEEK_DOWN
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
    except urllib.error.HTTPError as e:
        if e.code in (401, 402, 403):
            _DEEPSEEK_DOWN = True
            print(f"    ⚠️  DeepSeek 不可用（HTTP {e.code}：欠费/鉴权），"
                  f"本轮剩余标题改走 workbuddy", file=sys.stderr)
        else:
            print(f"    ⚠️  翻译失败：{title[:40]}… -> {e}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"    ⚠️  翻译失败：{title[:40]}… -> {e}", file=sys.stderr)
        return ""


def _translate_workbuddy(title: str, timeout: int) -> str:
    """按 WORKBUDDY_MODELS 顺序试模型，第一个给出译文的胜出。

    每个模型失败只换下一个、不重试同一个（网关的失败多为确定性的模型/上游
    能力问题，重试同一模型只是放大等待）。
    """
    key = os.environ.get("WORKBUDDY_API_KEY") or _read_env_file().get("CODEBUDDY_API_KEY", "")
    if not key:
        return ""
    url = os.environ.get("WORKBUDDY_BASE_URL", "http://127.0.0.1:7863/v1/chat/completions")
    body = json.dumps({
        "model": "",  # 每个模型单独填
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(title)},
        ],
        "stream": False,
        "temperature": 0.3,
    })
    errs = []
    for model in WORKBUDDY_MODELS:
        payload = json.loads(body)
        payload["model"] = model
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode())
            txt = (d["choices"][0]["message"].get("content") or "").strip()
            if txt:
                return txt
            errs.append(f"{model}: 空回复")
        except Exception as e:
            errs.append(f"{model}: {e}")
    print(f"    ⚠️  翻译失败：{title[:40]}… -> " + " ｜ ".join(errs), file=sys.stderr)
    return ""


def translate_one(title: str, timeout: int = 40) -> str:
    """主后端失败即降级：workbuddy（hy3 免费）→ workbuddy 回退模型 → 官方 DeepSeek。"""
    if not title:
        return ""
    if BACKEND == "workbuddy":
        zh = _translate_workbuddy(title, timeout)
        if zh:
            return zh
        # 最后兜底：官方 DeepSeek（有余额时）。欠费后 _DEEPSEEK_DOWN 置位，不再撞墙。
        return "" if _DEEPSEEK_DOWN else _translate_deepseek(title, timeout)
    if not _DEEPSEEK_DOWN:
        zh = _translate_deepseek(title, timeout)
        if zh:
            return zh
    return _translate_workbuddy(title, timeout)


def _find_item(day: dict, url: str):
    """按 url 在 day 结构里定位 item（找不到返回 None）。"""
    if not url:
        return None
    for s in day.get("sources", {}).values():
        for it in s.get("items", []):
            if it.get("url") == url:
                return it
    return None


def process_file(path: Path, dry_run: bool = False) -> tuple:
    """翻译当日标题。

    增量写回策略：每译完一条，重读磁盘 → 把新译写入对应 item → 写盘。
    这样即使与 fetch/其他进程并发写同一文件，也只丢"这一条"，
    不会用内存旧快照把别人的更新覆盖掉（曾因此丢过 600+ 条翻译）。
    """
    day = json.loads(path.read_text(encoding="utf-8"))
    # 先收集待译 url 清单，避免边遍历边重读导致迭代器失效
    pending = []
    for s in day.get("sources", {}).values():
        for it in s.get("items", []):
            if it.get("title") and not it.get("title_zh"):
                pending.append((it.get("url", ""), it.get("title")))
    total_all = sum(len(s.get("items", [])) for s in day.get("sources", {}).values())
    if dry_run:
        return total_all, 0

    new = 0
    for url, title in pending:
        zh = translate_one(title)
        if not zh:
            time.sleep(0.3)
            continue
        new += 1
        try:
            day = json.loads(path.read_text(encoding="utf-8"))  # 重读磁盘最新状态
            target = _find_item(day, url)
            if target is not None:
                target["title_zh"] = zh
            day["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
            path.write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print(f"    ⚠️  写回失败(译文仅内存)：{e}", file=sys.stderr)
        time.sleep(0.3)  # 付费档 RPM 充足
    return total_all, new


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
