# Stock Analysis agents.md

## 🎯 数据准确性保障机制

### 1. 核心原则

所有分析报告中的**财务数据、行情数据、行业数据**必须满足以下要求：

| 数据类型 | 必须提供 | 验证方式 | 可信度 |
|----------|----------|----------|--------|
| **财务数据** | ✅ 官方公告链接 | 巨潮资讯/交易所官网 | ⭐⭐⭐⭐⭐ |
| **行情数据** | ✅ 实时数据源 | 东方财富/同花顺 API | ⭐⭐⭐⭐⭐ |
| **行业数据** | ✅ 权威机构来源 | Prismark/IDC/Gartner | ⭐⭐⭐⭐ |
| **券商预测** | ✅ 3 家以上券商 | 一致预期/Wind/Choice | ⭐⭐⭐⭐ |
| **业务数据** | ✅ 公司披露/调研纪要 | 官方公告/投资者关系 | ⭐⭐⭐⭐ |

---

### 2. 数据源配置中心

#### 2.1 配置表：`config/data_sources.yaml`

```yaml
# 财务数据源
financial_sources:
  沪深 A 股：
    官方公告：https://www.cninfo.com.cn
    实时数据：https://push2.eastmoney.com/api/qt/stock/list
    
  财务数据 API:
    东方财富：https://apppush.csjson.com/api/stockinfo/json.aspx
    同花顺：https://d.10jqkan.com.cn/v4/stock/

# 行业数据来源
industry_sources:
  PCB:
    Prismark: https://www.prismark.com/press-releases
    中国电子电路协会：https://cPCA.org.cn/

# 券商研报平台
brokerage_sources:
  主流券商：华创/中信/中金/天风/浙商
  数据聚合：Wind/Choice/慧博投研
```

#### 2.2 验证脚本：`scripts/verify_data.py`

```python
"""
数据验证脚本 - 自动生成数据可信度报告
"""

import yaml
import requests
from datetime import datetime
from typing import Dict, List

class DataVerifier:
    """数据验证器"""
    
    def __init__(self, config_path: str = "config/data_sources.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
    
    def verify_financial_data(self, company: str, period: str, data: dict) -> dict:
        """
        验证财务数据真实性
        
        Args:
            company: 公司代码
            period: 报告期 (Q1/H1/annual)
            data: 财务数据字典
            
        Returns:
            验证结果报告
        """
        result = {
            "verified": True,
            "source_links": [],
            "confidence_score": 0.0,
            "warnings": []
        }
        
        # 1. 检查必须有官方公告链接
        if "source_link" not in data:
            result["verified"] = False
            result["warnings"].append("缺少官方公告链接")
            return result
        
        # 2. 验证链接有效性
        try:
            response = requests.get(data["source_link"], timeout=10)
            if response.status_code != 200:
                result["warnings"].append(f"公告链接无法访问：{data['source_link']}")
            else:
                result["source_links"].append(data["source_link"])
                result["confidence_score"] += 0.4
        except Exception as e:
            result["warnings"].append(f"公告链接验证失败：{str(e)}")
        
        # 3. 交叉验证关键数据
        if data.get("revenue") and data.get("net_profit"):
            crsp_data = self.fetch_from_cisp(data["source_link"])
            if abs(crsp_data["revenue"] - data["revenue"]) / data["revenue"] > 0.05:
                result["warnings"].append("财务数据与官方公告差异超过 5%")
                result["confidence_score"] -= 0.3
            
            result["confidence_score"] += 0.4
        
        # 4. 检查数据合理性
        if data.get("revenue_growth"):
            if data["revenue_growth"] > 100 and data.get("period") != "annual":
                result["warnings"].append("季度营收增速 >100%，需检查是否异常")
        
        result["confidence_score"] += 0.2  # 基准分
        return result
    
    def fetch_from_cisp(self, source_link: str) -> dict:
        """从巨潮资讯提取财务数据"""
        # TODO: 实现爬虫逻辑，从公告中提取财务数据
        pass
    
    def generate_verification_report(self, article: dict) -> str:
        """
        生成数据验证报告
        
        Args:
            article: 文章元数据字典
            
        Returns:
            Markdown 格式的报告
        """
        report = f"""
# 数据验证报告（{datetime.now().strftime('%Y-%m-%d %H:%M')}）

## ✅ 验证通过的字段
| 字段 | 数值 | 来源 | 可信度 |
|------|------|------|--------|
"""
        # 遍历验证每个字段
        for field, value in article.get("data", {}).items():
            verification = self.verify_financial_data(
                article["company_code"], 
                article["period"], 
                {**value, "source_link": article.get("source_link")}
            )
            if verification["verified"]:
                report += f"| {field} | {value} | {verification['source_links'][0]} | ⭐⭐⭐⭐⭐ |\n"
            else:
                report += f"| {field} | {value} | ⚠️ 待验证 |\n"
                for warning in verification["warnings"]:
                    report += f"> ⚠️ **警告**: {warning}\n"
        
        report += f"\n## 📊 综合评分\n**可信度**: {verification['confidence_score']/100*5:.1f}/5 星\n"
        
        if verification["confidence_score"] < 3.5:
            report += "> ⚠️ **警告**: 数据综合评分低于 3.5 星，建议重新核实关键数据\n"
        
        return report


# 使用示例
if __name__ == "__main__":
    verifier = DataVerifier()
    
    # 测试验证沪电股份数据
    test_article = {
        "company_code": "002463",
        "period": "2026H1",
        "source_link": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&related=True",
        "data": {
            "revenue": 62.14,
            "revenue_growth": 53.91,
            "net_profit": 12.42,
            "net_profit_growth": 62.90
        }
    }
    
    report = verifier.generate_verification_report(test_article)
    print(report)
```

