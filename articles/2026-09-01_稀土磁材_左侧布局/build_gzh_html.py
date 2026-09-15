#!/usr/bin/env python3
"""稀土磁材文章 → 石墨极简风公众号 HTML"""

import re
from pathlib import Path

GRAY = "#52525B"
DARK = "#27272A"
LIGHT = "#A1A1AA"
LINE = "#E4E4E7"
BG = "#FAFAFA"

LEAF = '<span leaf="">'
LEAF_END = '</span>'

def p(text, **kw):
    style = kw.get("style", "margin-bottom:22px;font-size:15px;line-height:1.8;text-align:justify;color:#52525B;letter-spacing:0.3px;")
    return f'<p style="{style}">{text}</p>'

def u(s):
    return f'<span style="border-bottom:2px solid #52525B;font-weight:600;color:#27272A;">{LEAF}{s}{LEAF_END}</span>'

def b(s):
    return f'<strong style="color:#27272A;">{LEAF}{s}{LEAF_END}</strong>'

def orange_u(s):
    return f'<span style="border-bottom:2px solid #F97316;font-weight:700;color:#27272A;">{LEAF}{s}{LEAF_END}</span>'

def link(s, url):
    return f'<a href="{url}" target="_blank" style="color:#52525B;border-bottom:1px solid #A1A1AA;">{LEAF}{s}{LEAF_END}</span></a>'.replace('</span></a>', '</a>')

def section_header(num, en, title, end_marker=False):
    actual_num = '∞' if end_marker else num
    return f'''<section style="margin-top:56px;margin-bottom:32px;padding:0 10px;">
  <section style="position:relative;padding-bottom:20px;border-bottom:1px solid #E4E4E7;">
    <p style="font-size:48px;font-weight:900;color:#E4E4E7;margin:0;line-height:1;letter-spacing:-2px;">{LEAF}{actual_num}{LEAF_END}</p>
    <section style="margin-top:-8px;">
      <p style="font-size:10px;color:#A1A1AA;font-weight:500;letter-spacing:3px;margin:0 0 6px;text-transform:uppercase;">{LEAF}{en}{LEAF_END}</p>
      <h3 style="font-size:20px;font-weight:800;color:#27272A;margin:0;letter-spacing:0.5px;line-height:1.4;">{LEAF}{title}{LEAF_END}</h3>
    </section>
  </section>
</section>'''

def section_divider():
    return '''<section style="padding:0 10px;">
  <section style="height:1px;background:#E4E4E7;margin:0;"><span leaf=""><br></span></section>
</section>'''

def data_card(num, label, color="#27272A", last=False):
    mr = 'margin-right:0;' if last else 'margin-right:8px;'
    return f'''<section style="flex:1;border:1px solid #E4E4E7;padding:22px 16px;{mr}text-align:center;">
    <p style="font-size:32px;font-weight:900;color:{color};margin:0 0 6px;line-height:1;letter-spacing:-1px;">{LEAF}{num}{LEAF_END}</p>
    <p style="font-size:11px;color:#A1A1AA;margin:0;letter-spacing:1px;">{LEAF}{label}{LEAF_END}</p>
  </section>'''

def two_col_data(d1, l1, d2, l2, d2_color="#F97316"):
    return f'''<section style="display:flex;margin:0 10px 28px;">{data_card(d1, l1)}{data_card(d2, l2, d2_color, last=True)}
</section>'''

def quote_gold(s):
    return f'''<section style="border-left:3px solid #52525B;padding:16px 0 16px 24px;margin:0 10px 28px;">
  <p style="font-size:16px;font-weight:700;color:#27272A;margin:0;line-height:1.7;letter-spacing:0.5px;">{LEAF}「{s}」{LEAF_END}</p>
</section>'''

