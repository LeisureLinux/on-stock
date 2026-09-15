# 外媒新闻速览模块

每日抓取 Bloomberg / FT / WSJ / Reuters 的**标题**，生成静态页发布到
<https://stock.freelamp.com/latest/>，并按日归档到 `/news/YYYYMMDD/`。

## 架构：抓取与构建分离

```
本机 cron ──▶ scripts/fetch_news.py ──▶ data/news/YYYYMMDD.json ──▶ git push
                                                                        │
                                                                        ▼
                                    GitHub（legacy Pages 自动发布 main:/docs）
                                                                        │
                                                     build.py → news_builder.py
                                                                        │
                                            docs/latest/ + docs/news/YYYYMMDD/
```

**为什么抓取放在本机而不是 Actions？**
Actions 出口 IP 属 Azure 数据中心段，反爬优先级最高。实测官网正文页直连：
FT 403（Cloudflare 验证页）、WSJ 401、Reuters 401（Akamai 全域封禁，带 cookie
也 401）。数据中心 IP 只会更严。本机 IP 至少能稳定拿到全部四家的官方
news sitemap（robots.txt 声明的路径不设人机验证）。

## 抓取

```bash
python3 scripts/fetch_news.py                    # 抓当天四家标题
python3 scripts/fetch_news.py --with-body        # 额外抓 Bloomberg 全文
python3 scripts/fetch_news.py --sources bb,wsj   # 只抓指定源
python3 scripts/fetch_news.py --pages 2          # Reuters 翻页（每页约 100 条）
python3 scripts/fetch_news.py --skip-letters     # 过滤 FT 的 Letter 读者来信
python3 scripts/fetch_news.py --date 20260907    # 指定归档日期
python3 scripts/fetch_news.py --from-file x.xml  # 离线解析（调试）
```

同一天可多次运行，sources 会合并而非覆盖。产物：`data/news/YYYYMMDD.json`
与归档索引 `data/news/index.json`。

## 构建

`build.py` 末尾调用 `news_builder.build_news_pages(docs_dir)`，生成：

| 路径 | 内容 |
|---|---|
| `docs/latest/index.html` + `index.json` | 最新一天（站点入口） |
| `docs/news/index.html` | 归档目录 |
| `docs/news/YYYYMMDD/index.html` + `index.json` | 每日归档 |

新闻模块异常不会阻断主站发布（try/except 包裹）。

## 每日自动化

完整链路：抓标题 → 翻译中文 → 提交 → push（push 触发 Pages 重建发布）。
翻译用 `scripts/translate_news.py`（默认 DeepSeek 后端，按 url 缓存，已译不重译）。

在 crontab 里加（注意用本机 Python 环境，DeepSeek key 从 `~/.codex/.env` 读取）：

```
0 8,20 * * * cd ~/codex/writings/stock && \
  python3 scripts/fetch_news.py --skip-letters --with-body >> /tmp/fetch_news.log 2>&1 && \
  python3 scripts/translate_news.py --date $(date +\%Y\%m\%d) >> /tmp/translate_news.log 2>&1 && \
  git add data/ docs/ && git commit -m "chore: 更新外媒速览 $(date +\%Y\%m\%d-\%H\%M)" && git push
```

> 注：翻译默认后端 DeepSeek（`TRANSLATE_BACKEND=deepseek`，国内直连可达、充值后无 RPM 限制）；
> 如需切到 workbuddy 本地代理：`TRANSLATE_BACKEND=workbuddy`。WSJ 体育新闻已在 `fetch_news.py` 的 `skip_sections` 过滤。

## 数据源状态

| 源 | sitemap | 正文 |
|---|---|---|
| Bloomberg | `/sitemaps/news/latest.xml` | ✅ `envoy.cirrus.bloomberg.com` 镜像域名直连，读 `__NEXT_DATA__` |
| FT | `/sitemaps/news.xml`、RSS `/rss/home/international` | ✅ 官方 news sitemap 可直连抓标题（实测 110 条/日）；正文仍受 Cloudflare 验证页拦截，暂无自动通道 |
| WSJ | `/wsjsitemaps/wsj_google_news.xml` | ✅ 官方 news sitemap 可直连抓标题（实测 108 条/日）；正文可经 TradingView `news/DJN_*`（道琼斯通讯社全文），需搜索 |
| Reuters | `/arc/outboundfeeds/news-sitemap/?outputType=xml` | ✅ 官方 news sitemap 可直连抓标题（实测 50 条/日，支持 `--pages` 翻页）；正文可经 CNA 等授权转载站，需搜索 |

> 标题四家均已跑通（2026-09-14 实测：bb 158 / ft 110 / wsj 108 / rt 50，共 426 条）。
> WSJ 官方 RSS（`feeds.a.dj.com`）数据陈旧（实测返回 2025 年内容），勿用。

## 已知坑

- **Python 版本**：CI 用 3.11，不支持 PEP 701（f-string 内嵌同型引号）。
  本仓库 `build.py` 曾因此持续构建失败，已改用 `.format`。写 f-string 时注意。
- **Pages 模式**：当前 legacy（main:/docs），发布由 GitHub 自带
  `pages build and deployment` 完成。`.github/workflows/deploy.yml` 只做构建校验，
  不执行部署——legacy 模式下 deploy-pages 会失败。若改 Actions 部署，需先到
  Settings → Pages → Source 切换。
- **build.py 会 `rmtree(docs/)`**：news 页面全部从 `data/` 重建，不要手工往
  `docs/` 里放文件。
