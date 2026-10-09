#!/usr/bin/env bash
# 并发批量拉取 users.txt 里所有用户最近 HOURS 小时的 post（list-then-diff 缓存策略），
# 输出"用户名 + 内容 + 创建时间"格式的文本报告。
#
# v2 批量优化：
#   - 一次 autocli 调用 (twitter user-posts --usernames "h1,h2,...") 拉所有用户
#   - 整批共享一次 navigate（cookies 只刷新一次，省 N×3s）
#   - 单用户失败不影响整批；命中 429 立刻中止后续
#
# 用法:
#   ./fetch_all_v2.sh [--hours N] [--list-limit N] [--inter-user-ms N] [--batch-size N] [--refresh] [--json]
#
# 选项:
#   --hours N           窗口小时数（滚动，默认 24）
#   --list-limit N      每个用户拉多少条候选（默认 30；窗口大或博主活跃时调高）
#   --inter-user-ms N   adapter 内部用户间间隔毫秒（默认 1500，节流防 429）
#   --batch-size N      每次 autocli 调用最多打包多少 handle（默认 6，超过 daemon 30s 超时风险）
#   --refresh           全部 id 当未命中重拉（覆盖现有 cache）
#   --json              额外把每用户的完整 JSON 以 NDJSON 输出到 fd 3
#
# 输出（stdout）: 中文报告，按 users.txt 顺序，每用户下按时间倒序。
# 进度日志走 stderr。
#
# 限流处理：
#   - adapter 内部命中 429 → 抛错；脚本整批退出非零（已抓的部分不会被丢弃，
#     但 stdout 报告不再渲染，便于调用方明确感知）。
#   - 不要循环重跑；429 后冷却 5-15 分钟再试。

set -euo pipefail

HOURS=24
LIST_LIMIT=30
INTER_USER_MS=1500
BATCH_SIZE=4
EMIT_JSON=0
REFRESH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --hours)          HOURS="$2"; shift 2 ;;
    --list-limit)     LIST_LIMIT="$2"; shift 2 ;;
    --inter-user-ms)  INTER_USER_MS="$2"; shift 2 ;;
    --batch-size)     BATCH_SIZE="$2"; shift 2 ;;
    --json)           EMIT_JSON=1; shift ;;
    --refresh)        REFRESH=1; shift ;;
    -h|--help)
      sed -n '2,28p' "$0"
      exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
USERS_FILE="$SKILL_DIR/users.txt"

log() { printf '[fetch_all_v2] %s\n' "$*" >&2; }

if [ ! -f "$USERS_FILE" ]; then
  log "找不到 $USERS_FILE"; exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 解析 users.txt：每行 "handle,username"