def quote_block(tag, content):
    return f'''<section style="background:#FAFAFA;border:1px solid #E4E4E7;padding:20px 22px;margin:0 10px 28px;">
  <p style="font-size:11px;color:#A1A1AA;margin:0 0 8px;letter-spacing:2px;font-weight:500;">{LEAF}{tag}{LEAF_END}</p>
  <p style="font-size:15px;color:#3F3F46;margin:0;line-height:1.8;text-align:justify;">{content}</p>
</section>'''

def table(headers, rows):
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
    out_html = '<section style="margin-bottom:24px;">'
    for i, item in enumerate(items, 1):
        out_html += f'''<section style="display:flex;align-items:flex-start;gap:10px;margin-bottom:12px;">
    <span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;background:#27272A;color:#fff;font-size:12px;font-weight:700;border-radius:50%;flex-shrink:0;margin-top:2px;">{LEAF}{i}{LEAF_END}</span>
    <p style="font-size:15px;color:#52525B;margin:0;line-height:1.8;flex:1;">{item}</p>
  </section>'''
    out_html += '</section>'
    return out_html

def subhead(s):
    return f'<p style="font-size:15px;font-weight:800;color:#27272A;margin:28px 0 14px;padding-left:12px;border-left:3px solid #52525B;line-height:1.4;">{LEAF}{s}{LEAF_END}</p>'

def end_section():
    return '''<section style="padding:0 10px;">
  <section style="text-align:center;margin:0 0 36px;">
    <section style="display:flex;align-items:center;justify-content:center;">
      <span style="height:1px;width:48px;background:#E4E4E7;margin-right:16px;">{leaf}<br>{leaf_end}</span>
      <span style="font-size:10px;color:#A1A1AA;letter-spacing:4px;font-weight:500;">{leaf}END{leaf_end}</span>
      <span style="height:1px;width:48px;background:#E4E4E7;margin-left:16px;">{leaf}<br>{leaf_end}</span>
    </section>
  </section>
</section>'''.format(leaf=LEAF, leaf_end=LEAF_END)

def signature_zen():
    return '''<section style="padding:0 10px 24px;">
  <section style="border-top:1px solid #E4E4E7;padding-top:28px;">
    <p style="margin-bottom:16px;font-size:15px;line-height:1.8;color:#52525B;text-align:justify;">
      {leaf}我是{leaf_end}
      <strong style="color:#27272A;">{leaf}退休前后{leaf_end}</strong>
      {leaf}，一个关注 A 股产业变革的中年投资者。本号日常跟踪风电、光伏、储能、半导体等行业的拐点信号。{leaf_end}
    </p>
    <p style="margin-bottom:0;font-size:15px;line-height:1.8;color:#52525B;text-align:justify;">
      {leaf}如果你觉得今天这篇有收获，欢迎{leaf_end}
      <strong style="color:#27272A;">{leaf}点赞、在看、转发{leaf_end}</strong>
      {leaf}三连，我们下篇见。{leaf_end}
    </p>
  </section>
</section>'''.format(leaf=LEAF, leaf_end=LEAF_END)

def disclaimer():
    """投资/产业分析类必加的 DISCLAIMER 区块"""
    return '''<section data-slot="DISCLAIMER" style="padding:0 10px 24px;border-top:1px dashed #E4E4E7;">
  <p style="font-size:11px;color:#A1A1AA;letter-spacing:2px;margin:14px 0 8px;">
    <span leaf="">DISCLAIMER</span>
  </p>
  <p style="font-size:12px;color:#A1A1AA;line-height:1.7;margin:0;text-align:justify;letter-spacing:0.3px;">
    <span leaf="">本文为个人投资观察与公开信息整理，不构成任何投资建议。所提及标的仅供研究讨论，不构成买入、卖出或持有的推荐。市场有风险，投资需谨慎。请读者基于自身风险承受能力和独立判断做出决策。</span>
  </p>
</section>'''.replace('<span leaf="">', LEAF).replace('</span>', LEAF_END, 1)

# ============= 装配全文 =============
parts = []

