#!/usr/bin/env python3
"""将 stock 网站 article.md 转换为石墨极简风公众号 HTML"""

import re
from pathlib import Path

# 石墨极简风主色
GRAY = "#52525B"
DARK = "#27272A"
LIGHT = "#A1A1AA"
LINE = "#E4E4E7"
BG = "#FAFAFA"
BG_TAG = "#F4F4F5"

LEAF = '<span leaf="">'
LEAF_END = '</span>'

def p(text, **kw):
    """段落组件：石墨下划线标记关键词"""
    style = kw.get("style", "margin-bottom:22px;font-size:15px;line-height:1.8;text-align:justify;color:#52525B;letter-spacing:0.3px;")
    return f'<p style="{style}">{text}</p>'

def txt(s):
    """普通文字"""
    return f'{LEAF}{s}{LEAF_END}'

def u(s):
    """石墨下划线关键词"""
    return f'<span style="border-bottom:2px solid #52525B;font-weight:600;color:#27272A;">{LEAF}{s}{LEAF_END}</span>'

def b(s):
    """深炭加粗"""
    return f'<strong style="color:#27272A;">{LEAF}{s}{LEAF_END}</strong>'

def orange_u(s):
    """橙色下划线（锚点，全文≤3处）"""
    return f'<span style="border-bottom:2px solid #F97316;font-weight:700;color:#27272A;">{LEAF}{s}{LEAF_END}</span>'

def link(s, url):
    return f'<a href="{url}" target="_blank" style="color:#52525B;border-bottom:1px solid #A1A1AA;">{LEAF}{s}{LEAF_END}</a>'

def section_header(num, en, title):
    """章节标题：超大水印编号"""
    return f'''<section style="margin-top:56px;margin-bottom:32px;padding:0 10px;">
  <section style="position:relative;padding-bottom:20px;border-bottom:1px solid #E4E4E7;">
    <p style="font-size:48px;font-weight:900;color:#E4E4E7;margin:0;line-height:1;letter-spacing:-2px;">{LEAF}{num}{LEAF_END}</p>
    <section style="margin-top:-8px;">
      <p style="font-size:10px;color:#A1A1AA;font-weight:500;letter-spacing:3px;margin:0 0 6px;text-transform:uppercase;">{LEAF}{en}{LEAF_END}</p>
      <h3 style="font-size:20px;font-weight:800;color:#27272A;margin:0;letter-spacing:0.5px;line-height:1.4;">{LEAF}{title}{LEAF_END}</h3>
    </section>
  </section>
</section>'''

def section_divider():
    """1px 石墨细线"""
    return '''<section style="padding:0 10px;">
  <section style="height:1px;background:#E4E4E7;margin:0;"><span leaf=""><br></span></section>
</section>'''

def data_card(num, label, color="#27272A"):
    """两列数据卡"""
    return f'''<section style="flex:1;border:1px solid #E4E4E7;padding:22px 16px;margin-right:8px;text-align:center;">
    <p style="font-size:32px;font-weight:900;color:{color};margin:0 0 6px;line-height:1;letter-spacing:-1px;">{LEAF}{num}{LEAF_END}</p>
    <p style="font-size:11px;color:#A1A1AA;margin:0;letter-spacing:1px;">{LEAF}{label}{LEAF_END}</p>
  </section>'''

def two_col_data(d1, l1, d2, l2):
    return f'''<section style="display:flex;margin:0 10px 28px;">{data_card(d1, l1)}{data_card(d2, l2, "#F97316").replace('margin-right:8px;', 'margin-right:0;')}
</section>'''

def quote_gold(s):
    """石墨竖条金句"""
    return f'''<section style="border-left:3px solid #52525B;padding:16px 0 16px 24px;margin:0 10px 28px;">
  <p style="font-size:16px;font-weight:700;color:#27272A;margin:0;line-height:1.7;letter-spacing:0.5px;">{LEAF}「{s}」{LEAF_END}</p>
</section>'''

