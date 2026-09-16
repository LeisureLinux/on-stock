#!/bin/bash
# stock.freelamp.com 外媒速览 · 每日自动流水线
# cron 调用（不要把带 % 的命令直接写进 crontab —— % 转义地狱）
#
# 链路: fetch(标题) → translate(中文化) → summarize(BB正文+摘要)
#       → build(生成静态页) → commit → push(触发 Pages 发布)
#
# 用法: run_daily.sh [YYYYMMDD]   缺省为今天(北京时间)
set -u
export LANG=C.UTF-8
PY=/home/axu/miniforge3/bin/python3
REPO=/home/axu/codex/writings/stock
LOGDIR=/tmp
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
DAYLOG="$LOGDIR/fetch_news.log"

log() { echo "[$(TZ=Asia/Shanghai date '+%F %T')] $*" >> "$DAYLOG"; }

log "==== 流水线开始 日期=$DATE ===="

cd "$REPO" || { log "❌ 进不了 $REPO"; exit 1; }

# 0) 已有未提交改动则先清场(理论上不该有；有就 stash 丢弃, 防卡链)
if ! git diff --quiet || ! git diff --cached --quiet; then
    log "⚠️  工作区有未提交改动, stash 掉"
    git stash -u >/dev/null 2>&1 || true
fi

# 1) 抓标题
if ! $PY scripts/fetch_news.py --skip-letters >> "$DAYLOG" 2>&1; then
    log "❌ fetch 失败, 终止"
    exit 1
fi
log "✅ fetch 完成"

# 1.5) 全部抓空(网络断/sitemap 挂)则告警跳过发布，避免 build+push 空转。
#      注意：不 exit 1，留给下轮 cron 自然重试；也不 clean stash，避免误伤手工改动。
TODAY=$DATE
NEW_TOTAL=$($PY -c "
import json, sys
from pathlib import Path
p = Path('$REPO/data/news/$TODAY.json')
if not p.exists():
    print(0); sys.exit()
d = json.loads(p.read_text())
print(sum(s.get('count', 0) for s in d.get('sources', {}).values()))
" 2>/dev/null || echo 0)
if [ "$NEW_TOTAL" -eq 0 ] 2>/dev/null; then
    log "⚠️  今日归档为空（四源 sitemap 全部抓取失败？网络问题），跳过 translate/summarize/build/push"
    exit 1
fi
log "✅ 今日归档 $NEW_TOTAL 条"

# 2) 翻译
if ! $PY scripts/translate_news.py --date "$DATE" >> "$LOGDIR/translate_news.log" 2>&1; then
    log "⚠️  translate 失败(继续摘要)"
fi
log "✅ translate 完成"

# 3) BB 摘要
if ! $PY scripts/summarize_news.py --date "$DATE" >> "$LOGDIR/summarize_news.log" 2>&1; then
    log "⚠️  summarize 失败(继续发布)"
fi
log "✅ summarize 完成"

# 4) 生成静态页(缺失步骤! 没它 docs/ 不更新)
if ! $PY build.py >> "$DAYLOG" 2>&1; then
    log "❌ build 失败, 终止"
    exit 1
fi
log "✅ build 完成"

# 5) 有变更才提交推送
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard data/ docs/)" ]; then
    log "✅ 无变更, 无需发布"
    exit 0
fi

git add data/ docs/ >> "$DAYLOG" 2>&1
if git commit -m "chore: 更新外媒速览 $DATE" >> "$DAYLOG" 2>&1; then
    if git push origin main >> "$DAYLOG" 2>&1; then
        log "✅ 已发布(git push 成功)"
    else
        log "❌ push 失败(本地已 commit, 下轮会补推)"
    fi
else
    log "⚠️  commit 无产出(可能仅时间戳变化)"
fi
log "==== 流水线结束 ===="