parts.append('<section style="max-width:677px;margin:0 auto;background:#FFFFFF;font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Hiragino Sans GB\',\'Microsoft YaHei\',sans-serif;color:#52525B;line-height:1.8;letter-spacing:0.3px;overflow-x:hidden;">')

# 引言卡
parts.append(f'''<section style="margin:10px 10px 40px;padding:32px 24px 24px;border-top:1px solid #E4E4E7;border-bottom:1px solid #E4E4E7;background:#FFFFFF;">
  <p style="font-size:11px;color:#A1A1AA;letter-spacing:2px;margin:0 0 18px;font-weight:400;">{LEAF}QUOTE{LEAF_END}</p>
  <p style="font-size:18px;font-weight:700;color:#27272A;margin:0 0 8px;line-height:1.7;letter-spacing:0.5px;">
    {LEAF}稀土价格已经{LEAF_END}
    {u("被供给端封死下行")}
    {LEAF}，金属厂倒挂、停产未复产。剩下的唯一变量是{LEAF_END}
    {orange_u("旺季订单能否兑现")}
    {LEAF}。{LEAF_END}
  </p>
  <p style="text-align:right;font-size:12px;color:#A1A1AA;margin:16px 0 0;letter-spacing:1px;">
    {LEAF}—— 数据截至 2026-09-01{LEAF_END}
  </p>
</section>''')

# 前言正文
parts.append(p(
    f'{LEAF}这是一篇基于 2026-09-01 中信证券稀土磁材研报的板块梳理。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}如果只看一句话：{LEAF_END}{u("供给收紧逻辑已成立")}{LEAF}，'
    f'金九银十订单 + 机器人长期增量是看点。但板块已经反弹 + 美联储鹰派压制估值，'
    f'纯估值修复行情走不远，{LEAF_END}{orange_u("等 Q4 数据验证")}{LEAF}。{LEAF_END}'
))

# 导读
parts.append('''<section style="padding:0 10px 40px;">
  <p style="font-size:11px;color:#A1A1AA;margin:0 0 16px;letter-spacing:2px;">
    <leaf style="display:none;"></leaf><span leaf="">本文看点</span>
  </p>
  <section style="display:flex;justify-content:space-between;">
    <section style="flex:1;background:#FAFAFA;border-top:1px solid #E4E4E7;padding:18px 12px 16px;margin-right:8px;">
      <p style="font-size:11px;color:#A1A1AA;font-weight:500;margin:0 0 8px;letter-spacing:1px;">{leaf}01{leaf_end}</p>
      <p style="font-size:13px;font-weight:700;color:#27272A;margin:0;line-height:1.5;">{leaf}板块表现与估值分位{leaf_end}</p>
    </section>
    <section style="flex:1;background:#FAFAFA;border-top:1px solid #E4E4E7;padding:18px 12px 16px;margin-right:8px;">
      <p style="font-size:11px;color:#A1A1AA;font-weight:500;margin:0 0 8px;letter-spacing:1px;">{leaf}02{leaf_end}</p>
      <p style="font-size:13px;font-weight:700;color:#27272A;margin:0;line-height:1.5;">{leaf}供给收紧循环 + 价格信号{leaf_end}</p>
    </section>
    <section style="flex:1;background:#FAFAFA;border-top:1px solid #E4E4E7;padding:18px 12px 16px;">
      <p style="font-size:11px;color:#A1A1AA;font-weight:500;margin:0 0 8px;letter-spacing:1px;">{leaf}03{leaf_end}</p>
      <p style="font-size:13px;font-weight:700;color:#27272A;margin:0;line-height:1.5;">{leaf}标的梳理 + Q4 验证信号{leaf_end}</p>
    </section>
  </section>
</section>'''.format(leaf=LEAF, leaf_end=LEAF_END))