def quote_block(tag, content):
    """极浅灰底引用块"""
    return f'''<section style="background:#FAFAFA;border:1px solid #E4E4E7;padding:20px 22px;margin:0 10px 28px;">
  <p style="font-size:11px;color:#A1A1AA;margin:0 0 8px;letter-spacing:2px;font-weight:500;">{LEAF}{tag}{LEAF_END}</p>
  <p style="font-size:15px;color:#3F3F46;margin:0;line-height:1.8;text-align:justify;">{content}</p>
</section>'''

def table(headers, rows):
    """表格"""
    thead = ''.join(f'<th style="background:#27272A;color:#fff;font-weight:700;padding:8px 12px;text-align:left;">{LEAF}{h}{LEAF_END}</th>' for h in headers)
    body = ''
    for i, row in enumerate(rows):
        bg = '#FAFAFA' if i % 2 else '#FFFFFF'
        body += '<tr>'
        for cell in row:
            body += f'<td style="padding:8px 12px;border-bottom:1px solid #E4E4E7;color:#52525B;background:{bg};">{LEAF}{cell}{LEAF_END}</td>'
        body += '</tr>'
    return f'''<section style="margin:0 10px 24px;overflow-x:auto;">
  <table style="width:100%;border-collapse:collapse;font-size:14px;">
    <thead><tr>{thead}</tr></thead>
    <tbody>{body}</tbody>
  </table>
</section>'''

def ordered_list(items):
    """有序列表"""
    out = '<section style="margin-bottom:24px;">'
    for i, item in enumerate(items, 1):
        out += f'''<section style="display:flex;align-items:flex-start;gap:10px;margin-bottom:12px;">
    <span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;background:#27272A;color:#fff;font-size:12px;font-weight:700;border-radius:50%;flex-shrink:0;margin-top:2px;">{LEAF}{i}{LEAF_END}</span>
    <p style="font-size:15px;color:#52525B;margin:0;line-height:1.8;flex:1;">{item}</p>
  </section>'''
    out += '</section>'
    return out

def tag_pill(s):
    return f'<span style="display:inline-block;border:1px solid #A1A1AA;color:#52525B;font-size:11px;font-weight:500;padding:2px 10px;border-radius:2px;margin-right:6px;letter-spacing:0.5px;">{LEAF}{s}{LEAF_END}</span>'

def subhead(s):
    """### 子标题：左竖条"""
    return f'<p style="font-size:15px;font-weight:800;color:#27272A;margin:28px 0 14px;padding-left:12px;border-left:3px solid #52525B;line-height:1.4;">{LEAF}{s}{LEAF_END}</p>'

def end_section():
    """END 分割线"""
    return '''<section style="padding:0 10px;">
  <section style="text-align:center;margin:0 0 36px;">
    <section style="display:flex;align-items:center;justify-content:center;">
      <span style="height:1px;width:48px;background:#E4E4E7;margin-right:16px;">{leaf}<br>{leaf_end}</span>
      <span style="font-size:10px;color:#A1A1AA;letter-spacing:4px;font-weight:500;">{leaf}END{leaf_end}</span>
      <span style="height:1px;width:48px;background:#E4E4E7;margin-left:16px;">{leaf}<br>{leaf_end}</span>
    </section>
  </section>
</section>'''.format(leaf=LEAF, leaf_end=LEAF_END)

def signature():
    """尾部签名"""
    return '''<section style="padding:0 10px 24px;">
  <section style="border-top:1px solid #E4E4E7;padding-top:28px;">
    <p style="margin-bottom:16px;font-size:15px;line-height:1.8;color:#52525B;text-align:justify;">
      {leaf}我是 {{作者名}}，{{一句话简介，如：热衷于分享 AI 观察与干货}}。{leaf_end}
    </p>
    <p style="margin-bottom:0;font-size:15px;line-height:1.8;color:#52525B;text-align:justify;">
      {leaf}如果你觉得今天这篇有收获，欢迎{leaf_end}
      <strong style="color:#27272A;">{leaf}点赞、在看、转发{leaf_end}</strong>
      {leaf}三连，我们下篇见。{leaf_end}
    </p>
  </section>
</section>'''.format(leaf=LEAF, leaf_end=LEAF_END)

