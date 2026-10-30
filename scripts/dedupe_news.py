#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨源重复新闻合并 —— 同一天归档里「同一件事被多家通讯社各报一条」的，只留一条。

判定分四级（逐级放宽，宁可漏杀、不可错杀）：
  1. 同源：标题归一化后完全相同                       → 重复
  2. 同源：一方词集合被另一方包含（短的一方 ≥ MIN_TOKENS 词）→ 重复
  3. 同源：IDF 加权词重叠分 ≥ --same（默认 0.55）      → 重复
  4. 跨源：IDF 加权词重叠分 ≥ --cross（默认 0.30）     → 重复

为什么用 IDF 加权而不是朴素 Jaccard：权重按**当天归档**统计，`intel`/`doordash`
这类当天少见的词权重大，`shares`/`stocks`/`fall` 这类到处都是的词几乎不计分。
于是「Intel shares fall 22%…」和「Intel Shares Plunge More Than 20%…」能配上，
而「Tokyo Inflation Exceeds BOJ's 2% Target」和「JGB Yields Fall Ahead of BOJ
Rate Decision」不会被误并（后者朴素 Jaccard 也有 0.27，是典型的假阳性）。

保留谁：源优先级 bb > wsj > ft > rt（bb 有正文/摘要能力，留它信息最全），
同级取发布时间早的那条。

被丢弃的条目不删数据，只打标（可回溯、可回滚）：
  dup_of      = 保留条目的 url
  dup_reason  = 判定依据（same-source:identical / cross-source:score=0.52 …）
  dup_title   = 保留条目的标题（便于人工复核）
`news_builder.py` 构建时跳过带 dup_of 的条目；本脚本每次重跑会先清空旧标记再重算，
所以数据一变（比如 Reuters 恢复抓取）标记会跟着变。

用法：
  python3 scripts/dedupe_news.py --date 20261030 --dry-run   # 只看会丢什么，不写盘
  python3 scripts/dedupe_news.py --date 20261030             # 落盘
  python3 scripts/dedupe_news.py --all                       # data/news 下全部归档