# 01 一句话总结
parts.append(section_header("01", "OVERVIEW", "一句话总结"))
parts.append(two_col_data(
    "+1.38%", "本周稀土磁材板块涨幅",
    "+1.59pct", "跑赢沪深 300"
))
parts.append(p(
    f'{LEAF}本周稀土磁材板块反弹 {LEAF_END}{b("1.38%")}'
    f'{LEAF}，跑赢沪深 300 指数 {LEAF_END}{b("1.59 个百分点")}'
    f'{LEAF}；行业市盈率降至 {LEAF_END}{b("53.06 倍")}'
    f'{LEAF}，处于历史 {LEAF_END}{b("45.3% 分位")}{LEAF}。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}估值不算便宜，但也没到极端位置。{LEAF_END}'
    f'{LEAF}更值得关注的是价格信号：中重稀土（氧化镝、氧化铽）继续上行，{LEAF_END}'
    f'{u("金属厂已普遍倒挂并出现减产")}{LEAF}，分离企业开工稳定但前期停产者暂未复产。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}叠加磁材大厂开工稳定 + 金九银十旺季订单有望释放，研报观点：{LEAF_END}'
    f'{u("稀土价格有望震荡上行")}{LEAF}，上游资源企业和优质磁材厂商盈利修复可期。{LEAF_END}'
))
parts.append(section_divider())

# 02 板块表现与估值
parts.append(section_header("02", "VALUATION", "板块表现与估值"))
parts.append(table(
    ["指标", "数值", "解读"],
    [
        ["本周板块涨幅", "+1.38%", "反弹力度中性"],
        ["沪深 300 同期", "−0.21%", "跑赢 1.59 pct"],
        ["行业 PE（TTM）", "53.06 倍", "历史 45.3% 分位"],
        ["估值压制因素", "美联储鹰派", "短期压制估值修复"],
    ]
))
parts.append(p(
    f'{LEAF}板块已经反弹 + 估值分位不算极低 + 美联储仍鹰，{LEAF_END}'
    f'{u("单纯的估值修复行情走不远")}{LEAF}，需要看价格能否兑现。{LEAF_END}'
))
parts.append(section_divider())

# 03 价格信号
parts.append(section_header("03", "PRICES", "价格信号：中重稀土强、镨钕稳、钕铁硼毛坯回调"))

parts.append(subhead("三大类价格走势"))
parts.append(table(
    ["品种", "走势", "备注"],
    [
        ["氧化镝", "+2.47%（本周）", "中重稀土代表，持续上行"],
        ["氧化铽", "+1.42%（本周）", "中重稀土，跟涨"],
        ["中钇富铕矿、缅甸离子矿", "小幅走高", "上游矿端信号"],
        ["镨钕系", "坚挺微涨", "72.5–73.1 万元/吨"],
        ["钕铁硼毛坯", "由涨转跌 −0.4%~−0.5%", "下游对高价接受度差"],
    ]
))

parts.append(subhead("解读"))
parts.append(p(
    f'{LEAF}{b("中重稀土走强")}{LEAF}：氧化镝近期累计涨幅已超 4%，现货紧张 + 军工/高端磁材需求支撑。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}{b("镨钕微涨")}{LEAF}：新能源车、风电主原料，价格稳在 72–73 万/吨。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}{b("钕铁硼毛坯回调")}{LEAF}，{LEAF_END}'
    f'{u("下游对高价接受度差")}{LEAF}，是短期负面信号，中游加工环节利润承压。{LEAF_END}'
))
parts.append(quote_gold("最值得盯的指标：钕铁硼毛坯价能否企稳。持续回调意味着需求端没起来。"))
parts.append(section_divider())

# 04 供给端
parts.append(section_header("04", "SUPPLY", "供给端：金属厂倒挂、分离企业未复产"))

parts.append(quote_block(
    "中信证券 2026-09-01 研报",
    f'{LEAF}{b("\"当前供应端持续收紧：分离企业开工稳定但前期停产者暂未复产，氧化物现货紧张；金属厂普遍倒挂，已出现减产迹象，后期供应增量有限。\"")}{LEAF_END}'
))

