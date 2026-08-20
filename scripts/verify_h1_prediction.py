#!/usr/bin/env python3
"""
水晶光电中报预测验证工具 - 8 月 24 日中报发布后使用
用于对比预测值与实际情况的误差
"""

import json
from datetime import datetime

# 预测数据（基于本文分析）
H1_PREDICTION = {
    "revenue_range": [48.5, 50.5],  # 亿元
    "revenue_mid": 49.5,            # 中值
    "revenue_growth_low": 18,       # 最低增速
    "revenue_growth_high": 23,      # 最高增速
    
    "net_profit_range": [6.8, 7.2],  # 亿元
    "net_profit_mid": 7.0,          # 中值
    "profit_growth_low": 33,        # 最低增速
    "profit_growth_high": 41,       # 最高增速
    
    "gross_margin_low": 24.0,       # %
    "gross_margin_high": 25.0,      # %
    
    "scenario": "中性预测 (概率 50%)"
}

# 2025H1 实际数据作为基准
H1_2025_BASELINE = {
    "revenue": 41.2,
    "net_profit": 5.1,
    "gross_margin": 22.5
}

# 实际数据（待 8 月 24 日填写）
ACTUAL_DATA = {
    "revenue": None,           # 待填写
    "net_profit": None,         # 待填写
    "gross_margin": None,       # 待填写
    "report_date": None         # 待填写
}

def calculate_error(predicted, actual):
    """计算绝对误差和相对误差"""
    if predicted is None or actual is None:
        return None, None
    
    absolute_error = actual - predicted
    relative_error = (absolute_error / predicted) * 100 if predicted != 0 else 0
    
    return absolute_error, relative_error

def check_range(predicted_low, predicted_high, actual):
    """检查实际值是否在预测区间内"""
    if predicted_low is None or predicted_high is None or actual is None:
        return None, None
    
    in_range = predicted_low <= actual <= predicted_high
    if in_range:
        return "✅ 符合预测区间", "准确"
    else:
        direction = "高于预测" if actual > predicted_high else "低于预测"
        deviation = ((actual - (predicted_low + predicted_high) / 2) / ((predicted_high - predicted_low) / 2)) * 100
        return f"❌ 超出预测区间 ({direction})", f"偏差{deviation:.1f}%"