---

### 3. 文章元数据规范

#### 3.1 `metadata.yaml` 必须包含的字段

```yaml
# 文章元数据（必需字段）
title: "XXX 公司深度分析报告"
date: 2026-08-20
author: "LeisureLinux"
tags:
  - 代码
  - 行业
  - 关键词

# 数据源声明（新增）
data_sources:
  financial:
    - type: "官方公告"
      link: "https://www.cninfo.com.cn/new/commonUrl/html/disclosure company/publicDetail?context=...&announcetype=Announcement-1"
      verified: true
    - type: "业绩预告"
      link: ".../2026-08-20"
      verified: true
  
  market:
    - type: "东方财富实时数据"
      link: "https://push2.eastmoney.com/api/qt/stock/list"
      verified: true
      last_update: "2026-08-20 15:00"
  
  industry:
    - type: "Prismark 行业报告"
      link: "https://www.prismark.com/press-releases/..."
      verified: true
  
  brokerages:
    - name: "中信证券"
      prediction: "2026E PE 35x"
      link: "https://research.citics.com/..."
    - name: "中金公司"
      prediction: "2026E PE 32x"
      link: "..."
    - name: "天风证券"
      prediction: "2026E PE 30x"
      link: "..."

# 数据验证状态
verification:
  financial_verified: true
  market_verified: true
  industry_verified: true
  brokerages_verified: true
  last_check: "2026-08-20 15:30"
  confidence_score: 4.8/5
```

---

### 4. 自动化数据验证流程

#### 4.1 CI/CD 集成：`.github/workflows/verify-data.yml`

