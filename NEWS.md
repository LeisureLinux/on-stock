# 外媒新闻速览模块

每日抓取 Bloomberg / FT / WSJ / Reuters 的**标题**，生成付费页供订阅用户阅读。

## 架构：抓取与构建分离，付费内容不进仓库

```
本机 cron ──▶ scripts/fetch_news.py ──▶ data/news/YYYYMMDD.json（gitignore）
                                                │
                                     build.py → news_builder.py
                                                │
                    ┌───────────────────────────┴───────────────────────────┐
                    ▼                                                       ▼
  docs/trial/ + docs/subscribe/      （公开，进 git）          dist_paid/latest/ + dist_paid/news/YYYYMMDD/
                    │                                       （付费，gitignore）
                    ▼                                                       │
        git push → GitHub Pages                            scripts/publish_paid.py
                    ▼                                                       ▼
        主域公开区回源 origin-stock                   Cloudflare KV `SITE`
                                                                 │
                                                    Worker 鉴权后从 KV 读，**不回源**
```

**为什么付费页不能放 `docs/`**：仓库是公开的。GitHub Pages 源站
（`origin-stock.freelamp.com`）、`raw.githubusercontent.com`、`cdn.jsdelivr.net`
都能直接读到仓库里的文件，Worker 只是它前面的一层代理，绕过去即可。同理
`data/news/*.json` 本身就是付费原料（标题+中译+摘要），也必须留在仓库外。

> 付费墙运维代码（Worker / users.py / 本说明）在 `tools/` 下，**已 gitignore**，
> 不进公开仓库；本机路径 `tools/cf-paywall/`。

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
（本机保留，**不进 git**）与归档索引 `data/news/index.json`。

## 构建

`build.py` 末尾调用 `news_builder.build_news_pages(docs_dir, dist_paid_dir)`，分两处输出：

| 路径 | 公开性 | 内容 |
|---|---|---|
| `docs/trial/index.html` | 公开（进 git） | 今日免费试读 5 条 |
| `docs/subscribe/index.html` | 公开（进 git） | 订阅页（套餐 + 收款码） |
| `dist_paid/latest/index.html` | 付费（gitignore） | 最新一天（站点入口 `/latest`） |
| `dist_paid/news/index.html` | 付费 | 归档目录 |
| `dist_paid/news/YYYYMMDD/index.html` | 付费 | 每日归档 |

付费页随后由 `scripts/publish_paid.py` 上传到 KV `SITE`（key 就是相对路径，
如 `latest/index.html`），Worker 鉴权后读取。

**不生成任何 `index.json`**：页面 HTML 已内联全部内容，前端不 fetch、构建也不读，
旧版每份 ~1.1 MB/天纯属冗余。

新闻模块异常不会阻断主站发布（try/except 包裹）。

## 每日自动化

完整链路（封装在 `scripts/run_daily.sh`，**不要**再手写下面那串命令）：

fetch 标题 → translate 中文 → summarize(BB 正文+摘要) → build.py（公开页→docs/，付费页→dist_paid/）
→ publish_paid.py（上传 KV）→ commit → push

在 crontab 里加一行即可（脚本自带 PATH 自愈、flock 互斥、路径自推导，**无需 cd**）：

```
0 8,20 * * * /home/axu/stock/scripts/run_daily.sh
```

关键设计：

* **无硬编码路径**：`REPO` 由脚本自身位置推导，`PYTHON` 用 `command -v python3` 自动探测；
  换机器不用改脚本。需要覆盖时可设环境变量 `PYTHON=/path/to/python` / `STOCK_LOGDIR=/var/log/stock`。
* **日志**：默认落 `$REPO/logs/`（`fetch_news.log`、`translate_news.log`、`summarize_news.log`），已被 `.gitignore` 忽略。
* **付费页先上 KV 再 push**：`publish_paid.py` 失败就终止本轮不 push——
  Pages 一旦删除旧页、KV 又没新内容，订阅者就会断供。
* **跨日归档**：`fetch_news.py` 按**发布时间(CST)**归档，sitemap 里混着前几天的条目会分流到历史日文件；
  `run_daily.sh` 用 mtime（3h 窗口）找出本轮真正改动的日期文件逐个跑 translate/summarize，
  否则分流到历史日的条目会永远没有中文标题。（`data/` 已不进 git，`git status` 不再报告它，故改用 mtime。）
* **DeepSeek key** 从 `~/.codex/.env` 读取；翻译默认后端 `TRANSLATE_BACKEND=deepseek`，
  如需切到 workbuddy 本地代理：`TRANSLATE_BACKEND=workbuddy`。
* WSJ/Reuters 体育新闻已在 `fetch_news.py` 的 `skip_sections` 过滤。

手工触发：`bash scripts/run_daily.sh [YYYYMMDD]`（缺省为今天，北京时间）。

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

- **发布时间必须带时区**：Google News sitemap 的 `<news:publication_date>` 是带
  时区标志的 W3C 格式（`Z` / `+00:00`）。**绝不能截断掉时区**——裸时间会被
  `datetime.astimezone()` 按主机本地时区解释，导致 UTC 墙钟被原样贴上 `+08:00`
  标签（少 8 小时）。历史归档曾因此错误，见下方「时区修正」。解析时用
  `cst_from_iso()` 统一处理（裸时间按 UTC 解释），不要自己 `[:19]` 截断。
- **Python 版本**：CI 用 3.11，不支持 PEP 701（f-string 内嵌同型引号）。
  本仓库 `build.py` 曾因此持续构建失败，已改用 `.format`。写 f-string 时注意。
- **Pages 模式**：当前 legacy（main:/docs），发布由 GitHub 自带
  `pages build and deployment` 完成。`.github/workflows/deploy.yml` 只做构建校验，
  不执行部署——legacy 模式下 deploy-pages 会失败。若改 Actions 部署，需先到
  Settings → Pages → Source 切换。
- **build.py 会 `rmtree(docs/)` 与 `rmtree(dist_paid/)`**：两类页面都从 `data/` 重建，
  不要手工往里面放文件。

## 时区修正（2026-09-23）

旧版 `parse_news_sitemap` 用 `[:19]` 截断 `publication_date`，把时区标志切掉；
`cst_from_iso` 又把裸时间当本机本地时间，导致**四源所有时间都少 8 小时**，
且按发布日归档时日期也可能错位。四源 sitemap 均输出 UTC，故统一 +8h 修正。

已修复：`scripts/fetch_news.py`（`parse_news_sitemap` + `cst_from_iso`）。
历史数据迁移：`scripts/migrate_news_timezone.py`（幂等，带 `--dry-run`/`--yes`）。