# ============= 装配全文 =============
parts = []

# 1. 全局容器开头
parts.append('<section style="max-width:677px;margin:0 auto;background:#FFFFFF;font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Hiragino Sans GB\',\'Microsoft YaHei\',sans-serif;color:#52525B;line-height:1.8;letter-spacing:0.3px;overflow-x:hidden;">')

# 2. 引言卡
parts.append(f'''<section style="margin:10px 10px 40px;padding:32px 24px 24px;border-top:1px solid #E4E4E7;border-bottom:1px solid #E4E4E7;background:#FFFFFF;">
  <p style="font-size:11px;color:#A1A1AA;letter-spacing:2px;margin:0 0 18px;font-weight:400;">{LEAF}QUOTE{LEAF_END}</p>
  <p style="font-size:18px;font-weight:700;color:#27272A;margin:0 0 8px;line-height:1.7;letter-spacing:0.5px;">
    {LEAF}当 11 家上市逆变器企业的合计归母净利同比{LEAF_END}
    {u('−4.48%')}
    {LEAF}，而{LEAF_END}
    {u('前三家拿走 95.57% 的净利润')}
    {LEAF}时，剩下 8 家只剩下{LEAF_END}
    {orange_u('「筹码重新定价」')}
    {LEAF}这一条路。{LEAF_END}
  </p>
  <p style="text-align:right;font-size:12px;color:#A1A1AA;margin:16px 0 0;letter-spacing:1px;">
    {LEAF}—— 数据截至 2026 H1{LEAF_END}
  </p>
</section>''')

# 3. 前言正文
parts.append(p(
    f'{LEAF}这是一篇基于 2026 上半年报数据的行业复盘。不讲故事，只摆数据；不做宏观展望，只看 Q3 拐点。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}如果只看一句话：{LEAF_END}{u("国内集中式逆变器被压制")}{LEAF}，{LEAF_END}{u("出口 \"量减价增\"")}{LEAF}，{LEAF_END}{orange_u("储能 + AIDC 接棒")}{LEAF}。比风电更值得左侧布局，但前提是 Q3 出货数据确认拐点。{LEAF_END}'
))

# 4. 导读
parts.append('''<section style="padding:0 10px 40px;">
  <p style="font-size:11px;color:#A1A1AA;margin:0 0 16px;letter-spacing:2px;">
    {leaf}本文看点{leaf_end}
  </p>
  <section style="display:flex;justify-content:space-between;">
    <section style="flex:1;background:#FAFAFA;border-top:1px solid #E4E4E7;padding:18px 12px 16px;margin-right:8px;">
      <p style="font-size:11px;color:#A1A1AA;font-weight:500;margin:0 0 8px;letter-spacing:1px;">{leaf}01{leaf_end}</p>
      <p style="font-size:13px;font-weight:700;color:#27272A;margin:0;line-height:1.5;">{leaf}行业全貌：前三家拿 95% 利润{leaf_end}</p>
    </section>
    <section style="flex:1;background:#FAFAFA;border-top:1px solid #E4E4E7;padding:18px 12px 16px;margin-right:8px;">
      <p style="font-size:11px;color:#A1A1AA;font-weight:500;margin:0 0 8px;letter-spacing:1px;">{leaf}02{leaf_end}</p>
      <p style="font-size:13px;font-weight:700;color:#27272A;margin:0;line-height:1.5;">{leaf}三大主线：集中式 / 出口 / 储能+AIDC{leaf_end}</p>
    </section>
    <section style="flex:1;background:#FAFAFA;border-top:1px solid #E4E4E7;padding:18px 12px 16px;">
      <p style="font-size:11px;color:#A1A1AA;font-weight:500;margin:0 0 8px;letter-spacing:1px;">{leaf}03{leaf_end}</p>
      <p style="font-size:13px;font-weight:700;color:#27272A;margin:0;line-height:1.5;">{leaf}Q3 拐点：盯三个数{leaf_end}</p>
    </section>
  </section>
</section>'''.format(leaf=LEAF, leaf_end=LEAF_END))