parts.append(subhead("翻译"))
parts.append(p(
    f'{LEAF}分离企业：开工稳定（不增产） + 前期停产者不复产 → {LEAF_END}'
    f'{u("供给上限被锁")}{LEAF_END}'
))
parts.append(p(
    f'{LEAF}金属厂：成本 > 售价 → 减产 → 进一步收紧供给{LEAF_END}'
))
parts.append(p(
    f'{LEAF}这两条叠加意味着：{LEAF_END}{u("稀土价格的下行空间被供给端封死")}{LEAF_END}'
))

parts.append(subhead("为什么金属厂会倒挂"))
parts.append(ordered_list([
    f'{b("上游氧化物涨价")}{LEAF} → 金属厂采购成本涨{LEAF_END}',
    f'{b("下游磁材厂不接高价")}{LEAF} → 金属厂售价无法同步传导{LEAF_END}',
    f'{b("倒挂")}{LEAF} → 减产 → 现货进一步紧张 → 氧化物价格进一步上行{LEAF_END}',
]))
parts.append(p(
    f'{LEAF}这是个自我强化的供给收紧循环。{LEAF_END}'
    f'{LEAF}只要下游磁材厂持续抵触，毛坯价就承压，但氧化物价格反而会被推高。{LEAF_END}'
))
parts.append(section_divider())

# 05 需求端
parts.append(section_header("05", "DEMAND", "需求端：短期偏淡，但旺季订单有望释放"))

parts.append(subhead("短期"))
parts.append(p(
    f'{LEAF}下游磁材厂{LEAF_END}{u("\"买涨不买跌\" 情绪")}'
    f'{LEAF}，涨价时备货，降价时观望，导致短期现货成交清淡。{LEAF_END}'
))

parts.append(subhead("旺季预期"))
parts.append(ordered_list([
    f'{b("磁材大厂开工整体稳定")}{LEAF_END}',
    f'{b("金九银十")}{LEAF}是新能源汽车 + 风电 + 工业电机旺季{LEAF_END}',
    f'{b("订单有望逐步释放")}{LEAF_END}',
]))

parts.append(subhead("长期支撑"))
parts.append(ordered_list([
    f'{b("新能源车永磁电机")}{LEAF}（驱动电机仍是主流路线）{LEAF_END}',
    f'{b("风电直驱永磁发电机")}{LEAF_END}',
    f'{b("人形机器人伺服电机")}{LEAF}（新增需求，金力永磁已布局）{LEAF_END}',
    f'{b("工业自动化 / 数控机床")}{LEAF_END}',
]))
parts.append(p(
    f'{LEAF}{b("长期需求增量")}{LEAF}比金九银十更值得重视。人形机器人一旦起量，'
    f'单台电机用磁材量虽小，但单机数量级是新能源车的 100 倍。{LEAF_END}'
))
parts.append(section_divider())

# 06 美联储鹰派
parts.append(section_header("06", "FED", "美联储鹰派是\"短期压制\""))
parts.append(quote_block(
    "中信证券",
    f'{LEAF}{b("\"美联储鹰派表态短期压制估值，但国内地产新政利好下游传统需求，形成对冲。\"")}{LEAF_END}'
))
parts.append(p(
    f'{LEAF}鹰派 → 全球流动性预期收紧 → 高估值板块承压。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}国内地产新政 → 传统需求（家电、五金、电梯）回暖 → 对冲负面影响。{LEAF_END}'
))
parts.append(p(
    f'{LEAF}{b("美联储因素是估值层面的，不是基本面层面的")}{LEAF}。{LEAF_END}'
    f'{LEAF}基本面看供给收紧 + 旺季需求，足以覆盖估值压制。{LEAF_END}'
))
parts.append(section_divider())

# 07 核心标的
parts.append(section_header("07", "TARGET", "核心标的：金力永磁（300748）"))

