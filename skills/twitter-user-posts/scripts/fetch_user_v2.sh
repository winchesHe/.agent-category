#!/usr/bin/env bash
# 拉取一个或多个 X handle 在最近 HOURS 小时内的全部 post，list-then-diff 缓存。
#
# 单 handle / 多 handle 都用同一架构：autocli twitter user-posts --usernames "h1,h2,..."
# 一次 navigate，整批共享 cookies；失败的 handle 会在 stderr 报告。
#
# 用法:
#   ./fetch_user_v2.sh <handle>
#   ./fetch_user_v2.sh <handle1> <handle2> ...
#   ./fetch_user_v2.sh "h1,h2,h3"
#
# 环境变量:
#   TWITTER_POSTS_HOURS         窗口小时数（滚动），默认 24
#   TWITTER_POSTS_LIST_LIMIT    一次 GQL list 拉多少条，默认 30
#   TWITTER_POSTS_REFRESH       =1 时把窗口内全部当未命中重拉
#   TWITTER_POSTS_INTER_USER_MS 批量内 handle 间间隔毫秒，默认 1500（节流防 429）
#
# 输出（stdout）: 全部 handle 的 cache 窗口 post 合并 JSON 数组，按 created_at 倒序。

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "用法: $0 <handle> [handle2 ...]  或  $0 \"h1,h2,h3\"" >&2
  exit 2
fi