# ===== 章节 01 一句话总结 =====
parts.append(section_header("01", "OVERVIEW", "一句话总结"))

parts.append(two_col_data(
    "727.64 亿", "11 家合计营收 +6.77%",
    "−4.48%", "合计归母净利同比"
))

parts.append(p(
    f'{LEAF}2026 上半年，{LEAF_END}{u("11 家上市逆变器企业合计营收 727.64 亿（+6.77%）")}'
    f'{LEAF}、{LEAF_END}{u("合计归母净利 109.07 亿（−4.48%）")}'
    f'{LEAF}，营收增速掉到个位数，净利润已经负增长。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}另一面，{LEAF_END}{b("阳光电源 + 德业 + 思格 三家拿走了行业 95.57% 的净利润")}'
    f'{LEAF}。剩下 8 家，要么微利、要么亏损，{LEAF_END}'
    f'{u("微逆龙头出现 \"营收腰斩\"")}{LEAF}。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}这是典型的{LEAF_END}{b("洗牌中段")}{LEAF}：行业增速见顶 → 价格战开打 → 份额向头部集中 → 二三线被甩开。{LEAF_END}'
    f'{LEAF}对左侧布局者来说，{LEAF_END}{u("正好是筹码重新定价的窗口")}{LEAF}。{LEAF_END}'
))

parts.append(section_divider())

# ===== 章节 02 国内集中式 =====
parts.append(section_header("02", "DOMESTIC", "国内集中式逆变器：被压制，Q2 已现拐点信号"))

parts.append(subhead("数据全貌"))
parts.append(table(
    ["维度", "2026 H1", "同比"],
    [
        ["11 家合计营收", "727.64 亿", "+6.77%"],
        ["11 家合计归母净利", "109.07 亿", "−4.48%"],
        ["阳光 + 德业 + 思格 净利占比", "95.57%", "—"],
        ["亏损企业数", "3 家", "—"],
    ]
))

parts.append(p(
    f'{LEAF}压制来自三个方向：国内集中式光伏并网节奏放缓（配储要求拉低 IRR）、价格战（二三线低价抢单）、{LEAF_END}'
    f'{u("微逆/集中式部分厂商上半年已亏损")}{LEAF}。{LEAF_END}'
))

parts.append(subhead("Q2 已开始环比改善"))
parts.append(p(
    f'{LEAF}虽然上半年整体负增长，但{LEAF_END}{b("阳光电源 Q2 营收约 153.51 亿、归母净利约 29.67 亿，环比 +29.5%")}'
    f'{LEAF}，说明压制因素最重的时点已过。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}而且有个{LEAF_END}{b("关键看点")}{LEAF}，阳光电源光伏逆变器板块毛利率{LEAF_END}'
    f'{u("42.72%")}{LEAF}，同比{LEAF_END}{u("逆势提升 6.98 个百分点")}{LEAF}。价虽然下来，毛利反而上去了，'
    f'头部公司的产品溢价能力没有被打穿。{LEAF_END}'
))

parts.append(section_divider())

# ===== 章节 03 出口 =====
parts.append(section_header("03", "EXPORT", "出口：「量减价增」，结构性机会大于总量"))

parts.append(two_col_data(
    "2473 万台", "1-6 月出口量 −6.5%",
    "+30%", "出口额 55.3 亿美元"
))

parts.append(p(
    f'{LEAF}简单算一下：量减 6.5%、额增 30%，{LEAF_END}'
    f'{u("单台均价上涨约 39%")}{LEAF}。这不是涨价，是{LEAF_END}'
    f'{b("产品结构升级")}{LEAF}——低毛利的传统集中式被淘汰，高毛利的{LEAF_END}'
    f'{u("户储 / 混合逆变器 / 微逆 / 大储 PCS")}{LEAF}占比上升。{LEAF_END}'
))