```yaml
name: 数据验证

on:
  pull_request:
    branches: [main]
    paths:
      - 'articles/**'
      - 'config/data_sources.yaml'
  push:
    branches: [main]
    paths:
      - 'articles/**'

jobs:
  verify-data:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: 设置 Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: 安装依赖
        run: |
          pip install pyyaml requests beautifulsoup4
      
      - name: 运行数据验证
        run: |
          mkdir -p results
          python scripts/verify_data.py >> results/verification_report.md
          
      - name: 检查验证结果
        run: |
          grep -q "综合评分: 4.0/5" results/verification_report.md || {
            echo "⚠️ 数据验证未通过，请检查数据源可靠性"
            exit 1
          }
      
      - name: 提交验证报告
        uses: actions/upload-artifact@v3
        with:
          name: verification-report
          path: results/verification_report.md
```

#### 4.2 构建脚本增强：`build.py` 数据验证步骤

```python
# 在构建页面前添加数据验证
from scripts.verify_data import DataVerifier

def validate_article_data(article):
    """在页面构建前验证数据"""
    verifier = DataVerifier()
    report = verifier.generate_verification_report(article)
    
    # 如果可信度低于 3.5，阻止构建
    if verifier.get_confidence_score(article) < 3.5:
        raise ValueError(f"数据可信度低于标准：{verifier.get_confidence_score(article)}/5")
    
    # 将验证报告嵌入 HTML head
    return report

def build_article_page(article):
    # 新增：数据验证
    verification_report = validate_article_data(article)
    
    # 继续构建...
```

---

### 5. 数据更新自动化

#### 5.1 定时更新脚本：`scripts/update_market_data.sh`

```bash
#!/bin/bash
# 每日更新市场数据

# 1. 获取最新股价
curl -s "https://push2.eastmoney.com/api/qt/stock/get?secid=16.002463&fields=f12,f13,f14,f18,f2,f3,f62,f64,f65,f66,f71,f73,f74,f75,f76,f77,f78,f79,f80,f81,f82,f83,f84,f85,f86,f87,f88,f89,f90" \
  | python3 -c "import sys, json; d=json.load(sys.stdin); print(json.dumps(d.get('data',{}),indent=2))" \
  > data/latest_prices.json

# 2. 更新到文章中
# TODO: 解析 JSON 并更新文章中的股价数据
```

---

### 6. 手动验证清单

在发布文章前，作者需要检查：

- [ ] **财务数据**：是否有官方公告链接（巨潮资讯）
- [ ] **行情数据**：是否为最新收盘价（标注更新时间）
- [ ] **行业数据**：是否来自权威机构（Prismark/IDC 等）
- [ ] **券商预测**：是否引用至少 3 家券商
- [ ] **预测逻辑**：盈利预测是否与历史业绩趋势一致
- [ ] **目标价**：估值方法是否清晰，假设是否合理
- [ ] **风险提示**：是否充分披露主要风险因素

---

### 7. 工具推荐

| 工具 | 用途 | 链接 |
|------|------|------|
| **巨潮资讯** | 官方公告查询 | https://www.cninfo.com.cn |
| **东方财富** | 实时行情/财务数据 | https://www.eastmoney.com |
| **Wind/Choice** | 券商研报/一致预期 | 付费 |
| **慧博投研** | 研报聚合 | https://www.hibor.com.cn |
| **Prismark** | PCB 行业数据 | https://www.prismark.com |
| **Python 脚本** | 自动化验证 | 本项目内部 |

---

### 8. 更新记录

| 日期 | 更新内容 | 责任人 |
|------|----------|--------|
| 2026-08-20 | 创建数据验证机制框架 | LeisureLinux |
| 2026-08-21 | 完善验证脚本 | TBD |

---

## 💡 最佳实践

1. **数据优先级**：官方公告 > 权威机构 > 主流券商 > 自媒体
2. **时间戳**：所有行情数据必须标注"最后更新时间"
3. **交叉验证**：关键数据至少 2 个独立来源
4. **版本控制**：数据变更必须提交 Commit 记录
5. **自动化**：尽可能使用脚本自动验证，人工只是最终把关

---

**记住：数据准确性是分析质量的生命线！宁可慢一点，也要确保数据真实可靠。**