parts.append(table(
    ["指标", "数值"],
    [
        ["营业收入（H1）", "46.49 亿元（+32.57% 同比）"],
        ["归母净利润（H1）", "4.62 亿元（+51.58% 同比）"],
        ["产能（高性能钕铁硼）", "4 万吨/年"],
        ["产能规划（2027 年底）", "6 万吨/年"],
        ["新方向", "人形机器人电机转子"],
    ]
))

parts.append(subhead("为什么被点"))
parts.append(ordered_list([
    f'{b("客户结构")}{LEAF}：新能源车 + 风电 + 工业电机 + 机器人，四大下游均衡，单一行业风险低{LEAF_END}',
    f'{b("产能利用率高")}{LEAF}：4 万吨已满产，新增 2 万吨产能 2027 年投产{LEAF_END}',
    f'{b("机器人卡位")}{LEAF}：人形机器人电机转子是新增长曲线，对标特斯拉 Optimus、宇树供应链{LEAF_END}',
]))
parts.append(p(
    f'{LEAF}{b("风险")}{LEAF}：上半年净利 +51.58% 已反映部分预期，估值不算便宜（PE 估计仍在 40-50 倍区间）。{LEAF_END}'
))
parts.append(section_divider())

# 08 其他标的
parts.append(section_header("08", "OTHERS", "其他关注标的"))
parts.append(table(
    ["标的", "代码", "主营", "看点"],
    [
        ["北方稀土", "600111", "轻稀土龙头", "镨钕主供应商，业绩弹性大"],
        ["中国稀土", "000831", "中重稀土龙头", "氧化镝、氧化铽涨价直接受益"],
        ["盛和资源", "600392", "稀土 + 锆钛", "缅甸矿进口受限受益"],
        ["中科三环", "000970", "钕铁硼磁材", "新能源车客户为主"],
        ["正海磁材", "300224", "钕铁硼磁材", "风电客户结构"],
        ["宁波韵升", "600366", "钕铁硼磁材", "工业电机 + 新能源车"],
    ]
))
parts.append(section_divider())

# 09 Q4 验证信号
parts.append(section_header("09", "Q4 SIGNALS", "Q4 验证信号：盯哪几个数"))
parts.append(ordered_list([
    f'{b("氧化镝周价")}{LEAF}：如果继续涨 1% 以上，确认中重稀土景气{LEAF_END}',
    f'{b("金属厂开工率")}{LEAF}（SMM 周报）：如果持续下降，确认供给收紧逻辑{LEAF_END}',
    f'{b("磁材大厂出货环比")}{LEAF}：金力永磁 9 月排产数据，旺季兑现度{LEAF_END}',
    f'{b("钕铁硼毛坯价")}{LEAF}：能否企稳，下游接受度的关键信号{LEAF_END}',
]))
parts.append(quote_gold("任一确认，板块 β 修复；全部确认，龙头 α 行情启动。"))
parts.append(section_divider())

# 10 风险
parts.append(section_header("10", "RISKS", "风险提示"))
parts.append(ordered_list([
    f'{b("美联储超预期鹰派")}{LEAF}：估值压制时间拉长{LEAF_END}',
    f'{b("钕铁硼毛坯持续回调")}{LEAF}：下游需求没起来，中游磁材厂利润进一步承压{LEAF_END}',
    f'{b("稀土配额松动")}{LEAF}：供给侧政策出现意外变化{LEAF_END}',
    f'{b("新能源车销量不及预期")}{LEAF}：金九银十旺季订单释放受阻{LEAF_END}',
    f'{b("机器人产业化进度低于预期")}{LEAF}：长期增长曲线兑现延后{LEAF_END}',
]))
parts.append(section_divider())

# ∞ 结语
parts.append(section_header("∞", "EPILOGUE", "左侧跟踪 + 右侧追涨组合", end_marker=True))