parts.append(subhead("三个主战场"))
parts.append(ordered_list([
    f'{b("欧洲")}{LEAF}（20.72 亿美元，仍是第一大），西班牙、荷兰等地高温带动户用，气价/电价波动 + 自主供电诉求；核心标的：德业（户储）、阳光（户用 + 大储）{LEAF_END}',
    f'{b("亚太")}{LEAF}（18.32 亿美元），澳大利亚 \"家用电池计划\" 补贴 + 印度/东南亚分布式起量；核心标的：禾迈/昱能（微逆）、阳光、上能{LEAF_END}',
    f'{b("中东 + 拉美")}{LEAF}，大型地面项目集中落地，阳光海外大储订单主战场之一{LEAF_END}',
]))

parts.append(subhead("海外占比已是头部公司命脉"))
parts.append(table(
    ["公司", "2026 H1 海外收入占比"],
    [
        ["阳光电源", "73.40%"],
        ["上能电气", "60.52%"],
    ]
))

parts.append(p(
    f'{LEAF}海外占比高 ≠ 抗风险，反而是{LEAF_END}{u("单点风险敞口大")}'
    f'{LEAF}。一旦欧美对华光伏/储能政策收紧，影响直接。但 2026 年至今，'
    f'欧美政策方向是支持户储自主供电，{LEAF_END}'
    f'{u("窗口期仍在")}{LEAF}。{LEAF_END}'
))

parts.append(section_divider())

# ===== 章节 04 储能 + AIDC =====
parts.append(section_header("04", "STORAGE + AIDC", "储能 + AIDC：被低估的新增长极"))

parts.append(quote_gold("储能已不是 \"配套业务\"，而是和逆变器平起平坐、甚至更大的主业。"))

parts.append(subhead("1) 储能：已取代逆变器成阳光电源第一大收入"))
parts.append(table(
    ["公司", "储能业务", "逆变器业务"],
    [
        ["阳光电源", "154.56 亿（50% 主营）", "123.88 亿，毛利 42.72%"],
        ["德业股份", "电池包 48.94 亿（+244%）", "51.32 亿（+94%）"],
        ["上能电气", "PCS 5.99 亿（+6.88%）", "21.98 亿（+39.36%）"],
        ["思格新能源", "营收 98.7 亿（+261.2%）", "—"],
    ]
))

parts.append(subhead("2) AIDC 电源 + 配储：真正的新极"))
parts.append(quote_block(
    "阳光电源 2026-08-28 机构交流纪要",
    f'{LEAF}\"{LEAF_END}{b("公司预计 AIDC 相关业务明后年开始增速可能会非常高")}{LEAF}\"，具体两块业务：'
    f'{LEAF}{LEAF_END}<br><br>'
    f'{LEAF}① AIDC 配储：目前在手订单约{LEAF_END}{u("2GWh")}'
    f'{LEAF}，跟进中项目{LEAF_END}{u("十几个 GWh")}{LEAF}；{LEAF_END}<br>'
    f'{LEAF}② AIDC 电源：全球真正投入实际应用的 SST（固态变压器）目前还没有，'
    f'公司已向客户{LEAF_END}{u("交付数台")}{LEAF}。{LEAF_END}<br><br>'
    f'{LEAF}来源：{LEAF_END}{link("人民财讯 2026-08-29", "https://stcn.com/article/detail/4161531.html")}'
))

parts.append(p(
    f'{LEAF}按 0.5 元/Wh 估算，{LEAF_END}{b("6 亿在手 + 50 亿潜在")}'
    f'{LEAF} 的盘子已挂在管道里。SST 全球无量产玩家，阳光是真正的卡位。{LEAF_END}'
))

parts.append(subhead("3) 禾迈之鉴：转型期的代价"))
parts.append(p(
    f'{LEAF}禾迈股份（微逆龙头）2026 H1：营收 17.80 亿（+77.09%），归母净利{LEAF_END}'
    f'{u("−1.64 亿")}{LEAF}（由盈转亏）。公司从单一微逆设备供应商向{LEAF_END}'
    f'{u("光储解决方案供应商")}{LEAF}转型，研发、渠道、市场投入大幅增加。{LEAF_END}'
))
parts.append(quote_gold("储能 PCS + 系统集成的门槛比卖逆变器高得多，没有渠道和工程能力的厂商会被拖着走。"))

