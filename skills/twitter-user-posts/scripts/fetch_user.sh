#!/usr/bin/env bash
# 拉取指定 X handle 在最近 DAYS 天内的全部 post，detail + 图片本地缓存。
#
# 增量同步策略（不再以 LIMIT 为缓存判断口径，而是按"天数窗口"）：
#   1. 探针：autocli --limit 1 拉最新一条。
#      - 如果这条 id 已经在缓存窗口内 → 视作"今天没新内容"，直接合并缓存返回。
#   2. 增量拉取：autocli --limit PROBE（从 INITIAL_LIMIT 起步，翻倍）扫一段。
#      - 在返回列表里找第一个命中缓存窗口的 id：命中之前的全部视为"新 post"。
#      - 如果列表里最早一条的 created_at 已经早于窗口起点 SINCE → 取窗口内的全部为新。
#      - 否则继续翻倍 PROBE 直到 MAX_PROBE。
#   3. 对新 ids 拉一次 --include-detail + 下载媒体，写入 cache。
#   4. 最终从 cache 里把窗口内的全部 post 按 created_at 倒序输出。
#
# 用法:
#   ./fetch_user.sh <handle> [initial_limit]
#
# 环境变量:
#   TWITTER_POSTS_DAYS         窗口天数，默认 1（仅今天，本地日历日）
#   TWITTER_POSTS_MAX_PROBE    探针 limit 上限，默认 200
#   TWITTER_POSTS_REFRESH      =1 时跳过 limit=1 探针，直接走增量逻辑

set -euo pipefail

USERNAME="${1:?用法: $0 <handle> [initial_limit]}"
INITIAL_LIMIT="${2:-20}"
DAYS="${TWITTER_POSTS_DAYS:-1}"
MAX_PROBE_LIMIT="${TWITTER_POSTS_MAX_PROBE:-200}"
REFRESH="${TWITTER_POSTS_REFRESH:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CACHE_ROOT="$SKILL_DIR/cache"
CACHE_DIR="$CACHE_ROOT/$USERNAME"
DOWNLOAD_MEDIA="$HOME/.autocli/adapters/twitter/download-media.py"

mkdir -p "$CACHE_DIR"

log() { printf '[fetch_user] %s\n' "$*" >&2; }

# autocli 是 browser strategy（共用一个 Chrome 登录会话），多进程并发会互相抢标签页。
# 用 mkdir 做跨进程 mutex（无依赖、原子），把 autocli 调用串行化。
AUTOCLI_LOCK="${TMPDIR:-/tmp}/twitter-user-posts-autocli.lock"
_lock_owned=0
autocli_locked() {
  local waited=0
  while ! mkdir "$AUTOCLI_LOCK" 2>/dev/null; do
    sleep 0.2
    waited=$((waited+1))
    if [ "$waited" -gt 900 ]; then
      log "warn: autocli 锁等待超时，强制继续"
      break
    fi
  done
  _lock_owned=1
  autocli "$@"
  local rc=$?
  rmdir "$AUTOCLI_LOCK" 2>/dev/null || true
  _lock_owned=0
  return "$rc"
}
trap '[ "$_lock_owned" = 1 ] && rmdir "$AUTOCLI_LOCK" 2>/dev/null || true' EXIT

# ─── 计算窗口起点 SINCE_ISO（本地今天 00:00 → 往前 DAYS-1 天，转成 UTC ISO8601） ───
TODAY_DATE="$(date +'%Y-%m-%d')"
if SINCE_LOCAL_SEC=$(date -j -v-$((DAYS-1))d -f '%Y-%m-%d %H:%M:%S' "$TODAY_DATE 00:00:00" +%s 2>/dev/null); then
  : # macOS BSD date
else
  SINCE_LOCAL_SEC=$(date -d "$TODAY_DATE 00:00:00 - $((DAYS-1)) days" +%s)  # GNU date
fi
SINCE_ISO="$(date -u -r "$SINCE_LOCAL_SEC" +'%Y-%m-%dT%H:%M:%SZ')"

log "user=$USERNAME days=$DAYS since=$SINCE_ISO initial_limit=$INITIAL_LIMIT"

TMP_WORK="$(mktemp -d)"
trap 'rmdir "$AUTOCLI_LOCK" 2>/dev/null || true; rm -rf "$TMP_WORK"' EXIT
CACHE_WIN_IDS="$TMP_WORK/cache_win_ids"
: >"$CACHE_WIN_IDS"