# 收集所有 handle：支持位置参数 + 单个参数里的逗号
HANDLES=()
for arg in "$@"; do
  IFS=',' read -ra parts <<<"$arg"
  for h in "${parts[@]}"; do
    h="${h#"${h%%[![:space:]]*}"}"
    h="${h%"${h##*[![:space:]]}"}"
    h="${h#@}"
    [ -n "$h" ] && HANDLES+=("$h")
  done
done

if [ "${#HANDLES[@]}" -eq 0 ]; then
  echo "error: 没解析出任何 handle" >&2
  exit 2
fi

HOURS="${TWITTER_POSTS_HOURS:-24}"
LIST_LIMIT="${TWITTER_POSTS_LIST_LIMIT:-30}"
REFRESH="${TWITTER_POSTS_REFRESH:-0}"
INTER_USER_MS="${TWITTER_POSTS_INTER_USER_MS:-1500}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { printf '[fetch_user_v2] %s\n' "$*" >&2; }

# rest_id 缓存（与 fetch_all_v2.sh 共享）
USER_IDS_CACHE="$SKILL_DIR/cache/.user_ids.json"
mkdir -p "$(dirname "$USER_IDS_CACHE")"
[ -f "$USER_IDS_CACHE" ] || echo '{}' >"$USER_IDS_CACHE"

build_user_ids_arg() {
  local pairs=()
  for h in "$@"; do
    local id
    id=$(jq -r --arg h "$h" '.[$h] // empty' "$USER_IDS_CACHE")
    [ -n "$id" ] && pairs+=("$h=$id")
  done
  if [ "${#pairs[@]}" -gt 0 ]; then
    (IFS=,; printf '%s' "${pairs[*]}")
  fi
}

update_user_ids_cache() {
  local batch_json_file="$1"
  local mapping
  mapping=$(jq '
    [.[]
     | select(.requested_username and ._rest_id)
     | {key: .requested_username, value: ._rest_id}
    ] | from_entries
  ' "$batch_json_file" 2>/dev/null)
  if [ -z "$mapping" ] || [ "$mapping" = "null" ] || [ "$mapping" = "{}" ]; then
    return 0
  fi
  local merged
  merged=$(jq -s '.[0] + .[1]' "$USER_IDS_CACHE" <(echo "$mapping"))
  [ -n "$merged" ] && printf '%s\n' "$merged" >"$USER_IDS_CACHE"
}

# autocli 跨进程互斥锁
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

TMP_WORK="$(mktemp -d)"
trap '[ "$_lock_owned" = 1 ] && rmdir "$AUTOCLI_LOCK" 2>/dev/null || true; rm -rf "$TMP_WORK"' EXIT

HANDLES_CSV="$(IFS=,; echo "${HANDLES[*]}")"
log "handles=${HANDLES_CSV} hours=$HOURS list_limit=$LIST_LIMIT refresh=$REFRESH"

# ─── GQL 调用：单 handle 用 --username，多 handle 用 --usernames ───
LIST_STDERR="$TMP_WORK/list.stderr"

# 从 cache 拼 --user-ids（命中即跳过 UserByScreenName）
USER_IDS_ARG="$(build_user_ids_arg "${HANDLES[@]}")"
USER_IDS_FLAGS=()
[ -n "$USER_IDS_ARG" ] && USER_IDS_FLAGS=(--user-ids "$USER_IDS_ARG")

PRIMARY_HANDLE="${HANDLES[0]}"

if [ "${#HANDLES[@]}" -eq 1 ]; then
  CACHED_HINT=""
  [ -n "$USER_IDS_ARG" ] && CACHED_HINT=" [rest_id 缓存命中]"
  log "GQL single (--username ${HANDLES[0]} --limit $LIST_LIMIT)$CACHED_HINT"
  if ! ALL_JSON="$(autocli_locked twitter user-posts \
      --username "${HANDLES[0]}" --limit "$LIST_LIMIT" \
      --primary-handle "$PRIMARY_HANDLE" \
      ${USER_IDS_FLAGS[@]:+"${USER_IDS_FLAGS[@]}"} \
      --format json 2>"$LIST_STDERR")"; then
    log "error: autocli 调用失败"
    cat "$LIST_STDERR" >&2 || true
    exit 1
  fi
else
  CACHED_HINT=""
  if [ -n "$USER_IDS_ARG" ]; then
    CACHED_HINT=" [rest_id 缓存命中: $(printf '%s\n' "$USER_IDS_ARG" | tr ',' '\n' | wc -l | tr -d ' ')/${#HANDLES[@]}]"
  fi
  log "GQL batch (--usernames \"$HANDLES_CSV\" --limit $LIST_LIMIT --inter-user-ms $INTER_USER_MS)$CACHED_HINT"
  if ! ALL_JSON="$(autocli_locked twitter user-posts \
      --usernames "$HANDLES_CSV" \
      --limit "$LIST_LIMIT" \
      --inter-user-ms "$INTER_USER_MS" \
      --primary-handle "$PRIMARY_HANDLE" \
      ${USER_IDS_FLAGS[@]:+"${USER_IDS_FLAGS[@]}"} \
      --format json 2>"$LIST_STDERR")"; then
    log "error: 批量 autocli 调用失败"
    cat "$LIST_STDERR" >&2 || true
    if grep -q 'HTTP 429' "$LIST_STDERR" 2>/dev/null; then
      log "⛔️ 命中 X 429 限流，请等 5-15 分钟后再试"
    fi
    exit 1
  fi
fi

if [ -z "$ALL_JSON" ] || [ "$ALL_JSON" = "null" ] || [ "$ALL_JSON" = "[]" ]; then
  log "warn: GQL 返回空（X 限流/瞬时空响应）→ 全部用 cache 兜底"
  cat "$LIST_STDERR" >&2 || true
  ALL_JSON='[]'
fi
echo "$ALL_JSON" >"$TMP_WORK/all.json"
ALL_LEN="$(jq 'length' "$TMP_WORK/all.json" 2>/dev/null || echo 0)"
log "ALL_JSON 解析后长度=$ALL_LEN"

# 更新 rest_id 缓存
update_user_ids_cache "$TMP_WORK/all.json"

# 局部失败提示（adapter warnings 里）
PER_USER_FAILS="$(jq -r '[.[].warnings[]?] | map(select(test("^fetch failed for "))) | unique | .[]' "$TMP_WORK/all.json" 2>/dev/null || true)"
if [ -n "$PER_USER_FAILS" ]; then
  log "warn: adapter 报告以下 handle 局部失败:"
  printf '%s\n' "$PER_USER_FAILS" | while IFS= read -r w; do log "  - $w"; done
fi

# ─── 按 requested_username 切分 → _process_user.sh per-user → 合并输出 ───
COMBINED="$TMP_WORK/combined.json"
echo '[]' >"$COMBINED"

for handle in "${HANDLES[@]}"; do
  USER_INPUT="$TMP_WORK/$handle.input.json"
  jq --arg h "$handle" '[.[] | select(.requested_username == $h)]' "$TMP_WORK/all.json" >"$USER_INPUT"
  USER_LEN="$(jq 'length' "$USER_INPUT")"
  log "$handle: USER_INPUT 命中 $USER_LEN 条 (按 requested_username 切)"

  if [ "$USER_LEN" -eq 0 ]; then
    log "warn: $handle 在 ALL_JSON 里 0 条（X 可能瞬时空响应/限流）→ 用 cache 兜底"
    # 不 continue，传空数组让 _process_user 走 cache window 兜底
  fi

  USER_OUT="$TMP_WORK/$handle.out.json"
  if ! TWITTER_POSTS_HOURS="$HOURS" \
       TWITTER_POSTS_LIST_LIMIT="$LIST_LIMIT" \
       TWITTER_POSTS_REFRESH="$REFRESH" \
       "$SCRIPT_DIR/_process_user.sh" "$handle" "$USER_INPUT" >"$USER_OUT" 2>>"$TMP_WORK/$handle.log"; then
    log "warn: $handle 处理失败"
    cat "$TMP_WORK/$handle.log" >&2 || true
    continue
  fi

  USER_OUT_LEN="$(jq 'length' "$USER_OUT" 2>/dev/null || echo 0)"
  log "$handle: _process_user 输出 $USER_OUT_LEN 条 (cache 窗口内)"
  if [ -s "$TMP_WORK/$handle.log" ]; then
    log "$handle: _process_user log:"
    while IFS= read -r line; do log "    $line"; done <"$TMP_WORK/$handle.log"
  fi

  # 累加到 combined
  jq -s '.[0] + .[1]' "$COMBINED" "$USER_OUT" >"$COMBINED.tmp" && mv "$COMBINED.tmp" "$COMBINED"
done

COMBINED_LEN="$(jq 'length' "$COMBINED" 2>/dev/null || echo 0)"
log "COMBINED 总计 $COMBINED_LEN 条 → 输出"

# 按 created_at 倒序输出
jq 'sort_by(.created_at // "") | reverse' "$COMBINED"