parts.append(section_divider())

# ===== 章节 05 标的梳理 =====
parts.append(section_header("05", "TARGETS", "标的梳理：四档定位"))

parts.append(table(
    ["档位", "公司", "核心逻辑", "风险"],
    [
        ["第一梯队（龙头）", "阳光电源 300274", "储能已超逆变器 + AIDC 双卡位", "海外政策、集中式价格战"],
        ["第一梯队（户储）", "德业股份 605117", "电池包 +244%，逆变器 +94%", "欧洲补贴退坡"],
        ["第一梯队（增速）", "思格新能源", "营收 +261%、净利 +201%", "估值预期已高"],
        ["第二梯队（出海+PCS）", "上能电气 300827", "海外 60.52%，PCS 业务稳", "PCS 价格战"],
        ["第二梯队（微逆）", "禾迈股份 688032", "转型期阵痛，2026 H1 亏损", "转型能否兑现"],
        ["第二梯队（组串）", "锦浪、固德威", "出口+组串逆变器中性增长", "行业洗牌"],
        ["观察", "微逆其余、户储二三线", "营收腰斩或亏损", "洗牌出清"],
    ]
))

parts.append(section_divider())

# ===== 章节 06 Q3 拐点 =====
parts.append(section_header("06", "Q3 TURNING POINT", "Q3 拐点：等哪三个数据"))

parts.append(p(
    f'{LEAF}原文的核心结论——{LEAF_END}{b("需要等 Q3 出货数据确认拐点")}'
    f'{LEAF}。具体盯三个数：{LEAF_END}'
))

parts.append(ordered_list([
    f'{b("阳光电源 Q3 储能出货环比")}{LEAF}：若 Q3 储能营收 > Q2（约 77 亿），确认国内大储拐点{LEAF_END}',
    f'{b("11 家行业 Q3 合计净利同比")}{LEAF}：若从 −4.48% 收窄到 0 轴以上，确认板块整体拐点{LEAF_END}',
    f'{b("欧洲户储出口额 7-9 月")}{LEAF}：若维持 6 月单月 > 3.5 亿美元，确认出口结构性向好{LEAF_END}',
]))

parts.append(quote_gold("任一确认，板块 β 修复；全部确认，龙头 α 行情启动。"))

parts.append(section_divider())

# ===== 章节 07 风险提示 =====
parts.append(section_header("07", "RISKS", "风险提示"))

parts.append(ordered_list([
    f'{b("欧美对华光伏/储能政策")}{LEAF}：关税、贸易壁垒可能瞬间翻转窗口期{LEAF_END}',
    f'{b("电芯价格波动")}{LEAF}：阳光储能毛利率已下滑 7.49pct，原材料价格反向波动是双刃剑{LEAF_END}',
    f'{b("集中式光伏国内并网节奏")}{LEAF}：若配储要求再加码，IRR 进一步下降，二三线先扛不住{LEAF_END}',
    f'{b("AIDC 业务兑现节奏")}{LEAF}：阳光目前 SST 交付数台，\"明后年高增速\" 是远期预期，不能折现到现在{LEAF_END}',
]))

parts.append(section_divider())

# ===== 章节 ∞ 结语 =====
parts.append(f'''<section style="margin-top:56px;margin-bottom:32px;padding:0 10px;">
  <section style="position:relative;padding-bottom:20px;border-bottom:1px solid #E4E4E7;">
    <p style="font-size:48px;font-weight:900;color:#E4E4E7;margin:0;line-height:1;letter-spacing:-2px;">{LEAF}∞{LEAF_END}</p>
    <section style="margin-top:-8px;">
      <p style="font-size:10px;color:#A1A1AA;font-weight:500;letter-spacing:3px;margin:0 0 6px;text-transform:uppercase;">{LEAF}EPILOGUE{LEAF_END}</p>
      <h3 style="font-size:20px;font-weight:800;color:#27272A;margin:0;letter-spacing:0.5px;line-height:1.4;">{LEAF}为什么说「比风电更值得左侧布局」{LEAF_END}</h3>
    </section>
  </section>
</section>''')