# 扫缓存目录，把 created_at >= SINCE 的 post id 收集进 CACHE_WIN_IDS（一行一个）
scan_cache_window() {
  : >"$CACHE_WIN_IDS"
  [ -d "$CACHE_DIR" ] || return
  local f ts pid
  for f in "$CACHE_DIR"/*.json; do
    [ -f "$f" ] || continue
    ts="$(jq -r '.created_at // ""' "$f" 2>/dev/null || true)"
    if [ -n "$ts" ] && [ ! "$ts" \< "$SINCE_ISO" ]; then
      pid="$(basename "$f" .json)"
      printf '%s\n' "$pid" >>"$CACHE_WIN_IDS"
    fi
  done
}

in_cache_window() {
  grep -Fxq "$1" "$CACHE_WIN_IDS"
}

# 输出 cache 里 created_at >= SINCE 的全部 post，按 created_at 倒序
output_window() {
  local files=() f ts
  if [ -d "$CACHE_DIR" ]; then
    for f in "$CACHE_DIR"/*.json; do
      [ -f "$f" ] || continue
      ts="$(jq -r '.created_at // ""' "$f" 2>/dev/null || true)"
      if [ -n "$ts" ] && [ ! "$ts" \< "$SINCE_ISO" ]; then
        files+=("$f")
      fi
    done
  fi
  if [ ${#files[@]} -eq 0 ]; then
    echo "[]"
  else
    jq -s 'sort_by(.created_at // "") | reverse' "${files[@]}"
  fi
}

scan_cache_window
CACHE_WIN_COUNT=$(wc -l <"$CACHE_WIN_IDS" | tr -d ' ')
log "缓存窗口内 post 数: $CACHE_WIN_COUNT"

# ─── 步骤 1：limit=3 探针，挑窗口内 created_at 最大的那条做命中判断 ───
# 拉 3 条而不是 1 条，是为了穿透 X 的置顶 post（置顶 created_at 远早于 SINCE，
# 直接 limit=1 会一直拿到置顶导致这步白做）。
LATEST_ID=""
if [ "$REFRESH" != 1 ] && [ "$CACHE_WIN_COUNT" -gt 0 ]; then
  LATEST_JSON="$(autocli_locked twitter user-posts \
    --username "$USERNAME" --limit 3 --format json 2>/dev/null || true)"
  # 挑窗口内（created_at >= SINCE）created_at 最大的那条 id
  LATEST_ID="$(printf '%s' "$LATEST_JSON" | jq -r --arg s "$SINCE_ISO" \
    '[.[] | select((.created_at // "") >= $s)] | sort_by(.created_at) | last | .id // empty' \
    2>/dev/null || true)"

  if [ -n "$LATEST_ID" ] && in_cache_window "$LATEST_ID"; then
    log "窗口内最新一条 id=$LATEST_ID 已在缓存 → 直接走缓存"
    output_window
    exit 0
  fi
  if [ -n "$LATEST_ID" ]; then
    log "窗口内最新一条 id=$LATEST_ID 不在缓存 → 进入增量探针"
  else
    log "limit=3 探针窗口内 0 条（全是置顶/限流？）→ 仍尝试增量"
  fi
fi

# ─── 步骤 2：增量探针，PROBE 从 INITIAL_LIMIT 起翻倍，找命中点或越过 SINCE ───
PROBE="$INITIAL_LIMIT"
NEW_IDS_FILE="$TMP_WORK/new_ids"
: >"$NEW_IDS_FILE"
LAST_LIST_JSON="[]"

while : ; do
  log "probe limit=$PROBE"
  LIST_JSON="$(autocli_locked twitter user-posts \
    --username "$USERNAME" --limit "$PROBE" --format json 2>/dev/null || true)"
  [ -z "$LIST_JSON" ] && LIST_JSON="[]"
  LAST_LIST_JSON="$LIST_JSON"

  LIST_LEN="$(printf '%s' "$LIST_JSON" | jq 'length' 2>/dev/null || echo 0)"
  if [ "$LIST_LEN" -eq 0 ]; then
    log "autocli 返回 0 条（限流/登录失效），按缓存兜底"
    output_window
    exit 0
  fi

  # 在 LIST 里找第一个命中缓存窗口的 id（跳过 created_at < SINCE 的置顶 post）
  HIT_IDX=-1
  IDX=0
  while IFS=$'\t' read -r pid ts; do
    [ -z "$pid" ] && { IDX=$((IDX+1)); continue; }
    # 置顶（ts 早于 SINCE）跳过——既不算命中也不算新增
    if [ -n "$ts" ] && [ "$ts" \< "$SINCE_ISO" ]; then
      IDX=$((IDX+1)); continue
    fi
    if in_cache_window "$pid"; then
      HIT_IDX="$IDX"
      break
    fi
    IDX=$((IDX+1))
  done < <(printf '%s' "$LIST_JSON" | jq -r '.[] | "\(.id)\t\(.created_at // "")"')

  if [ "$HIT_IDX" -ge 0 ]; then
    log "在第 $((HIT_IDX+1)) 条命中缓存 → 取窗口内、命中点之前的为新增"
    # 切到 HIT_IDX 之前，再筛 created_at >= SINCE（自动滤掉置顶）
    printf '%s' "$LIST_JSON" | jq -r --argjson n "$HIT_IDX" --arg s "$SINCE_ISO" \
      '.[0:$n] | .[] | select((.created_at // "") >= $s) | .id' >"$NEW_IDS_FILE"
    break
  fi

  EARLIEST_TS="$(printf '%s' "$LIST_JSON" | jq -r '.[-1].created_at // ""' 2>/dev/null || true)"
  if [ -n "$EARLIEST_TS" ] && [ "$EARLIEST_TS" \< "$SINCE_ISO" ]; then
    log "最早一条 ts=$EARLIEST_TS 已早于 SINCE → 列表覆盖完整，取窗口内全部为新增"
    printf '%s' "$LIST_JSON" | jq -r --arg s "$SINCE_ISO" \
      '.[] | select(.created_at >= $s) | .id' >"$NEW_IDS_FILE"
    break
  fi

  # autocli 返回条数 < 请求 limit，说明已经拉到该用户时间线尽头，没必要继续翻倍
  if [ "$LIST_LEN" -lt "$PROBE" ]; then
    log "返回 $LIST_LEN < probe $PROBE → 已到时间线尽头，取窗口内全部为新增"
    printf '%s' "$LIST_JSON" | jq -r --arg s "$SINCE_ISO" \
      '.[] | select(.created_at >= $s) | .id' >"$NEW_IDS_FILE"
    break
  fi

  if [ "$PROBE" -ge "$MAX_PROBE_LIMIT" ]; then
    log "warn: 探针达到上限 ${MAX_PROBE_LIMIT}，仍未越过 SINCE，按当前列表全量为新增"
    printf '%s' "$LIST_JSON" | jq -r --arg s "$SINCE_ISO" \
      '.[] | select(.created_at >= $s) | .id' >"$NEW_IDS_FILE"
    break
  fi
  PROBE=$((PROBE * 2))
  [ "$PROBE" -gt "$MAX_PROBE_LIMIT" ] && PROBE="$MAX_PROBE_LIMIT"
done

NEW_COUNT=$(grep -c . "$NEW_IDS_FILE" 2>/dev/null || true)
NEW_COUNT="${NEW_COUNT:-0}"
log "需要拉 detail 的新 post: $NEW_COUNT 条"

# ─── 步骤 3：对新 ids 拉一次带 detail + 下载媒体，写入 cache ───
if [ "$NEW_COUNT" -gt 0 ]; then
  log "拉详情 + 下载图片 → $CACHE_DIR (probe=$PROBE)"
  if [ -f "$DOWNLOAD_MEDIA" ]; then
    DETAIL_JSON="$(autocli_locked twitter user-posts \
      --username "$USERNAME" --limit "$PROBE" --include-detail true --format json 2>/dev/null \
      | python3 "$DOWNLOAD_MEDIA" --output "$CACHE_ROOT" --pretty 2>/dev/null || true)"
  else
    log "warn: 找不到 download-media.py，仅保存 detail JSON 不下载图片"
    DETAIL_JSON="$(autocli_locked twitter user-posts \
      --username "$USERNAME" --limit "$PROBE" --include-detail true --format json 2>/dev/null || true)"
  fi
  [ -z "$DETAIL_JSON" ] && DETAIL_JSON="[]"

  while IFS= read -r pid; do
    [ -z "$pid" ] && continue
    POST="$(printf '%s' "$DETAIL_JSON" | jq --arg id "$pid" 'map(select(.id == $id)) | first')"
    if [ "$POST" = "null" ] || [ -z "$POST" ]; then
      log "warn: 详情结果里找不到 id=${pid}（可能在第二次抓取时滑出窗口）"
      continue
    fi
    printf '%s\n' "$POST" | jq '.' >"$CACHE_DIR/$pid.json"
    log "保存 cache/$USERNAME/$pid.json"
  done <"$NEW_IDS_FILE"
fi

# ─── 步骤 4：合并输出窗口内的全部缓存 ───
output_window