ROWS=()
HANDLES=()
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [ -z "$line" ] && continue
  if [[ "$line" == *,* ]]; then
    handle="${line%%,*}"
    uname="${line#*,}"
    handle="${handle#"${handle%%[![:space:]]*}"}"
    handle="${handle%"${handle##*[![:space:]]}"}"
    uname="${uname#"${uname%%[![:space:]]*}"}"
    uname="${uname%"${uname##*[![:space:]]}"}"
  else
    handle="$line"
    uname="$line"
  fi
  ROWS+=("$handle"$'\t'"$uname")
  HANDLES+=("$handle")
done < "$USERS_FILE"

N="${#ROWS[@]}"
log "用户数=$N batch_size=$BATCH_SIZE list_limit=$LIST_LIMIT hours=$HOURS inter_user_ms=$INTER_USER_MS refresh=$REFRESH"

# rest_id 缓存：handle → rest_id 的 JSON 字典，避免重复打 UserByScreenName（X 限流最严的端点）
USER_IDS_CACHE="$SKILL_DIR/cache/.user_ids.json"
mkdir -p "$(dirname "$USER_IDS_CACHE")"
[ -f "$USER_IDS_CACHE" ] || echo '{}' >"$USER_IDS_CACHE"

# 给定 handle 列表，构造 --user-ids "h1=id1,h2=id2" 形式（仅含已缓存的）
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

# 从 batch 返回 JSON 中提取 handle→rest_id，merge 进缓存文件
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
  if [ -n "$merged" ]; then
    printf '%s\n' "$merged" >"$USER_IDS_CACHE"
  fi
}

# autocli 锁（与 fetch_user_v2.sh 共享同一锁，确保多脚本并行也安全）
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
trap '[ "$_lock_owned" = 1 ] && rmdir "$AUTOCLI_LOCK" 2>/dev/null || true; rm -rf "$TMP"' EXIT

# ─── 分批 autocli 调用：每批 <= BATCH_SIZE 个 handle，避免 daemon 30s 超时 ───
echo '[]' >"$TMP/all.json"
ALL_STDERR="$TMP/all.stderr"

i=0
batch_idx=0
while [ "$i" -lt "$N" ]; do
  end=$((i + BATCH_SIZE))
  [ "$end" -gt "$N" ] && end="$N"
  BATCH_HANDLES=("${HANDLES[@]:i:$((end - i))}")
  BATCH_CSV="$(IFS=,; echo "${BATCH_HANDLES[*]}")"
  batch_idx=$((batch_idx + 1))

  # 拼 --user-ids（已缓存的 handle 跳过 UserByScreenName）
  USER_IDS_ARG="$(build_user_ids_arg "${BATCH_HANDLES[@]}")"
  USER_IDS_FLAGS=()
  CACHED_HINT=""
  if [ -n "$USER_IDS_ARG" ]; then
    USER_IDS_FLAGS=(--user-ids "$USER_IDS_ARG")
    CACHED_HINT=" [rest_id 缓存命中: $(printf '%s\n' "$USER_IDS_ARG" | tr ',' '\n' | wc -l | tr -d ' ')/${#BATCH_HANDLES[@]}]"
  fi
  log "batch $batch_idx (handles $((i+1))-$end / $N): --usernames \"$BATCH_CSV\"$CACHED_HINT"

  : >"$ALL_STDERR"
  if ! BATCH_JSON="$(autocli_locked twitter user-posts \
      --usernames "$BATCH_CSV" \
      --limit "$LIST_LIMIT" \
      --inter-user-ms "$INTER_USER_MS" \
      --primary-handle "${BATCH_HANDLES[0]}" \
      ${USER_IDS_FLAGS[@]:+"${USER_IDS_FLAGS[@]}"} \
      --format json 2>"$ALL_STDERR")"; then
    log "error: batch $batch_idx 失败"
    cat "$ALL_STDERR" >&2 || true
    if grep -q 'HTTP 429' "$ALL_STDERR" 2>/dev/null; then
      log "⛔️ 命中 X 429 限流，请等 5-15 分钟后再试，不要循环重跑"
      exit 1
    fi
    if grep -q 'timed out after' "$ALL_STDERR" 2>/dev/null; then
      log "⏱️  本批超时，建议下次用更小的 --batch-size（当前 ${BATCH_SIZE}）"
    fi
    # 单批失败不中止：继续后续批，让能拿到的都拿到
  else
    [ -z "$BATCH_JSON" ] && BATCH_JSON="[]"
    # 写当前 batch 到临时文件，更新 user_ids 缓存
    BATCH_FILE="$TMP/batch_$batch_idx.json"
    printf '%s\n' "$BATCH_JSON" >"$BATCH_FILE"
    update_user_ids_cache "$BATCH_FILE"
    # 累加到 all.json
    jq -s '.[0] + .[1]' "$TMP/all.json" "$BATCH_FILE" >"$TMP/all.json.new" \
      && mv "$TMP/all.json.new" "$TMP/all.json"
  fi
  i="$end"
done

if [ "$(jq 'length' "$TMP/all.json")" = "0" ]; then
  log "warn: 所有批次都没拉到数据（X 限流/瞬时空响应）→ 全部用 cache 兜底"
fi

# adapter warnings 里可能含 per-user 失败信息（命中 429 已经在 adapter 抛了；
# 这里捕获其它失败的 handle，比如 UserByScreenName 失败）
PER_USER_FAILS="$(jq -r '[.[].warnings[]?] | map(select(test("^fetch failed for "))) | unique | .[]' "$TMP/all.json" 2>/dev/null || true)"
if [ -n "$PER_USER_FAILS" ]; then
  log "warn: adapter 报告以下用户局部失败:"
  printf '%s\n' "$PER_USER_FAILS" | while IFS= read -r w; do log "  - $w"; done
fi

# 计算 SINCE
NOW_SEC=$(date +%s)
SINCE_SEC=$((NOW_SEC - HOURS * 3600))
SINCE_ISO="$(date -u -r "$SINCE_SEC" +'%Y-%m-%dT%H:%M:%SZ')"
NOW_LOCAL="$(date +'%Y-%m-%d %H:%M:%S')"

log "时间窗口起点(UTC) = $SINCE_ISO"

# ─── 按 requested_username 切分 + 调 _process_user.sh per-user 处理 ───
: >"$TMP/result.tsv"
for ((j=0; j<N; j++)); do
  row="${ROWS[$j]}"
  handle="${row%%$'\t'*}"
  uname="${row#*$'\t'}"
  line_no=$((j+1))

  USER_INPUT="$TMP/$handle.input.json"
  jq --arg h "$handle" '[.[] | select(.requested_username == $h)]' "$TMP/all.json" >"$USER_INPUT"
  USER_LEN="$(jq 'length' "$USER_INPUT")"

  if [ "$USER_LEN" -eq 0 ]; then
    # 这个 handle 在 ALL_JSON 里 0 条 → X 瞬时空响应/限流；不 skip，让 _process_user 走 cache 兜底
    log "warn: $handle 在 ALL_JSON 里 0 条 → 用 cache 兜底"
  fi

  # 调 helper 处理（窗口过滤 / cache diff / 下图 / 写 cache / 输出）
  TWITTER_POSTS_HOURS="$HOURS" \
  TWITTER_POSTS_LIST_LIMIT="$LIST_LIMIT" \
  TWITTER_POSTS_REFRESH="$REFRESH" \
    "$SCRIPT_DIR/_process_user.sh" "$handle" "$USER_INPUT" >"$TMP/$handle.json" 2>>"$TMP/$handle.log" || {
      printf '%s\t%s\t%s\tfail\n' "$line_no" "$handle" "$uname" >>"$TMP/result.tsv"
      continue
    }
  printf '%s\t%s\t%s\tok\n' "$line_no" "$handle" "$uname" >>"$TMP/result.tsv"
done

# ─── 渲染报告 ───
printf '# 推特用户监控报告\n'
printf '生成时间: %s    时间窗口: 最近 %s 小时 (since %s)\n\n' "$NOW_LOCAL" "$HOURS" "$SINCE_ISO"

TOTAL_POSTS=0
while IFS=$'\t' read -r line_no handle uname status; do
  printf '## %s (@%s)\n' "$uname" "$handle"
  if [ "$status" != "ok" ]; then
    printf '  ⚠️ 拉取失败\n\n'
    continue
  fi

  # 文件不存在/不可解析时，FILTERED 兜底为 []
  if [ ! -s "$TMP/$handle.json" ]; then
    FILTERED='[]'
  else
    FILTERED="$(jq --arg since "$SINCE_ISO" \
      '[.[] | select((.created_at // "") >= $since)] | sort_by(.created_at) | reverse' \
      "$TMP/$handle.json" 2>/dev/null)"
    [ -z "$FILTERED" ] && FILTERED='[]'
  fi

  CNT="$(jq 'length' <<<"$FILTERED" 2>/dev/null || echo 0)"
  CNT="${CNT:-0}"
  TOTAL_POSTS=$((TOTAL_POSTS + CNT))

  if [ "$CNT" -eq 0 ]; then
    printf '  (近 %s 小时无新动态)\n\n' "$HOURS"
    continue
  fi
  printf '  共 %s 条\n\n' "$CNT"

  jq -r --arg uname "$uname" --arg handle "$handle" '
    .[] |
    "### " + $uname + " (@" + $handle + ")  ·  " + (.created_at // "?") + "\n" +
    (.content // "") + "\n\n" +
    "  " + (.url // "") + "\n" +
    (if (.has_article // false) and ((.article_title // "") | length > 0)
       then "  📰 article: " + .article_title + "\n" else "" end) +
    (if (.local_media_paths // []) | length > 0
       then "  🖼  media: " + ((.local_media_paths // []) | join(", ")) + "\n"
     elif (.media_urls // []) | length > 0
       then "  🖼  media_urls: " + ((.media_urls // []) | join(", ")) + "\n"
       else "" end)
  ' <<<"$FILTERED"

  printf '\n'
done < <(sort -n -k1,1 "$TMP/result.tsv")

printf -- '---\n汇总: 用户 %s 个，时间窗口内 post 共 %s 条\n' "$N" "$TOTAL_POSTS"

if [ "$EMIT_JSON" = 1 ] && { true >&3; } 2>/dev/null; then
  while IFS=$'\t' read -r line_no handle uname status; do
    [ "$status" = "ok" ] || continue
    POSTS="$(cat "$TMP/$handle.json")"
    jq -nc --arg h "$handle" --arg u "$uname" --argjson p "$POSTS" \
      '{handle: $h, username: $u, posts: $p}' >&3
  done < <(sort -n -k1,1 "$TMP/result.tsv")
fi
