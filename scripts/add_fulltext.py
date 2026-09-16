#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全文收录工具：把手工导出的 markdown 正文，挂到对应新闻条目上。

流程：
  1. 从 ~/studies/Linux/AI/ (或 --src 指定目录) 读取 export_*.md 文件
  2. 按文件名/正文标题模糊匹配 data/news 里的新闻条目（按 url slug / title）
  3. 用 DeepSeek 分段翻译全文为中文（缓存，已译段落不重译）
  4. 生成 data/fulltext/<YYYYMMDD>/<slug>.json（源文+译文+元数据）
  5. build.py 读 data/fulltext 生成 docs/fulltext/<YYYYMMDD>/<slug>/ 排版页
     新闻列表对应条目加「全文」小图标链接（news_builder）

用法：
  python3 scripts/add_fulltext.py                     # 扫描默认目录，处理所有未入库的 md
  python3 scripts/add_fulltext.py --file <md路径>     # 处理单个文件
  python3 scripts/add_fulltext.py --list              # 只显示匹配结果，不翻译
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "news"
FT_DIR = ROOT / "data" / "fulltext"          # 译好的全文 JSON
DEFAULT_SRC = Path.home() / "studies" / "Linux" / "AI"

CST = timezone(timedelta(hours=8))
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

TRANSLATE_PROMPT = (
    "你是财经新闻翻译器。把用户提供的英文新闻正文逐段翻译成简体中文。要求：\n"
    "1. 只输出译文正文（多个自然段，用空行分隔），不要解释、不要加序号、不要输出原文；\n"
    "2. 财经术语准确（Fed=美联储、Treasury=美债、grid=电网、power purchase agreement=购电协议等）；\n"
    "3. 专有名词首次出现可括注英文（如 国际能源署（IEA）），公司/人名保留常用译名；\n"
    "4. 语句通顺润色，符合中文财经媒体表达习惯，但不得增删事实、数字；\n"
    "5. 数字、单位、百分比必须与原文一致。")


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