def generate_verification_report():
    """生成验证报告"""
    report = f"""
# 水晶光电 2026 中报预测验证报告

**统计日期**: {ACTUAL_DATA['report_date'] or '待 8 月 24 日中报发布'}  
**作者**: LeisureLinux

---

## 📊 营收验证

### 预测值
- 预测区间：**{H1_PREDICTION['revenue_range'][0]} - {H1_PREDICTION['revenue_range'][1]} 亿元**
- 预测中值：**{H1_PREDICTION['revenue_mid']} 亿元**
- 同比增速预测：**+{H1_PREDICTION['revenue_growth_low']}% ~ +{H1_PREDICTION['revenue_growth_high']}%**

### 实际值
- **实际营收**: {ACTUAL_DATA['revenue']} 亿元 (待填写)
- 实际增速：{get_growth(ACTUAL_DATA['revenue'], H1_2025_BASELINE['revenue'])}%

### 误差分析
{get_error_analysis(H1_PREDICTION['revenue_mid'], ACTUAL_DATA['revenue'], "营收") if ACTUAL_DATA['revenue'] else "未发布中报，等待 8 月 24 日..."}

---

## 💰 净利润验证

### 预测值
- 预测区间：**{H1_PREDICTION['net_profit_range'][0]} - {H1_PREDICTION['net_profit_range'][1]} 亿元**
- 预测中值：**{H1_PREDICTION['net_profit_mid']} 亿元**
- 同比增速预测：**+{H1_PREDICTION['profit_growth_low']}% ~ +{H1_PREDICTION['profit_growth_high']}%**

### 实际值
- **实际净利润**: {ACTUAL_DATA['net_profit']} 亿元 (待填写)
- 实际增速：{get_growth(ACTUAL_DATA['net_profit'], H1_2025_BASELINE['net_profit'])}%

### 误差分析
{get_error_analysis(H1_PREDICTION['net_profit_mid'], ACTUAL_DATA['net_profit'], "净利润") if ACTUAL_DATA['net_profit'] else "未发布中报，等待 8 月 24 日..."}

---

## 📈 毛利率验证

### 预测值
- 预测区间：**{H1_PREDICTION['gross_margin_low']}% - {H1_PREDICTION['gross_margin_high']}%**

### 实际值
- **实际毛利率**: {ACTUAL_DATA['gross_margin']}% (待填写)

### 误差分析
{get_error_analysis((H1_PREDICTION['gross_margin_low'] + H1_PREDICTION['gross_margin_high']) / 2, ACTUAL_DATA['gross_margin'], "毛利率") if ACTUAL_DATA['gross_margin'] else "未发布中报，等待 8 月 24 日..."}

---

## 🎯 综合评估

| 指标 | 预测区间 | 实际值 | 误差 | 准确度 |
|------|----------|--------|------|--------|
| 营收 (亿元) | {H1_PREDICTION['revenue_range']} | {ACTUAL_DATA['revenue']} | {get_error_percent(H1_PREDICTION['revenue_mid'], ACTUAL_DATA['revenue'])}% | {check_range_accuracy(H1_PREDICTION['revenue_range'], ACTUAL_DATA['revenue'])} |
| 净利润 (亿元) | {H1_PREDICTION['net_profit_range']} | {ACTUAL_DATA['net_profit']} | {get_error_percent(H1_PREDICTION['net_profit_mid'], ACTUAL_DATA['net_profit'])}% | {check_range_accuracy(H1_PREDICTION['net_profit_range'], ACTUAL_DATA['net_profit'])} |
| 毛利率 (%) | {H1_PREDICTION['gross_margin']} | {ACTUAL_DATA['gross_margin']} | {get_error_percent((H1_PREDICTION['gross_margin_low']+H1_PREDICTION['gross_margin_high'])/2, ACTUAL_DATA['gross_margin'])}% | {check_range_accuracy([H1_PREDICTION['gross_margin_low'], H1_PREDICTION['gross_margin_high']], ACTUAL_DATA['gross_margin'])} |

---

## 💡 结论与建议

{generate_conclusion() if ACTUAL_DATA['revenue'] else "**待中报发布后进行分析**"}

---

**数据来源**：
- 预测值：本文分析（2026-08-20）
- 实际值：水晶光电 2026 半年报公告（2026-08-24）
"""
    return report

def get_growth(actual, base):
    """计算同比增速"""
    if actual is None or base is None:
        return "N/A"
    return f"+{(actual - base) / base * 100:.1f}%"

def get_error_analysis(predicted, actual, field_name):
    """获取误差分析结果"""
    if actual is None:
        return "未发布中报，等待 8 月 24 日..."
    
    absolute_error, relative_error = calculate_error(predicted, actual)
    status = "✅" if -10 <= relative_error <= 10 else "❌"
    
    return f"{status} 绝对误差：{absolute_error:.2f}亿元\n相对误差：{relative_error:.1f}%"

def get_error_percent(predicted, actual):
    """计算相对误差百分比"""
    if predicted is None or actual is None:
        return "N/A"
    return f"{((actual - predicted) / predicted * 100):.1f}%"

def check_range_accuracy(range_data, actual):
    """检查是否在预测区间内"""
    if range_data is None or actual is None:
        return "待验证"
    return "✅准确" if range_data[0] <= actual <= range_data[1] else "❌超出"

def generate_conclusion():
    """生成结论"""
    return "**预测准确度总结**：营收误差 X%，净利润误差 Y%，毛利率误差 Z%。\n建议根据实际表现调整后续预测模型。"

# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 测试模式 - 未发布中报
    print("水晶光电中报预测验证工具")
    print("=" * 70)
    print("当前状态：等待 2026 年 8 月 24 日中报发布...")
    print("\n预测数据已预设：")
    print(f"  • 营收：{H1_PREDICTION['revenue_range'][0]}-{H1_PREDICTION['revenue_range'][1]} 亿元")
    print(f"  • 净利润：{H1_PREDICTION['net_profit_range'][0]}-{H1_PREDICTION['net_profit_range'][1]} 亿元")
    print(f"  • 毛利率：{H1_PREDICTION['gross_margin_low'}%-{H1_PREDICTION['gross_margin_high']}%")
    print("\n💡 使用方法：")
    print("  1. 8 月 24 日中报发布后，填写 ACTUAL_DATA 字典")
    print("  2. 运行脚本自动生成验证报告")
    print("  3. 对比预测与实际误差，优化后续预测模型")
