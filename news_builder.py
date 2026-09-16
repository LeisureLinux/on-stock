#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外媒新闻页面构建器 —— 由 build.py 调用，读取 data/news/*.json 生成静态页面。

产物：
  docs/latest/index.html + index.json    最新一天（站点入口 /latest）
  docs/news/index.html                   归档目录
  docs/news/<YYYYMMDD>/index.html + index.json   每日归档
"""

import html
import json
from pathlib import Path

LORE_DIR = Path(__file__).parent
ASSETS_DIR = LORE_DIR / "assets"  # 静态资源源目录（收款码等）
NEWS_DATA_DIR = LORE_DIR / "data" / "news"
FULLTEXT_DATA_DIR = LORE_DIR / "data" / "fulltext"
SITE_URL = "https://stock.freelamp.com"

# 免费试读条数
TRIAL_LIMIT = 5

# 短标签
SOURCE_SHORT = {"bb": "BB", "ft": "FT", "wsj": "WSJ", "rt": "RT"}

SOURCE_LABEL = {
    "bb": "Bloomberg",
    "ft": "Financial Times",
    "wsj": "The Wall Street Journal",
    "rt": "Reuters",
}

# 每家一个主色，用于源标签
SOURCE_COLOR = {
    "bb": "#B45309",
    "ft": "#0F766E",
    "wsj": "#1D4ED8",
    "rt": "#B91C1C",
}


def _e(s) -> str:
    return html.escape(str(s or ""), quote=False)


def load_days():
    """读取所有归档日数据，日期倒序返回 [(date, data), ...]"""
    if not NEWS_DATA_DIR.exists():
        return []
    days = []
    for f in sorted(NEWS_DATA_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        days.append((d.get("date", f.stem), d))
    days.sort(key=lambda x: x[0], reverse=True)
    return days


def fmt_date(date_str: str) -> str:
    """20260907 → 2026-09-07"""
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


# ---------------------------------------------------------------- 单日页面

DAY_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{canonical}">
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <link rel="alternate" type="application/json" href="{canonical}index.json">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
      background: #F9FAFB; color: #374151; line-height: 1.75;
    }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 0 24px; }}
    header {{
      background: linear-gradient(135deg, #DC2626, #F87171);
      padding: 40px 0 32px; color: #fff; margin-bottom: 28px;
    }}
    header h1 {{ font-size: 27px; font-weight: 900; letter-spacing: -0.5px; margin-bottom: 6px; }}
    header .sub {{ font-size: 14px; opacity: 0.9; }}
    header .nav {{ margin-top: 14px; font-size: 13px; }}
    header .nav a {{ color: #fff; text-decoration: none; opacity: 0.9; margin-right: 16px; border-bottom: 1px solid rgba(255,255,255,0.4); }}
    header .nav a:hover {{ opacity: 1; }}

    .toolbar {{
      background: #fff; border: 1px solid #E5E7EB; border-radius: 12px;
      padding: 14px 18px; margin-bottom: 20px; display: flex; gap: 10px;
      flex-wrap: wrap; align-items: center;
    }}
    .toolbar input {{
      flex: 1; min-width: 180px; border: 1px solid #E5E7EB; border-radius: 8px;
      padding: 8px 12px; font-size: 14px; font-family: inherit; outline: none;
    }}
    .toolbar input:focus {{ border-color: #DC2626; }}
    .chip {{
      border: 1px solid #E5E7EB; background: #fff; border-radius: 20px;
      padding: 6px 14px; font-size: 13px; cursor: pointer; color: #4B5563;
      font-family: inherit; transition: all .15s;
    }}
    .chip:hover {{ border-color: #DC2626; color: #DC2626; }}
    .chip.on {{ background: #DC2626; border-color: #DC2626; color: #fff; }}

    .src-block {{ margin-bottom: 26px; }}
    .src-head {{
      display: flex; align-items: baseline; gap: 10px;
      padding-bottom: 8px; margin-bottom: 10px; border-bottom: 2px solid #E5E7EB;
    }}
    .src-name {{ font-size: 16px; font-weight: 800; }}
    .src-count {{ font-size: 12px; color: #9CA3AF; }}
    .src-note {{ font-size: 12px; color: #9CA3AF; margin-bottom: 10px; }}

    ul.news {{ list-style: none; }}
    ul.news li {{
      background: #fff; border: 1px solid #E5E7EB; border-radius: 10px;
      padding: 12px 16px; margin-bottom: 8px; display: flex; gap: 12px;
      align-items: baseline; transition: box-shadow .15s;
    }}
    ul.news li:hover {{ box-shadow: 0 2px 12px rgba(220,38,38,0.10); }}
    .time {{
      font-size: 12px; color: #9CA3AF; font-variant-numeric: tabular-nums;
      white-space: nowrap; flex-shrink: 0;
    }}
    .news a {{
      color: #111827; text-decoration: none; font-size: 14.5px;
      font-weight: 500; line-height: 1.55;
    }}
    .news a:hover {{ color: #DC2626; }}
    .badge {{
      font-size: 11px; padding: 1px 7px; border-radius: 4px; color: #fff;
      flex-shrink: 0; font-weight: 600;
    }}
    .empty {{ color: #9CA3AF; font-size: 14px; padding: 8px 0; }}
    .title-zh {{ display: block; font-size: 15px; line-height: 1.5; color: #111827; }}
    .title-en {{ display: block; font-size: 12px; line-height: 1.4; color: #9CA3AF; margin-top: 2px; }}
    .title-sum {{ display: block; font-size: 12.5px; line-height: 1.5; color: #4B5563;
      margin-top: 4px; padding-left: 8px; border-left: 2px solid #E5E7EB; }}
    .ft-link {{ display: inline-block; margin-top: 5px; font-size: 12px; color: #DC2626;
      background: #FEF2F2; border: 1px solid #FECACA; border-radius: 6px;
      padding: 1px 8px; text-decoration: none; font-weight: 600; }}
    .ft-link:hover {{ background: #FEE2E2; }}

    footer {{
      text-align: center; color: #9CA3AF; font-size: 13px;
      padding: 32px 0 40px; border-top: 1px solid #E5E7EB; margin-top: 32px;
    }}
    footer a {{ color: #6B7280; }}
    @media (max-width: 600px) {{
      .container {{ padding: 0 16px; }}
      ul.news li {{ flex-wrap: wrap; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>{h1}</h1>
      <div class="sub">{sub}</div>
      <div class="nav">
        <a href="/">首页</a>
        <a href="/news/">历史归档</a>
        <a href="/latest/">最新</a>
        <a href="/subscribe/">订阅</a>
      </div>
    </div>
  </header>

  <div class="container">
    <div class="toolbar">
      <input id="q" type="search" placeholder="过滤标题关键词…">
      {chips}
    </div>

    <div id="list">{blocks}</div>

    <footer>
      数据来源：各机构官方 news sitemap ｜ 时间为北京时间（CST）<br>
      LeisureLinux · <a href="/">股市观察</a>
    </footer>
  </div>

  <script>
    var q = document.getElementById('q');
    var chips = [].slice.call(document.querySelectorAll('.chip'));
    var items = [].slice.call(document.querySelectorAll('ul.news li'));

    function apply() {{
      var kw = (q.value || '').toLowerCase();
      var active = chips.filter(function (c) {{ return c.classList.contains('on'); }})
                        .map(function (c) {{ return c.dataset.src; }});
      items.forEach(function (li) {{
        var okKw = !kw || li.textContent.toLowerCase().indexOf(kw) > -1;
        var okSrc = active.length === 0 || active.indexOf(li.dataset.src) > -1;
        li.style.display = (okKw && okSrc) ? '' : 'none';
      }});
      document.querySelectorAll('.src-block').forEach(function (b) {{
        var vis = b.querySelectorAll('ul.news li[style=""], ul.news li:not([style])').length;
        b.style.display = vis ? '' : 'none';
      }});
    }}

    q.addEventListener('input', apply);
    chips.forEach(function (c) {{
      c.addEventListener('click', function () {{
        c.classList.toggle('on');
        apply();
      }});
    }});
  </script>
</body>
</html>
"""