parts.append(p(
    f'{LEAF}{b("稀土磁材板块现在更适合\"左侧跟踪 + 右侧追涨\"组合")}{LEAF}：{LEAF_END}'
))
parts.append(ordered_list([
    f'{b("左侧")}{LEAF}：行业供给收紧逻辑已经形成，金属厂倒挂、停产未复产是事实{LEAF_END}',
    f'{b("右侧")}{LEAF}：板块已经涨了 1.38%，本周再追的安全边际不高{LEAF_END}',
]))

parts.append(subhead("操作思路"))
parts.append(ordered_list([
    f'{b("上游资源")}{LEAF}（北方稀土、中国稀土、盛和资源）：受益于氧化物涨价，弹性大，等回调介入{LEAF_END}',
    f'{b("中游磁材龙头")}{LEAF}（金力永磁）：客户结构优、产能利用率高，{LEAF_END}{u("等 9 月排产数据兑现")}{LEAF}{LEAF_END}',
    f'{b("人形机器人卡位")}{LEAF}：金力永磁 + 宁波韵升，看长期不看短期{LEAF_END}',
]))
parts.append(p(
    f'{LEAF}{b("前提")}{LEAF}：Q4 价格信号 + 旺季订单数据持续验证。否则就是{LEAF_END}'
    f'{u("\"涨价一日游\"")}{LEAF}的反弹陷阱。{LEAF_END}'
))

# END
parts.append(end_section())

# 签名
parts.append(signature_zen())

# 免责声明（投资/产业分析类必加）
parts.append(disclaimer())

# 相关文章
parts.append('''<section style="padding:0 10px 24px;">
  <p style="font-size:11px;color:#A1A1AA;letter-spacing:2px;margin:0 0 14px;">
    <span leaf="">RELATED READS</span>
  </p>
  <p style="font-size:15px;line-height:1.8;color:#52525B;margin:0 0 8px;text-align:justify;">
    <span leaf="">您或许也对以下文章感兴趣：</span>
  </p>
  <p style="font-size:13px;color:#A1A1AA;line-height:1.7;margin:0;text-align:justify;letter-spacing:0.3px;">
    <span leaf="">👉 相关文章手动插入位（使用公众号编辑器右侧「图文 / 链接 / 专辑」按钮插入 2–5 条同主题往期文章）。</span>
  </p>
</section>'''.replace('<span leaf="">', LEAF).replace('</span>', LEAF_END))

# 名片
parts.append(f'''<section data-slot="WECHAT_CARD" style="padding:0 10px 28px;border:1px dashed #A1A1AA;border-radius:4px;">
  <p style="font-size:11px;color:#A1A1AA;letter-spacing:2px;margin:0 0 12px;">
    {LEAF}FOLLOW US{LEAF_END}
  </p>
  <p style="font-size:15px;line-height:1.8;color:#52525B;margin:0;text-align:justify;">
    {LEAF}不想错过下一篇？在本段虚线框内，将鼠标光标停在两个虚线框之间，点公众号编辑器右侧的「{LEAF_END}
    <strong style="color:#27272A;">{LEAF}插入公众号名片{LEAF_END}</strong>
    {LEAF}」按钮（不是「插入图片」），选 ZEN 后插入到本段位置。{LEAF_END}
  </p>
  <p style="font-size:12px;color:#A1A1AA;margin:8px 0 0;letter-spacing:0.3px;line-height:1.7;text-align:justify;">
    {LEAF}提示：本提示文案可手动删除。虚线框仅用于定位，发布时可点框后按 Delete 键连框一起删除。{LEAF_END}
  </p>
</section>''')

parts.append('</section>')

html = '\n'.join(parts)

out_dir = Path("/home/axu/codex/writings/stock/articles/2026-09-01_稀土磁材_左侧布局")
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "排版_石墨极简风(graphite-minimal).html"
out_path.write_text(html, encoding='utf-8')
print(f"OK -> {out_path}")
print(f"size: {out_path.stat().st_size} bytes")