"""

import argparse
import collections
import json
import math
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "news"

# 保留优先级：数字越小越优先留
SOURCE_PRIORITY = {"bb": 0, "wsj": 1, "ft": 2, "rt": 3}

# 标题里不承载"这件事是什么"的词：留着只会让不同事件互相靠近
STOP = set("""a an the and or but of to in on at for from by with as is are was were be been being
its it this that these those after before over under amid into out up down not no new says said say
will would could should may might can has have had do does did than then so also more most less
s t re ve ll d m what whats why how who whom which when where""".split())

MIN_TOKENS = 3          # 参与"包含"判定的最短标题词数（太短的标题不适用）
RARE_DF_RATIO = 0.02    # 只用于 debug 输出：df 占比低于此值的词算"罕见词"


def _norm_title(t: str) -> str:
    t = (t or "").lower().replace("\u2019s", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _tokens(t: str) -> set:
    """标题 → 词集合（去停用词、去标点、粗暴去复数）。"""
    t = (t or "").lower().replace("\u2019s", "").replace("\u2019", "")
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9.\-]*", t)
             if w not in STOP and len(w) > 1]
    return {w.rstrip("s") if len(w) > 3 else w for w in words}


def _idf(corpus: list) -> dict:
    n = len(corpus)
    df = collections.Counter(t for ts in corpus for t in ts)
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


def _score(a: set, b: set, idfw: dict) -> float:
    union = a | b
    if not union:
        return 0.0
    num = sum(idfw.get(t, 1.0) for t in a & b)
    den = sum(idfw.get(t, 1.0) for t in union)
    return num / den if den else 0.0


class _UF:
    """并查集：把"彼此判为重复"的条目并成簇，每簇只留一个 keeper。"""

    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def dedupe_day(day: dict, cross: float, same: float, dry_run: bool = False) -> dict:
    """在一天的归档上标注重复条目，返回统计。"""
    # 摊平：只处理有 title 的条目（空标题的垃圾条目另行处理，不参与比对）
    flat = []
    for src_key, s in (day.get("sources") or {}).items():
        for it in (s.get("items") or []):
            it.pop("dup_of", None)          # 每次重算：先清旧标记
            it.pop("dup_reason", None)
            it.pop("dup_title", None)
            if (it.get("title") or "").strip():
                flat.append((src_key, it))

    if len(flat) < 2:
        return {"items": len(flat), "clusters": 0, "dropped": 0, "pairs": []}

    corpus = [_tokens(it.get("title")) for _, it in flat]
    idfw = _idf(corpus)
    norm = [_norm_title(it.get("title")) for _, it in flat]

    uf = _UF(len(flat))
    reasons = {}                             # (i, j) -> 判定依据
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            same_src = flat[i][0] == flat[j][0]
            a, b = corpus[i], corpus[j]
            reason = ""
            if same_src:
                if norm[i] == norm[j]:
                    reason = "same-source:identical"
                elif (min(len(a), len(b)) >= MIN_TOKENS
                      and (a <= b or b <= a)):
                    reason = "same-source:containment"
                else:
                    sc = _score(a, b, idfw)
                    if sc >= same:
                        reason = f"same-source:score={sc:.2f}"
            else:
                sc = _score(a, b, idfw)
                if sc >= cross:
                    reason = f"cross-source:score={sc:.2f}"
            if reason:
                uf.union(i, j)
                reasons[(i, j)] = reason

    clusters = collections.defaultdict(list)
    for idx in range(len(flat)):
        clusters[uf.find(idx)].append(idx)

    def rank(idx: int):
        """keeper 排序键：源优先级 → 发布时间早 → 原顺序。"""
        src_key, it = flat[idx]
        ts = str(it.get("published_cst") or it.get("time") or "")
        return (SOURCE_PRIORITY.get(src_key, 99), ts or "~", idx)

    pairs, dropped = [], 0
    for members in clusters.values():
        if len(members) < 2:
            continue
        members.sort(key=rank)
        keeper = members[0]
        keep_url = flat[keeper][1].get("url") or ""
        keep_title = flat[keeper][1].get("title") or ""
        for idx in members[1:]:
            src_key, it = flat[idx]
            reason = next((r for (i, j), r in reasons.items()
                           if {i, j} == {keeper, idx}), "cluster")
            pairs.append({
                "drop_src": src_key, "drop_title": it.get("title") or "",
                "keep_src": flat[keeper][0], "keep_title": keep_title,
                "reason": reason,
            })
            if not dry_run:
                it["dup_of"] = keep_url
                it["dup_reason"] = reason
                it["dup_title"] = keep_title
            dropped += 1

    return {"items": len(flat), "clusters": sum(1 for m in clusters.values() if len(m) > 1),
            "dropped": dropped, "pairs": pairs}


def process_file(path: Path, cross: float, same: float, dry_run: bool) -> dict:
    day = json.loads(path.read_text(encoding="utf-8"))
    st = dedupe_day(day, cross, same, dry_run)
    st["file"] = path.name
    if not dry_run and st["dropped"]:
        day["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        path.write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def main():
    ap = argparse.ArgumentParser(description="同日跨源重复新闻合并（打标 dup_of）")
    ap.add_argument("--date", default=None, help="YYYYMMDD，默认今天")
    ap.add_argument("--all", action="store_true", help="处理 data/news 下全部归档")
    ap.add_argument("--dry-run", action="store_true", help="只列出会丢弃的条目，不写盘")
    ap.add_argument("--cross", type=float, default=0.30, help="跨源判定阈值（默认 0.30）")
    ap.add_argument("--same", type=float, default=0.55, help="同源判定阈值（默认 0.55）")
    ap.add_argument("--verbose", action="store_true", help="逐条打印被合并的对")
    args = ap.parse_args()

    if args.all:
        files = sorted(DATA_DIR.glob("*.json"))
    else:
        date = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
        files = [DATA_DIR / f"{date}.json"]
        if not files[0].exists():
            sys.exit(f"无数据文件：{files[0]}")

    mode = "dry-run（不写盘）" if args.dry_run else "落盘"
    print(f"去重 ｜ {mode} ｜ cross={args.cross} same={args.same}")
    tot_items = tot_drop = tot_clusters = 0
    for f in files:
        if f.name == "index.json":
            continue
        st = process_file(f, args.cross, args.same, args.dry_run)
        tot_items += st["items"]
        tot_drop += st["dropped"]
        tot_clusters += st["clusters"]
        print(f"  {st['file']}: {st['items']} 条 → 合并 {st['clusters']} 组、"
              f"丢弃 {st['dropped']} 条")
        if args.verbose:
            for p in st["pairs"]:
                print(f"    ✂ [{p['drop_src']}] {p['drop_title'][:56]}")
                print(f"      ↳ 保留 [{p['keep_src']}] {p['keep_title'][:56]}  ({p['reason']})")
    print(f"\n合计：{tot_items} 条，合并 {tot_clusters} 组，丢弃 {tot_drop} 条"
          + ("（dry-run，未写入）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