def deepseek_translate(text: str, timeout: int = 120) -> str:
    key = _read_env_file().get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": TRANSLATE_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode())
            return d["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"翻译失败: {last}")


def parse_md(md_path: Path) -> dict:
    """从导出的 md 里提取 (标题, 来源url, 正文段落列表)"""
    text = md_path.read_text(encoding="utf-8")
    # 标题: 第一个 # 行
    m = re.search(r"^#\s+(.+?)$", text, re.M)
    title = m.group(1).strip() if m else md_path.stem
    # 去掉标题里的 | Reuters / | Bloomberg 之类后缀
    title = re.sub(r"\s*\|\s*\w+.*$", "", title).strip()
    # 来源 url: > 来源：xxx 行
    m = re.search(r"^>\s*来源：(\S+)", text, re.M)
    src_url = m.group(1).strip() if m else ""
    # 正文: 去掉标题行、引用行、markdown 标记；跳过尾部导航(Read Next 等)
    lines = text.splitlines()
    paras, skip_tail = [], False
    for ln in lines:
        s = ln.strip()
        if s.startswith("# ") or s.startswith("> 来源"):
            continue
        if re.match(r"^#{1,3}\s+(Read Next|Most Read|Also Read|Sign up|Subscribe)", s, re.I):
            skip_tail = True
        if skip_tail:
            continue
        if not s:
            continue
        if s.startswith("#") or s.startswith("!") or s.startswith("[!") :
            continue
        if s.startswith("**View')") or s.startswith("**Download"):
            continue
        # 去除粗体/斜体标记，保留纯文本段落
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        clean = re.sub(r"\*(.+?)\*", r"\1", clean)
        clean = re.sub(r"\[(.+?)\]\([^)]*\)", r"\1", clean)
        # 丢弃垃圾段: 纯链接列表 / 订阅推广 / 许可声明
        if re.match(r"^[-*]?\s*\[?\s*\]\((mailto|https?)", clean):
            continue
        if re.match(r"^(Purchase Licensing|Opinions expressed|Sign up|Follow)", clean, re.I):
            continue
        if len(clean) < 15 and not re.search(r"[\u4e00-\u9fff]", clean):
            continue
        paras.append(clean)
    # 去掉作者简介之后的（粗略：以 "Opinions expressed" / "Purchase Licensing" 分段可留可去）
    return {"title": title, "src_url": src_url, "paras": paras}


def slugify(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return s[:60] or "untitled"


def match_news_item(title: str, src_url: str):
    """在 data/news 里找对应条目。优先 url slug 匹配，其次标题词重合。"""
    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

    slug = ""
    if src_url:
        m = re.search(r"/([^/]+?)/?(?:\?|$)", src_url)
        slug = norm(re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", m.group(1))) if m else ""
    t_words = set(norm(title).split())

    best = None
    for f in sorted(DATA_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        day = f.stem
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for k, s in d.get("sources", {}).items():
            for it in s.get("items", []):
                iu = it.get("url", "")
                # 1) url 直接匹配
                if src_url and src_url.rstrip("/") == iu.rstrip("/"):
                    return day, k, it
                # 2) slug 匹配
                m2 = re.search(r"/([^/]+?)/?(?:\?|$)", iu)
                islug = norm(re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", m2.group(1))) if m2 else ""
                if slug and islug and (slug == islug or slug in islug or islug in slug):
                    return day, k, it
                # 3) 标题词重合 ≥ 60%
                it_words = set(norm(it.get("title", "")).split())
                if t_words and it_words:
                    inter = len(t_words & it_words) / max(len(t_words), len(it_words))
                    if inter >= 0.6 and (best is None or inter > best[0]):
                        best = (inter, day, k, it)
    if best:
        return best[1], best[2], best[3]
    return None


def main():
    ap = argparse.ArgumentParser(description="全文收录（手工导出 md → 翻译 → 挂接新闻）")
    ap.add_argument("--file", help="处理单个 md 文件")
    ap.add_argument("--src", default=str(DEFAULT_SRC), help="md 导出目录")
    ap.add_argument("--list", action="store_true", help="只显示匹配，不翻译")
    ap.add_argument("--days", type=int, default=14, help="在最近 N 天的 news 数据里匹配")
    args = ap.parse_args()

    files = [Path(args.file)] if args.file else sorted(DEFAULT_SRC.glob("export_*.md"))
    if not files:
        sys.exit(f"未找到 md 文件（{args.src}/export_*.md）")

    FT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(CST)

    for md in files:
        if not md.exists():
            continue
        info = parse_md(md)
        hit = match_news_item(info["title"], info["src_url"])
        if not hit:
            print(f"❓ 未匹配: {md.name}")
            print(f"   标题: {info['title']}")
            continue
        day, src, it = hit
        # 按 item 的发布日归档全文（与新闻归档一致）
        pc = (it.get("published_cst") or "")[:10].replace("-", "") or day
        slug = slugify(info["title"])
        out = FT_DIR / f"{pc}.json"

        doc = json.loads(out.read_text()) if out.exists() else {"articles": {}}
        if slug in doc.get("articles", {}):
            print(f"⏭️  已存在: {slug}")
            continue

        print(f"📄 匹配 [{pc}] {src}: {it.get('title_zh') or it['title']}")
        print(f"   源文件: {md.name} ｜ 正文 {len(info['paras'])} 段")
        if args.list:
            continue

        # 分段翻译（每 4 段一批，控制单次请求长度）
        paras = info["paras"]
        zh_paras = []
        for i in range(0, len(paras), 4):
            chunk = "\n\n".join(paras[i:i + 4])
            zh = deepseek_translate(chunk)
            zh_paras.extend([p for p in zh.split("\n\n") if p.strip()])
            time.sleep(0.3)
        doc["articles"][slug] = {
            "title_en": info["title"],
            "title_zh": it.get("title_zh", ""),
            "source": src,
            "source_url": info["src_url"] or it.get("url", ""),
            "news_url": it.get("url", ""),
            "time": it.get("time", ""),
            "published_cst": it.get("published_cst", ""),
            "added_at": now.isoformat(),
            "paras_en": paras,
            "paras_zh": zh_paras,
        }
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        print(f"   ✅ 全文已收录: {out.name} / {slug}（译 {len(zh_paras)} 段）")


if __name__ == "__main__":
    main()