def build_day_page(date: str, day: dict, is_latest: bool = False, fulltext: dict = None) -> str:
    sources = day.get("sources", {})
    total = sum(s.get("count", 0) for s in sources.values())

    chips = []
    for key in sources:
        label = sources[key].get("name", SOURCE_LABEL.get(key, key))
        chips.append(
            f'<button class="chip" data-src="{_e(key)}">{_e(label)}</button>')
    chips_html = "\n      ".join(chips)

    blocks = []
    for key, s in sources.items():
        name = s.get("name", SOURCE_LABEL.get(key, key))
        color = SOURCE_COLOR.get(key, "#6B7280")
        items = s.get("items", [])
        lis = []
        for it in items:
            badge = (f'<span class="badge" style="background:{color}">'
                     f'{_e(SOURCE_SHORT.get(key, name.split()[0]))}</span>')
            zh = it.get("title_zh", "")
            if zh:
                title_html = (f'<span class="title-zh">{_e(zh)}</span>'
                              f'<span class="title-en">{_e(it.get("title", ""))}</span>')
            else:
                title_html = _e(it.get("title", ""))
            summ = it.get("summary_zh", "")
            if summ:
                title_html += f'<span class="title-sum">{_e(summ)}</span>'
            # 全文图标：该条目有手工收录全文时，加「全文」链接
            if fulltext and it.get("url"):
                arts = fulltext.get("articles", {})
                for slug, a in arts.items():
                    if a.get("news_url") == it.get("url"):
                        title_html += (f'<a class="ft-link" href="/fulltext/{date}/{_e(slug)}/" '
                                       f'title="阅读中文全文（翻译排版）">📄 全文</a>')
                        break
            lis.append(
                f'<li data-src="{_e(key)}">'
                f'<span class="time">{_e(it.get("time", ""))} CST</span>'
                f'<a href="{_e(it.get("link") or it.get("url", ""))}" target="_blank" '
                f'rel="noopener">{title_html}</a>'
                f'{badge}</li>')
        body = "\n        ".join(lis) if lis else '<div class="empty">当日无数据</div>'
        blocks.append(
            f'<div class="src-block" data-block="{_e(key)}">\n'
            f'  <div class="src-head">\n'
            f'    <span class="src-name" style="color:{color}">{_e(name)}</span>\n'
            f'    <span class="src-count">{len(items)} 条</span>\n'
            f'  </div>\n'
            f'  <div class="src-note">{_e(s.get("note", ""))}</div>\n'
            f'  <ul class="news">\n        {body}\n  </ul>\n'
            f'</div>')

    fd = fmt_date(date)
    h1 = f"外媒速览 · {fd}" + ("（最新）" if is_latest else "")
    sub = (f"共 {total} 条 ｜ 来源 {len(sources)} 家 ｜ "
           f"更新于 {_e(day.get('generated_at', '')[:16].replace('T', ' '))} CST")

    return DAY_TEMPLATE.format(
        title=f"外媒新闻速览 {fd} ｜ 股市观察",
        desc=f"{fd} 彭博、金融时报、华尔街日报、路透社最新新闻标题汇总，共 {total} 条。",
        canonical=f"{SITE_URL}/{'latest' if is_latest else 'news/' + date}/",
        h1=h1, sub=sub,
        chips=chips_html,
        blocks="\n\n    ".join(blocks),
    )