parts.append(p(
    f'{LEAF}风电板块逻辑是{LEAF_END}{b("\"政策 + 招标\" 双轮驱动")}'
    f'{LEAF}，确定性高，但估值也已经反映了——7 月单月风电新增装机 +271% 是兑现，不是预期。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}逆变器板块逻辑是{LEAF_END}{b("\"左侧 + 拐点\"")}{LEAF}：{LEAF_END}'
))
parts.append(ordered_list([
    f'{b("行业净利润已经负增长")}{LEAF}：最坏时点正在过去{LEAF_END}',
    f'{b("头部公司份额已 95% 集中")}{LEAF}：剩者为王{LEAF_END}',
    f'{b("储能 + AIDC 提供新的成长曲线")}{LEAF}：不是单纯修估值{LEAF_END}',
]))
parts.append(p(
    f'{LEAF}当一个行业从{LEAF_END}{u("\"全面负增长\"")}{LEAF}中走出第一根阳线，'
    f'{LEAF_END}{u("反弹弹性往往大于估值已修复的板块")}{LEAF}。但前提是{LEAF_END}'
    f'{LEAF}Q3 出货数据必须确认。否则就是{LEAF_END}'
    f'{b("等不到拐点的左侧陷阱")}{LEAF}。{LEAF_END}'
))

# 8. END
parts.append(end_section())

# 9. 签名（用占位）
parts.append(signature())

# 10. 相关文章
parts.append('''<section style="padding:0 10px 24px;">
  <p style="font-size:11px;color:#A1A1AA;letter-spacing:2px;margin:0 0 14px;">
    {leaf}RELATED READS{leaf_end}
  </p>
  <p style="font-size:15px;line-height:1.8;color:#52525B;margin:0 0 8px;text-align:justify;">
    {leaf}您或许也对以下文章感兴趣：{leaf_end}
  </p>
  <p style="font-size:13px;color:#A1A1AA;line-height:1.7;margin:0;text-align:justify;letter-spacing:0.3px;">
    {leaf}👉 相关文章手动插入位（使用公众号编辑器右侧「图文 / 链接 / 专辑」按钮插入 2–5 条同主题往期文章）。{leaf_end}
  </p>
</section>'''.format(leaf=LEAF, leaf_end=LEAF_END))

# 11. 名片
parts.append('''<section data-slot="WECHAT_CARD" style="padding:0 10px 28px;border:1px dashed #A1A1AA;border-radius:4px;">
  <p style="font-size:11px;color:#A1A1AA;letter-spacing:2px;margin:0 0 12px;">
    {leaf}FOLLOW US{leaf_end}
  </p>
  <p style="font-size:15px;line-height:1.8;color:#52525B;margin:0;text-align:justify;">
    {leaf}不想错过下一篇？在本段虚线框内，将鼠标光标停在两个虚线框之间，点公众号编辑器右侧的「{leaf_end}
    <strong style="color:#27272A;">{leaf}插入公众号名片{leaf_end}</strong>
    {leaf}」按钮（不是「插入图片」），选 ZEN 后插入到本段位置。{leaf_end}
  </p>
  <p style="font-size:12px;color:#A1A1AA;margin:8px 0 0;letter-spacing:0.3px;line-height:1.7;text-align:justify;">
    {leaf}提示：本提示文案可手动删除。虚线框仅用于定位，发布时可点框后按 Delete 键连框一起删除。{leaf_end}
  </p>
</section>'''.format(leaf=LEAF, leaf_end=LEAF_END))

# 全局容器结尾
parts.append('</section>')

html = '\n'.join(parts)

out_dir = Path(__file__).resolve().parent
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "排版_石墨极简风(graphite-minimal).html"
out_path.write_text(html, encoding='utf-8')
print(f"OK -> {out_path}")
print(f"size: {out_path.stat().st_size} bytes")