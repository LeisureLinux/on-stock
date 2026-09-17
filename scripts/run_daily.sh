#!/bin/bash
# stock.freelamp.com 外媒速览 · 每日自动流水线
# cron 调用（不要把带 % 的命令直接写进 crontab —— % 转义地狱）
#
# 链路: fetch(标题) → translate(中文化) → summarize(BB正文+摘要)
#       → build(生成静态页) → commit → push(触发 Pages 发布)
#
# 用法: run_daily.sh [YYYYMMDD]   缺省为今天(北京时间)
#
# 移植说明: REPO 由脚本自身位置推导，PYTHON 自动探测，机器之间无需改路径。
#           仍可用环境变量覆盖: PYTHON=/path/to/python / STOCK_LOGDIR=/var/log/stock
set -u
export LANG=C.UTF-8

# ---- cron 环境自愈：cron 给的 PATH 很窄，这里补齐 ----
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin${PATH:+:$PATH}"
[ -n "${HOME:-}" ] && export PATH="$HOME/bin:$HOME/.local/bin:$PATH"

# ---- 路径/解释器：不硬编码 ----
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$(command -v python3 || true)}"

DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
LOGDIR="${STOCK_LOGDIR:-$REPO/logs}"
DAYLOG="$LOGDIR/fetch_news.log"
LOCKFILE="$LOGDIR/run_daily.lock"

mkdir -p "$LOGDIR" || { echo "❌ 建不了 $LOGDIR" >&2; exit 1; }

log() { echo "[$(TZ=Asia/Shanghai date '+%F %T')] $*" >> "$DAYLOG"; }

# ---- 并发互斥：上一轮没跑完(翻译/摘要很慢)就不要叠一轮 ----
exec 9>"$LOCKFILE"
if ! flock -n 9; then
    log "⚠️  上一轮仍在运行(锁 $LOCKFILE 未释放)，本轮跳过"
    exit 0
fi

log "==== 流水线开始 日期=$DATE ===="

if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    log "❌ 找不到可用的 python3（可设 PYTHON= 指定）"
    exit 1
fi
log "环境: REPO=$REPO PYTHON=$PYTHON ($("$PYTHON" -V 2>&1 | awk '{print $2}'))"

cd "$REPO" || { log "❌ 进不了 $REPO"; exit 1; }

# 0) 旧版本遗留的 stash 提醒（不再自动 stash：那会静默吃掉手工改动且失败不回滚）
STASH_N=$(git stash list 2>/dev/null | grep -c . || true)
[ "${STASH_N:-0}" -gt 0 ] && log "⚠️  尚有 $STASH_N 个 stash 未处理，请手工 git stash list 确认"

# 1) 抓标题
if ! "$PYTHON" scripts/fetch_news.py --skip-letters >> "$DAYLOG" 2>&1; then
    log "❌ fetch 失败, 终止"
    exit 1
fi
log "✅ fetch 完成"

# 1.5) 全部抓空(网络断/sitemap 挂)则告警跳过发布，避免 build+push 空转。
#      注意：不 exit 1，留给下轮 cron 自然重试；也不 clean stash，避免误伤手工改动。
TODAY=$DATE
NEW_TOTAL=$("$PYTHON" -c "
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

# 1.6) fetch 会按"发布时间"跨日归档，本轮真正改动的日期文件可能不止今天。
#      逐个交给 translate/summarize，否则分流到历史日的条目永远不会有中文标题。
#      git status 同时覆盖「已跟踪被改」和「新建未跟踪」两种情况。
TOUCHED=$(git status --porcelain -- data/news/ \
          | sed -n 's#^...data/news/\([0-9]\{8\}\)\.json$#\1#p' \
          | sort -u | tr '\n' ' ')
case " $TOUCHED " in
    *" $TODAY "*) : ;;
    *) TOUCHED="$TODAY $TOUCHED" ;;
esac
log "本轮涉及归档日:$TOUCHED"

# 2) 翻译（逐回归档日，增量：已译不重译）
for d in $TOUCHED; do
    if ! "$PYTHON" scripts/translate_news.py --date "$d" >> "$LOGDIR/translate_news.log" 2>&1; then
        log "⚠️  translate $d 失败(继续摘要)"
    fi
done
log "✅ translate 完成"

# 3) BB 摘要
for d in $TOUCHED; do
    if ! "$PYTHON" scripts/summarize_news.py --date "$d" >> "$LOGDIR/summarize_news.log" 2>&1; then
        log "⚠️  summarize $d 失败(继续发布)"
    fi
done
log "✅ summarize 完成"

# 4) 生成静态页
if ! "$PYTHON" build.py >> "$DAYLOG" 2>&1; then
    log "❌ build 失败, 终止"
    exit 1
fi
log "✅ build 完成"

# 5) 有变更才提交推送（只看 data/ docs/，不因工作区其它脏文件误提交）
git add data/ docs/ >> "$DAYLOG" 2>&1
if git diff --cached --quiet; then
    log "✅ 无变更, 无需发布"
    exit 0
fi

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