# ---------------------------------------------------------------- 归档目录

ARCHIVE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>外媒速览归档 ｜ 股市观察</title>
  <meta name="description" content="每日外媒新闻标题归档：Bloomberg、FT、WSJ、Reuters。">
  <link rel="canonical" href="{site_url}/news/">
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
      background: #F9FAFB; color: #374151; line-height: 1.75;
    }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 0 24px; }}
    header {{
      background: linear-gradient(135deg, #DC2626, #F87171);
      padding: 40px 0 32px; color: #fff; margin-bottom: 28px;
    }}
    header h1 {{ font-size: 27px; font-weight: 900; margin-bottom: 6px; }}
    header .sub {{ font-size: 14px; opacity: 0.9; }}
    header .nav {{ margin-top: 14px; font-size: 13px; }}
    header .nav a {{ color: #fff; text-decoration: none; opacity: .9; margin-right: 16px; border-bottom: 1px solid rgba(255,255,255,0.4); }}
    .day {{
      background: #fff; border: 1px solid #E5E7EB; border-radius: 12px;
      padding: 18px 22px; margin-bottom: 12px; display: flex;
      justify-content: space-between; align-items: center; gap: 12px;
      transition: box-shadow .15s, transform .15s;
    }}
    .day:hover {{ box-shadow: 0 4px 16px rgba(220,38,38,0.10); transform: translateY(-1px); }}
    .day a {{ text-decoration: none; color: inherit; }}
    .day-date {{ font-size: 17px; font-weight: 800; color: #111827; }}
    .day-total {{ font-size: 13px; color: #6B7280; margin-top: 2px; }}
    .day-src {{ font-size: 12px; color: #9CA3AF; text-align: right; white-space: nowrap; }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>外媒速览 · 历史归档</h1>
      <div class="sub">共 {count} 天 ｜ 每日汇总 Bloomberg / FT / WSJ / Reuters</div>
      <div class="nav">
        <a href="/">首页</a>
        <a href="/latest/">最新</a>
      </div>
    </div>
  </header>
  <div class="container">
    {days}
  </div>
</body>
</html>
"""


def build_archive_page(days) -> str:
    rows = []
    for date, d in days:
        sources = d.get("sources", {})
        total = sum(s.get("count", 0) for s in sources.values())
        detail = " ｜ ".join(
            f"{SOURCE_LABEL.get(k, k)} {s.get('count', 0)}"
            for k, s in sources.items())
        rows.append(
            f'<div class="day">\n'
            f'  <a href="{date}/" style="flex:1">\n'
            f'    <div class="day-date">{fmt_date(date)}</div>\n'
            f'    <div class="day-total">共 {total} 条</div>\n'
            f'  </a>\n'
            f'  <div class="day-src">{_e(detail)}</div>\n'
            f'</div>')
    return ARCHIVE_TEMPLATE.format(
        site_url=SITE_URL,
        count=len(days),
        days="\n    ".join(rows) if rows else '<p>暂无归档</p>',
    )


# ---------------------------------------------------------------- 试读页

TRIAL_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>今日速览 · 免费试读 | 外媒新闻</title>
  <meta name="description" content="Bloomberg / FT / WSJ / Reuters 每日标题速览，免费试读最新 {limit} 条。">
  <link rel="canonical" href="{site_url}/trial/">
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
      background: #F9FAFB; color: #374151; line-height: 1.75;
    }}
    .container {{ max-width: 760px; margin: 0 auto; padding: 0 24px; }}
    header {{
      background: linear-gradient(135deg, #DC2626, #F87171);
      padding: 40px 0 32px; color: #fff; margin-bottom: 28px;
    }}
    header h1 {{ font-size: 27px; font-weight: 900; letter-spacing: -0.5px; margin-bottom: 6px; }}
    header .sub {{ font-size: 14px; opacity: 0.9; }}
    header .nav {{ margin-top: 14px; font-size: 13px; }}
    header .nav a {{ color: #fff; text-decoration: none; opacity: 0.9; margin-right: 16px; border-bottom: 1px solid rgba(255,255,255,0.4); }}

    .note {{
      background: #fff; border: 1px solid #E5E7EB; border-left: 3px solid #DC2626;
      border-radius: 10px; padding: 14px 18px; margin-bottom: 20px; font-size: 14px;
    }}
    .src {{ margin-bottom: 22px; }}
    .src-head {{ font-size: 15px; font-weight: 800; margin-bottom: 8px;
      display: flex; align-items: center; gap: 8px; }}
    ul.news {{ list-style: none; margin-bottom: 8px; }}
    ul.news li {{
      background: #fff; border: 1px solid #E5E7EB; border-radius: 10px;
      padding: 12px 16px; margin-bottom: 7px; display: flex; gap: 12px; align-items: baseline;
    }}
    .time {{ font-size: 12px; color: #9CA3AF; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .badge {{ font-size: 11px; padding: 1px 7px; border-radius: 4px; color: #fff; font-weight: 600; flex-shrink: 0; }}
    .t {{ font-size: 14.5px; font-weight: 500; color: #111827; line-height: 1.55; }}

    .cta {{
      background: #fff; border: 1px solid #E5E7EB; border-radius: 14px;
      padding: 26px 24px; text-align: center; margin-bottom: 24px;
    }}
    .cta h2 {{ font-size: 18px; margin-bottom: 8px; color: #111827; }}
    .cta p {{ font-size: 14px; color: #6B7280; margin-bottom: 18px; }}
    .btn {{
      display: inline-block; background: #DC2626; color: #fff; text-decoration: none;
      padding: 11px 26px; border-radius: 8px; font-size: 14.5px; font-weight: 600;
    }}
    .btn:hover {{ background: #B91C1C; }}
    footer {{ text-align: center; color: #9CA3AF; font-size: 13px; padding: 32px 0 40px;
      border-top: 1px solid #E5E7EB; margin-top: 20px; }}
    footer a {{ color: #6B7280; }}
    @media (max-width: 600px) {{ .container {{ padding: 0 16px; }} ul.news li {{ flex-wrap: wrap; }} }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>外媒速览 · 免费试读</h1>
      <div class="sub">{date} ｜ Bloomberg · FT · WSJ · Reuters</div>
      <div class="nav"><a href="/subscribe/">订阅方案</a></div>
    </div>
  </header>
  <div class="container">
    <div class="note">
      以下是今日四个来源各最新 <b>{limit}</b> 条标题的中文翻译（今日全量 <b>{total}</b> 条）。
      完整标题清单、按源筛选、英文原文、每日归档与历史检索，需订阅后访问。
    </div>
    <ul class="news">
    {items}
    </ul>
    <div class="cta">
      <h2>订阅解锁全部内容</h2>
      <p>每天 300+ 条外媒标题 · 四家分源 · 历史归档 · 永久可查<br>10 元 / 月起</p>
      <a class="btn" href="/subscribe/">查看订阅方案</a>
    </div>
    <footer>由 LeisureLinux-Editor 编辑 ｜ <a href="/subscribe/">订阅</a></footer>
  </div>
</body>
</html>
"""


def build_trial_page(date: str, day: dict, limit: int = TRIAL_LIMIT) -> str:
    """免费试读页：四个来源各取最新 limit 条，展示翻译后的中文标题（无则英文原文）。"""
    blocks = []
    shown = 0
    for key, s in (day.get("sources") or {}).items():
        items = s.get("items", [])
        # 每源按时间倒序取前 limit 条（items 本身多按时间排列，倒序取尾更稳妥）
        top = sorted(items, key=lambda it: it.get("time", ""), reverse=True)[:limit]
        if not top:
            continue
        shown += len(top)
        name = s.get("name", key.upper())
        color = SOURCE_COLOR.get(key, "#6B7280")
        lis = "\n".join(
            f'      <li><span class="time">{_e(it.get("time", ""))}</span>'
            f'<span class="t">{_e(it.get("title_zh") or it.get("title", ""))}</span></li>'
            for it in top)
        blocks.append(
            f'    <div class="src">\n'
            f'      <div class="src-head" style="color:{color}">{_e(name)}'
            f'<span class="badge" style="background:{color}">{_e(SOURCE_SHORT.get(key, key.upper()))}</span>'
            f'</div>\n      <ul class="news">\n{lis}\n      </ul>\n    </div>')

    items = "\n".join(blocks) or '      <li><span class="t">暂无数据</span></li>'
    total = sum(s.get("count", 0) for s in (day.get("sources") or {}).values())
    return TRIAL_TEMPLATE.format(
        site_url=SITE_URL, date=fmt_date(date), limit=limit,
        total=total, items=items,
    )


# ---------------------------------------------------------------- 订阅页

SUBSCRIBE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>订阅方案 | 外媒速览</title>
  <meta name="description" content="Bloomberg / FT / WSJ / Reuters 每日中文速览订阅，10 元起。">
  <link rel="canonical" href="{site_url}/subscribe/">
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
      background: #F9FAFB; color: #374151; line-height: 1.75;
    }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 0 24px; }}
    header {{
      background: linear-gradient(135deg, #DC2626, #F87171);
      padding: 40px 0 32px; color: #fff; margin-bottom: 28px;
    }}
    header h1 {{ font-size: 27px; font-weight: 900; letter-spacing: -0.5px; margin-bottom: 6px; }}
    header .sub {{ font-size: 14px; opacity: 0.9; }}
    header .nav {{ margin-top: 14px; font-size: 13px; }}
    header .nav a {{ color: #fff; text-decoration: none; opacity: 0.9; margin-right: 16px; border-bottom: 1px solid rgba(255,255,255,0.4); }}

    .plans {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }}
    .plan {{
      background: #fff; border: 1px solid #E5E7EB; border-radius: 14px;
      padding: 20px 16px; text-align: center; position: relative;
    }}
    .plan.hot {{ border-color: #DC2626; box-shadow: 0 2px 14px rgba(220,38,38,0.12); }}
    .plan .tag {{
      position: absolute; top: -10px; left: 50%; transform: translateX(-50%);
      background: #DC2626; color: #fff; font-size: 11px; padding: 2px 10px; border-radius: 10px;
    }}
    .plan .dur {{ font-size: 13px; color: #6B7280; }}
    .plan .price {{ font-size: 30px; font-weight: 900; color: #111827; margin: 4px 0 2px; }}
    .plan .price span {{ font-size: 15px; font-weight: 600; }}
    .plan .avg {{ font-size: 12px; color: #9CA3AF; }}
    .plan {{ cursor: pointer; transition: border-color .15s, box-shadow .15s, transform .15s; }}
    .plan:hover {{ border-color: #F87171; transform: translateY(-2px); }}
    .plan.sel {{ border-color: #DC2626; box-shadow: 0 2px 14px rgba(220,38,38,0.18); }}
    .plan.sel::after {{ content: "已选"; position: absolute; bottom: 8px; left: 50%; transform: translateX(-50%); font-size: 11px; color: #DC2626; font-weight: 700; }}
    .chosen {{ font-size: 13px; color: #DC2626; font-weight: 600; margin-bottom: 12px; }}

    .pay {{
      background: #fff; border: 1px solid #E5E7EB; border-radius: 14px;
      padding: 28px 24px; text-align: center; margin-bottom: 24px;
    }}
    .pay h2 {{ font-size: 18px; margin-bottom: 6px; }}
    .pay .hint {{ font-size: 13px; color: #6B7280; margin-bottom: 18px; }}
    .qr {{
      width: 220px; max-width: 70%; border: 1px solid #E5E7EB; border-radius: 10px;
      padding: 8px; background: #fff; margin: 0 auto 14px;
    }}
    .qr-missing {{
      width: 220px; max-width: 70%; margin: 0 auto 14px; border: 1px dashed #D1D5DB;
      border-radius: 10px; padding: 40px 10px; color: #9CA3AF; font-size: 13px; text-align: center;
    }}

    ol.steps {{ counter-reset: s; list-style: none; margin: 0 0 24px; }}
    ol.steps li {{
      position: relative; padding-left: 34px; margin-bottom: 14px; font-size: 14.5px;
    }}
    ol.steps li::before {{
      counter-increment: s; content: counter(s);
      position: absolute; left: 0; top: 2px; width: 22px; height: 22px; border-radius: 50%;
      background: #DC2626; color: #fff; font-size: 12px; text-align: center; line-height: 22px;
    }}
    .login {{ background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:24px;margin-bottom:24px; }}
    .login h2 {{ font-size:18px;margin-bottom:12px; }}
    .flow {{ background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:24px;margin-bottom:24px; }}
    .flow h2 {{ font-size:18px;margin-bottom:12px; }}
    .flabel {{ font-size:14px;color:#374151;margin:6px 0; }}
    .row {{ display:flex;gap:8px;margin:8px 0;flex-wrap:wrap; }}
    .row input {{ flex:1;min-width:160px;padding:10px 12px;border:1px solid #D1D5DB;border-radius:8px;font-size:14px; }}
    .row button {{ padding:10px 18px;border:0;border-radius:8px;background:#DC2626;color:#fff;font-size:14px;cursor:pointer; }}
    .row button:hover {{ background:#B91C1C; }}
    .msg {{ font-size:13px;min-height:18px;margin-top:6px;color:#6B7280; }}
    .msg.ok {{ color:#059669; }}
    .msg.err {{ color:#DC2626; }}
    #cf-turnstile {{ margin:8px 0; }}
    .faq dt {{ font-weight: 700; margin-top: 14px; color: #111827; }}
    .faq dd {{ color: #6B7280; }}
    footer {{ text-align: center; color: #9CA3AF; font-size: 13px; padding: 32px 0 40px;
      border-top: 1px solid #E5E7EB; margin-top: 20px; }}
    footer a {{ color: #6B7280; }}
    @media (max-width: 700px) {{
      .container {{ padding: 0 16px; }}
      .plans {{ grid-template-columns: repeat(2, 1fr); }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>订阅方案</h1>
      <div class="sub">每天 300+ 条外媒标题速览 · 四家分源 · 历史归档</div>
      <div class="nav"><a href="/trial/">免费试读</a></div>
    </div>
  </header>
  <div class="container">
    <div class="plans">
      <div class="plan" data-plan="1m" data-price="10">
        <div class="dur">1 个月</div>
        <div class="price"><span>¥</span>10</div>
        <div class="avg">—</div>
      </div>
      <div class="plan" data-plan="3m" data-price="28">
        <div class="dur">3 个月</div>
        <div class="price"><span>¥</span>28</div>
        <div class="avg">约 9.3 元 / 月</div>
      </div>
      <div class="plan" data-plan="6m" data-price="48">
        <div class="dur">6 个月</div>
        <div class="price"><span>¥</span>48</div>
        <div class="avg">8 元 / 月</div>
      </div>
      <div class="plan hot" data-plan="1y" data-price="88">
        <div class="tag">最划算</div>
        <div class="dur">1 年</div>
        <div class="price"><span>¥</span>88</div>
        <div class="avg">7.3 元 / 月</div>
      </div>
    </div>

    <div class="flow">
      <h2>订阅流程</h2>
      <div class="step1">
        <p class="flabel">① 先验证邮箱（确保能收到账号邮件）</p>
        <div class="row">
          <input id="email" type="email" placeholder="你的邮箱，如 you@qq.com" autocomplete="email">
          <button id="btn-code" type="button">获取验证码</button>
        </div>
        <div class="row" id="code-row" style="display:none">
          <input id="code" type="text" placeholder="6 位验证码" inputmode="numeric" maxlength="6">
          <button id="btn-verify" type="button">验证邮箱</button>
        </div>
        <div class="cf-turnstile" id="cf-turnstile"></div>
        <div class="msg" id="email-msg"></div>
      </div>
      <div class="step2">
        <p class="flabel">② 选好上方套餐，扫码付款（备注邮箱）</p>
        <p class="flabel">③ 我确认收款后，账号自动发到你的邮箱</p>
      </div>
    </div>

    <div class="pay">
      <h2>微信扫码付款</h2>
      <div class="hint">付款时请在备注里填上你的邮箱（与上面验证的邮箱一致），方便我核对</div>
      {qr}
      <div class="chosen" id="chosen">未选择套餐 —— 点上方卡片选时长</div>
      <div class="hint">长按识别 / 扫码 → 选择金额 → 备注邮箱 → 完成支付</div>
    </div>

    <div class="login">
      <h2>已有账号？登录</h2>
      <div class="row">
        <input id="lu" type="text" placeholder="用户名（邮箱）" autocomplete="username">
        <input id="lp" type="password" placeholder="密码" autocomplete="current-password">
        <button id="btn-login" type="button">登录</button>
      </div>
      <div class="msg" id="login-msg"></div>
    </div>

    <ol class="steps">
      <li>按上面的套餐金额扫码付款，备注里留一句话（微信号或邮箱即可）。</li>
      <li>我收到款后人工核对，一般 2 小时内、最长当天回复。</li>
      <li>你会收到一组<b>用户名 + 密码 + 到期日期</b>，浏览器打开站点时填入弹出的登录框即可，登录状态记住 7 天。</li>
    </ol>

    <dl class="faq">
      <dt>订阅后能看到什么？</dt>
      <dd>每天 Bloomberg / FT / WSJ / Reuters 全部标题（约 300 条）、按来源筛选、关键词检索，以及全部历史归档。时间为北京时间。</dd>
      <dt>一个账号能几个人用？</dt>
      <dd>一人一号。账号异常共享会被停用。</dd>
      <dt>到期后怎么办？</dt>
      <dd>会提示已到期并跳回本页。续费后用户名密码不变，重新登录即可继续。</dd>
      <dt>内容来源是？</dt>
      <dd>各媒体官方公开发布的新闻站点地图，系统每日自动汇总整理，仅作信息聚合，版权归原媒体所有。</dd>
    </dl>

    <footer>由 LeisureLinux-Editor 编辑 ｜ <a href="/trial/">免费试读</a></footer>
  </div>
  <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
  <script>
    (function () {{
      var plans = document.querySelectorAll('.plan');
      var chosen = document.getElementById('chosen');
      var pay = document.querySelector('.pay');
      var TURNSTILE_SITE_KEY = '{turnstile_site_key}';
      plans.forEach(function (p) {{
        p.addEventListener('click', function () {{
          plans.forEach(function (x) {{ x.classList.remove('sel'); }});
          p.classList.add('sel');
          chosen.textContent = '已选 ' + p.dataset.plan + '（付 ¥' + p.dataset.price + '）';
          if (pay && pay.scrollIntoView) pay.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }});
      }});

      function setMsg(id, text, ok) {{
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className = 'msg' + (ok === false ? ' err' : ok === true ? ' ok' : '');
      }}
      function getPlan() {{
        var sel = document.querySelector('.plan.sel');
        return sel ? sel.dataset.plan : '';
      }}

      // ① 获取验证码
      document.getElementById('btn-code').addEventListener('click', async function () {{
        var email = document.getElementById('email').value.trim();
        var plan = getPlan();
        if (!plan) return setMsg('email-msg', '请先选择上方套餐时长', false);
        if (!email || !/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(email)) return setMsg('email-msg', '邮箱格式不正确', false);
        var token = (window.turnstile && window._tsToken) ? window._tsToken : '';
        setMsg('email-msg', '发送中…');
        var r = await fetch('/api/verify-email', {{
          method: 'POST', headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{ email: email, plan: plan, turnstile: token }})
        }}).then(function (x) {{ return x.json(); }});
        if (r.ok) {{
          setMsg('email-msg', r.msg, true);
          document.getElementById('code-row').style.display = 'flex';
        }} else {{
          setMsg('email-msg', r.msg, false);
        }}
      }});

      // ② 校验验证码
      document.getElementById('btn-verify').addEventListener('click', async function () {{
        var email = document.getElementById('email').value.trim();
        var code = document.getElementById('code').value.trim();
        setMsg('email-msg', '验证中…');
        var r = await fetch('/api/verify-code', {{
          method: 'POST', headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{ email: email, code: code }})
        }}).then(function (x) {{ return x.json(); }});
        setMsg('email-msg', r.msg, r.ok);
      }});

      // 登录
      document.getElementById('btn-login').addEventListener('click', async function () {{
        var u = document.getElementById('lu').value.trim();
        var p = document.getElementById('lp').value;
        setMsg('login-msg', '登录中…');
        var r = await fetch('/api/login', {{
          method: 'POST', headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{ user: u, pass: p }})
        }}).then(function (x) {{ return x.json(); }});
        if (r.ok) {{
          setMsg('login-msg', '登录成功，正在跳转…', true);
          setTimeout(function () {{ location.href = '/latest/'; }}, 600);
        }} else {{
          setMsg('login-msg', r.msg, false);
        }}
      }});

      // Turnstile 回调
      window.onloadTurnstileCallback = function () {{
        if (window.turnstile && TURNSTILE_SITE_KEY) {{
          window._tsToken = turnstile.render('#cf-turnstile', {{
            sitekey: TURNSTILE_SITE_KEY,
            callback: function (t) {{ window._tsToken = t; }}
          }});
        }}
      }};
    }})();
  </script>
</body>
</html>
"""


def build_subscribe_page(has_qr: bool = False) -> str:
    qr = ('<img class="qr" src="/assets/wechat-pay-qr.png" alt="微信收款码">'
          if has_qr else
          '<div class="qr-missing">收款码待上传<br>（放置 assets/wechat-pay-qr.png）</div>')
    ts_key = ''
    env_file = Path.home() / '.codex' / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('TURNSTILE_SITE_KEY='):
                ts_key = line.split('=', 1)[1].strip().strip('"\'')
                break
    return SUBSCRIBE_TEMPLATE.format(site_url=SITE_URL, qr=qr, turnstile_site_key=ts_key)


# ---------------------------------------------------------------- 入口

def load_fulltext(date: str):
    """读某天的全文收录数据；无则返回 None"""
    f = FULLTEXT_DATA_DIR / f"{date}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


FULLTEXT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | 外媒全文</title>
  <meta name="robots" content="noindex, nofollow">
  <link rel="canonical" href="{site_url}/fulltext/{date}/{slug}/">
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', serif;
      background: #F9FAFB; color: #374151; line-height: 1.9; }}
    .paper {{ max-width: 720px; margin: 0 auto; background: #fff; padding: 48px 56px 64px; }}
    .src-line {{ font-size: 13px; color: #9CA3AF; margin-bottom: 6px; }}
    .src-line a {{ color: #6B7280; }}
    h1 {{ font-size: 26px; line-height: 1.45; color: #111827; margin: 6px 0 6px; font-weight: 800; }}
    .en-title {{ font-size: 15px; color: #9CA3AF; line-height: 1.5; margin-bottom: 18px; }}
    hr {{ border: 0; border-top: 1px solid #F3F4F6; margin: 22px 0; }}
    p {{ font-size: 16px; margin-bottom: 18px; text-align: justify; }}
    .lang-toggle {{ margin: 0 0 18px; font-size: 13px; }}
    .lang-toggle button {{ background: #fff; border: 1px solid #E5E7EB; border-radius: 8px;
      padding: 5px 14px; margin-right: 8px; cursor: pointer; font-size: 13px; color: #374151; }}
    .lang-toggle button.on {{ background: #DC2626; color: #fff; border-color: #DC2626; }}
    body.show-en p.en {{ display: block; }}
    body.show-en p.zh {{ display: none; }}
    footer {{ max-width: 720px; margin: 0 auto; padding: 20px; font-size: 12.5px;
      color: #9CA3AF; text-align: center; }}
    footer a {{ color: #DC2626; }}
    @media (max-width: 760px) {{ .paper {{ padding: 28px 20px 44px; }} }}
  </style>
</head>
<body>
  <div class="paper">
    <div class="src-line">{source_name} · {time} CST ｜ <a href="{news_url}" target="_blank" rel="noopener">原文</a></div>
    <h1>{title}</h1>
    <div class="en-title">{title_en}</div>
    <div class="lang-toggle">
      <button class="on" onclick="setLang('zh', this)">中文</button>
      <button onclick="setLang('en', this)">English</button>
    </div>
{paras}
  </div>
  <footer>内容由 AI 翻译润色，仅供参考，以原文为准 ｜ <a href="/latest/">返回今日速览</a> ｜ <a href="/subscribe/">订阅</a></footer>
  <script>
    function setLang(lang, btn) {{
      document.body.classList.toggle('show-en', lang === 'en');
      var bs = document.querySelectorAll('.lang-toggle button');
      for (var i = 0; i < bs.length; i++) bs[i].classList.remove('on');
      btn.classList.add('on');
    }}
  </script>
</body>
</html>
"""


def build_fulltext_pages(docs_dir: Path) -> int:
    """生成所有全文排版页 docs/fulltext/<date>/<slug>/，返回页数"""
    if not FULLTEXT_DATA_DIR.exists():
        return 0
    n = 0
    for f in sorted(FULLTEXT_DATA_DIR.glob("*.json")):
        date = f.stem
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for slug, a in doc.get("articles", {}).items():
            src_label = SOURCE_LABEL.get(a.get("source"), a.get("source", "").upper())
            paras = []
            zh = a.get("paras_zh", [])
            en = a.get("paras_en", [])
            for i in range(max(len(zh), len(en))):
                z = zh[i] if i < len(zh) else ""
                e = en[i] if i < len(en) else ""
                if z:
                    paras.append(f'    <p class="zh">{_e(z)}</p>')
                if e:
                    paras.append(f'    <p class="en" style="display:none;color:#6B7280;font-size:14px">{_e(e)}</p>')
            html = FULLTEXT_TEMPLATE.format(
                site_url=SITE_URL, date=date, slug=slug,
                title=_e(a.get("title_zh") or a.get("title_en", "")),
                title_en=_e(a.get("title_en", "")),
                source_name=_e(src_label), time=_e(a.get("time", "")),
                news_url=_e(a.get("news_url", "#")),
                paras="\n".join(paras))
            d = docs_dir / "fulltext" / date / slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(html, encoding="utf-8")
            n += 1
    return n


def build_news_pages(docs_dir: Path) -> int:
    """生成全部新闻页面，返回生成的目录数"""
    days = load_days()
    if not days:
        print("   ℹ️  无新闻数据（data/news/ 为空），跳过新闻页构建")
        return 0

    news_dir = docs_dir / "news"
    news_dir.mkdir(parents=True, exist_ok=True)

    latest_date, latest_data = days[0]

    # 每日归档页
    for date, d in days:
        day_dir = news_dir / date
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / "index.html").write_text(
            build_day_page(date, d, is_latest=False), encoding="utf-8")
        (day_dir / "index.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    # 归档目录
    (news_dir / "index.html").write_text(
        build_archive_page(days), encoding="utf-8")

    # latest：完整复制最新一天（站点入口 /latest）
    latest_dir = docs_dir / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    (latest_dir / "index.html").write_text(
        build_day_page(latest_date, latest_data, is_latest=True,
                       fulltext=load_fulltext(latest_date)), encoding="utf-8")
    (latest_dir / "index.json").write_text(
        json.dumps(latest_data, ensure_ascii=False, indent=1), encoding="utf-8")

    # 免费试读页
    trial_dir = docs_dir / "trial"
    trial_dir.mkdir(parents=True, exist_ok=True)
    (trial_dir / "index.html").write_text(
        build_trial_page(latest_date, latest_data), encoding="utf-8")
    flat = []
    for k, s in latest_data.get("sources", {}).items():
        for it in s.get("items", []):
            flat.append({"src": k, "src_name": SOURCE_LABEL.get(k, k),
                         "badge": SOURCE_SHORT.get(k, k.upper()),
                         "color": SOURCE_COLOR.get(k, "#6B7280"),
                         "time": it.get("time", ""), "title": it.get("title", "")})
    flat.sort(key=lambda x: x["time"], reverse=True)
    (trial_dir / "index.json").write_text(
        json.dumps({"date": latest_date, "trial_limit": TRIAL_LIMIT,
                    "items": flat[:TRIAL_LIMIT]},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")

    # 全文排版页
    n_ft = build_fulltext_pages(docs_dir)
    if n_ft:
        print(f"   📄 全文页：{n_ft} 篇")

    # 订阅页
    sub_dir = docs_dir / "subscribe"
    sub_dir.mkdir(parents=True, exist_ok=True)
    has_qr = (ASSETS_DIR / "wechat-pay-qr.png").exists()
    (sub_dir / "index.html").write_text(
        build_subscribe_page(has_qr), encoding="utf-8")

    total = sum(s.get("count", 0) for s in latest_data.get("sources", {}).values())
    print(f"   📰 新闻页：{len(days)} 天归档 + latest（{latest_date}，{total} 条）"
          f" + trial（5 条免费） + subscribe")


if __name__ == "__main__":
    import tempfile
    out = Path(tempfile.mkdtemp())
    build_news_pages(out)
    print("测试输出:", out)
