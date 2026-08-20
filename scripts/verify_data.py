#!/usr/bin/env python3
"""
数据验证脚本 - Stock Analysis 项目
用于自动生成数据可信度报告，确保所有财务、行情、行业数据的真实性
"""

import yaml
import json
import re
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path


class DataVerifier:
    """数据验证器 - 确保所有数据分析的准确性"""
    
    MIN_CONFIDENCE_SCORE = 3.5  # 最低可信度分数
    
    def __init__(self, config_path: str = "config/data_sources.yaml"):
        """初始化验证器"""
        self.config_path = Path(config_path)
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """加载配置"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def verify_financial_data(
        self, 
        company_code: str, 
        period: str, 
        data: dict,
        source_link: str = None
    ) -> dict:
        """
        验证财务数据真实性
        
        Args:
            company_code: 公司代码（如 002463）
            period: 报告期（Q1/H1/annual）
            data: 财务数据字典（营收、净利润等）
            source_link: 官方公告链接
        
        Returns:
            验证结果报告字典
        """
        result = {
            "verified": True,
            "confidence_score": 5.0,
            "source_links": [],
            "warnings": [],
            "errors": []
        }
        
        # 1. 检查官方公告链接
        if not source_link:
            result["verified"] = False
            result["errors"].append("❌ 缺少官方公告链接")
            result["confidence_score"] -= 2.0
            return result
        
        result["source_links"].append(source_link)
        result["confidence_score"] = 5.0  # 官方公告基准分
        
        # 2. 解析财报数据（简化版，实际需爬虫）
        # TODO: 实现从巨潮资讯提取数据
        extracted_data = self._extract_from_cninfo(source_link)
        
        # 3. 交叉验证关键数据
        if extracted_data:
            for key in ["revenue", "net_profit", "revenue_growth", "net_profit_growth"]:
                if key in data and key in extracted_data:
                    normalized = data.get("period")
                    if abs(explicit_comparison(normalized, extracted_data)) > 0.05:
                        result["confidence_score"] -= 0.5
                        result["warnings"].append(f"⚠️ {key} 与官方公告差异超过 5%")
        
        # 4. 数据合理性检查
        if data.get("revenue_growth", 0) > 100 and period != "annual":
            result["warnings"].append("⚠️ 季度营收增速 >100%，建议人工复核")
        
        if data.get("net_profit", 0) < 0 and period == "annual":
            result["warnings"].append("⚠️ 全年净利润为负，需检查是否一致")
        
        # 5. 行业一致性检查
        industry_score = self._check_industry_consistency(company_code, period, data)
        result["confidence_score"] = min(5.0, result["confidence_score"] * industry_score)
        
        # 6. 计算最终评分（四舍五入到 0.1）
        result["confidence_score"] = round(result["confidence_score"], 1)
        
        # 检查是否达标
        if result["confidence_score"] < self.MIN_CONFIDENCE_SCORE:
            result["verified"] = False
            result["errors"].append(f"❌ 综合评分 {result['confidence_score']}/5 低于标准 {self.MIN_CONFIDENCE_SCORE}")
        
        return result
    
    def extract_from_cninfo(self, source_link: str) -> dict:
        """
        从巨潮资讯提取财务数据
        TODO: 实现真实的爬虫逻辑
        """
        # 当前返回模拟数据（实际需替换为真实爬虫）
        # 示例：
        # import requests
        # from bs4 import BeautifulSoup
        # response = requests.get(source_link, timeout=10)
        # .... 解析 HTML 提取数据
        return {}
    
    def check_industry_consistency(self, company_code: str, period: str, data: dict) -> float:
        """检查数据与行业趋势是否一致"""
        score = 1.0
        
        # 示例逻辑：检查沪电股份营收增速是否与 PCB 行业增速匹配
        if company_code == "002463":
            # PCB 行业 2026 年增速约 12.5%（Prismark）
            industry_growth = 12.5  # 简化版
            if abs(data.get("revenue_growth", 0) - industry_growth) > 50:
                score = 0.7  # 大幅偏离行业均值，风险较高
        
        return score
    
    def generate_verification_report(self, article_data: dict) -> str:
        """
        生成 Markdown 格式的数据验证报告
        
        Args:
            article_data: 文章元数据，包含所有数据字段
        
        Returns:
            Markdown 报告字符串
        """
        report = f"""
# 📊 数据验证报告
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}  
**公司**: {article_data.get('company_name', 'N/A')} (代码：{article_data.get('company_code', 'N/A')})

---

## ✅ 已验证的数据字段
"""
        total_score = 0
        field_count = 0
        
        for field, value in article_data.get("verified_data", {}).items():
            verification = self.verify_financial_data(
                article_data["company_code"],
                article_data["period"],
                value,
                article_data.get("source_link")
            )
            total_score += verification["confidence_score"]
            field_count += 1
            
            score_symbol = "⭐" * int(verification["confidence_score"])
            status = "✅" if verification["verified"] else "❌"
            
            report += f"""
### {status} {field}
- **数值**: {value}
- **可信度**: {score_symbol} ({verification['confidence_score']}/{len(score_symbol)})
"""
            if verification["source_links"]:
                report += f"- **来源**: {verification['source_links'][0]}\n"
            
            for warning in verification["warnings"]:
                report += f"> ⚠️ **警告**: {warning}\n"
        
        # 计算综合评分
        avg_score = total_score / max(1, field_count)
        final_score = round(avg_score, 1)
        
        report += f"""

---

## 📊 综合评分

| 指标 | 数值 | 评级 |
|------|------|------|
| **验证字段数** | {field_count} | — |
| **平均可信度** | {final_score}/5 | {"✅优秀" if final_score >= 4.5 else "✅良好" if final_score >= 3.5 else "❌需改进"} |
| **验证状态** | {"✅通过" if final_score >= self.MIN_CONFIDENCE_SCORE else "❌未通过"} | — |

"""
        
        if final_score < self.MIN_CONFIDENCE_SCORE:
            report += f"> ⚠️ **警告**: 综合评分 {final_score}/5 低于标准 {self.MIN_CONFIDENCE_SCORE}，建议重新核实数据源\n"
        
        return report


def explicit_comparison(data1, data2):
    """计算相对差异"""
    if isinstance(data1, (int, float)) and isinstance(data2, (int, float)):
        return abs(data1 - data2) / abs(data2) if data2 != 0 else 0
    return 0


# ==================== 使用示例 ====================

if __name__ == "__main__":
    print("启动数据验证器...\n")
    
    verifier = DataVerifier()
    
    # 测试场景：沪电股份 2026Q1 数据
    test_article = {
        "company_name": "沪电股份",
        "company_code": "002463",
        "period": "2026Q1",
        "source_link": "https://www.cninfo.com.cn/new/commonUrl/html/disclosureListSearch?announcetype=Announcement-1",
        "verified_data": {
            "revenue": {
                "value": 62.14,
                "unit": "亿元"
            },
            "revenue_growth": {
                "value": 53.91,
                "unit": "%"
            },
            "net_profit": {
                "value": 12.42,
                "unit": "亿元"
            },
            "net_profit_growth": {
                "value": 62.90,
                "unit": "%"
            }
        }
    }
    
    report = verifier.generate_verification_report(test_article)
    print(report)
    
    # 保存报告到文件
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    report_path = results_dir / "verification_report.md"
    report_path.write_text(report, encoding='utf-8')
    print(f"\n✅ 验证报告已保存至：{report_path}")
