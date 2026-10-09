#!/usr/bin/env bash
# 并发批量拉取 users.txt 里所有用户最近 N 条 post（带缓存），
# 按 --days 过滤后输出"用户名 + 内容 + 创建时间"格式的文本报告。
#
# 用法:
#   ./fetch_all.sh [--days N] [--limit N] [--concurrency N] [--refresh] [--json]
#
# 选项:
#   --days N         窗口天数（本地日历日，默认 1 即仅今天）；窗口决定 fetch_user 的同步范围
#   --limit N        探针起步 limit（默认 20，会按需翻倍）
#   --concurrency N  并发数（默认 3，autocli 调用受全局锁串行化）
#   --refresh        跳过 limit=1 探针，直接走增量（适合刚更新过又想再确认）
#   --json           额外把每用户的完整 JSON 也输出（NDJSON，到 stderr 之外的 fd 3）
#
# 输出（stdout）: 人类可读的中文报告，按 users.txt 里的 id 排序，
#                每个用户下按时间倒序列出最近 N 天的 post。
# 进度日志走 stderr。

set -euo pipefail

DAYS=1
LIMIT=20
CONCURRENCY=3
EMIT_JSON=0
REFRESH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --days)         DAYS="$2"; shift 2 ;;
    --limit)        LIMIT="$2"; shift 2 ;;
    --concurrency)  CONCURRENCY="$2"; shift 2 ;;
    --json)         EMIT_JSON=1; shift ;;
    --refresh)      REFRESH=1; shift ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
USERS_FILE="$SKILL_DIR/users.txt"

log() { printf '[fetch_all] %s\n' "$*" >&2; }

if [ ! -f "$USERS_FILE" ]; then
  log "找不到 $USERS_FILE"; exit 1
fi

# 解析 users.txt：每行 "handle,username"
#   handle   = X URL 里的 screen_name (传给 autocli)
#   username = X profile 显示名 (报告里展示)
# 兼容旧行：纯 "handle" 时 username 直接复用 handle。
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ROWS=()  # 每行 "handle<TAB>username"，保留 users.txt 中的原始顺序
while IFS= read -r line || [ -n "$line" ]; do
  # 去掉 # 注释和首尾空白（不能 tr -d 空白，username 里可能有空格）
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [ -z "$line" ] && continue
  if [[ "$line" == *,* ]]; then
    handle="${line%%,*}"
    uname="${line#*,}"
    # 去掉 handle/uname 各自的两端空白
    handle="${handle#"${handle%%[![:space:]]*}"}"
    handle="${handle%"${handle##*[![:space:]]}"}"
    uname="${uname#"${uname%%[![:space:]]*}"}"
    uname="${uname%"${uname##*[![:space:]]}"}"
  else
    handle="$line"
    uname="$line"
  fi
  ROWS+=("$handle"$'\t'"$uname")
done < "$USERS_FILE"

log "用户数=${#ROWS[@]} concurrency=$CONCURRENCY limit=$LIMIT days=$DAYS refresh=$REFRESH"
export TWITTER_POSTS_REFRESH="$REFRESH"
export TWITTER_POSTS_DAYS="$DAYS"

# 并发跑 fetch_user.sh，按 chunk 模式（每批 CONCURRENCY 个，等完再起下一批）。
# 不用 wait -n / xargs，确保在 macOS 默认 bash 3.2 上也稳。
# result.tsv 字段: <line_no>\t<handle>\t<username>\t<ok|fail>
: >"$TMP/result.tsv"
N="${#ROWS[@]}"
i=0
while [ "$i" -lt "$N" ]; do
  pids=()
  end=$(( i + CONCURRENCY ))
  [ "$end" -gt "$N" ] && end="$N"
  for ((j=i; j<end; j++)); do
    row="${ROWS[$j]}"
    handle="${row%%$'\t'*}"
    uname="${row#*$'\t'}"
    line_no=$((j+1))
    (
      if "$SCRIPT_DIR/fetch_user.sh" "$handle" "$LIMIT" \
            >"$TMP/$handle.json" 2>>"$TMP/$handle.log"; then
        printf '%s\t%s\t%s\tok\n' "$line_no" "$handle" "$uname" >>"$TMP/result.tsv"
      else
        printf '%s\t%s\t%s\tfail\n' "$line_no" "$handle" "$uname" >>"$TMP/result.tsv"
      fi
    ) &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do wait "$pid" || true; done
  i="$end"
done

# 计算时间窗口起点 SINCE_ISO（本地今天 00:00 → 往前 DAYS-1 天，转 UTC ISO8601）
# 与 fetch_user.sh 保持一致：days=1 = 仅今天，days=3 = 含今天的最近 3 天
TODAY_DATE="$(date +'%Y-%m-%d')"
if SINCE_LOCAL_SEC=$(date -j -v-$((DAYS-1))d -f '%Y-%m-%d %H:%M:%S' "$TODAY_DATE 00:00:00" +%s 2>/dev/null); then
  :
else
  SINCE_LOCAL_SEC=$(date -d "$TODAY_DATE 00:00:00 - $((DAYS-1)) days" +%s)
fi
SINCE_ISO="$(date -u -r "$SINCE_LOCAL_SEC" +'%Y-%m-%dT%H:%M:%SZ')"
NOW_LOCAL="$(date +'%Y-%m-%d %H:%M:%S')"

log "时间窗口起点(UTC) = $SINCE_ISO"

# 输出报告头
printf '# 推特用户监控报告\n'
printf '生成时间: %s    时间窗口: 最近 %s 天 (since %s)\n\n' "$NOW_LOCAL" "$DAYS" "$SINCE_ISO"

TOTAL_POSTS=0
# 按 users.txt 原始顺序（line_no 升序）输出
while IFS=$'\t' read -r line_no handle uname status; do
  printf '## %s (@%s)' "$uname" "$handle"
  if [ "$status" != "ok" ]; then
    printf '  ⚠️ 拉取失败\n\n'
    continue
  fi

  # 过滤时间窗口内的 post，按 created_at 倒序
  FILTERED="$(jq --arg since "$SINCE_ISO" \
    '[.[] | select((.created_at // "") >= $since)] | sort_by(.created_at) | reverse' \
    "$TMP/$handle.json" 2>/dev/null || echo '[]')"

  CNT="$(jq 'length' <<<"$FILTERED")"
  TOTAL_POSTS=$((TOTAL_POSTS + CNT))

  if [ "$CNT" -eq 0 ]; then
    printf '  (近 %s 天无新动态)\n\n' "$DAYS"
    continue
  fi
  printf '  共 %s 条\n\n' "$CNT"

  # 逐条渲染：用户名（显示名）/ 创建时间 / 内容 / 链接 / 媒体 / metrics
  jq -r --arg uname "$uname" --arg handle "$handle" '
    .[] |
    "### " + $uname + " (@" + $handle + ")  ·  " + (.created_at // "?") + "\n" +
    (.content // "") + "\n\n" +
    "  🔗 " + (.url // "") + "\n" +
    (if (.has_article // false) and ((.article_title // "") | length > 0)
       then "  📰 article: " + .article_title + "\n" else "" end) +
    (if (.local_media_paths // []) | length > 0
       then "  🖼  media: " + ((.local_media_paths // []) | join(", ")) + "\n"
     elif (.media_urls // []) | length > 0
       then "  🖼  media_urls: " + ((.media_urls // []) | join(", ")) + "\n"
       else "" end) +
    "  📊 likes=" + ((.metrics.likes // 0) | tostring) +
    " replies=" + ((.metrics.replies // 0) | tostring) +
    " reposts=" + ((.metrics.reposts // 0) | tostring) +
    " views=" + ((.metrics.views // 0) | tostring) + "\n"
  ' <<<"$FILTERED"

  printf '\n'
done < <(sort -n -k1,1 "$TMP/result.tsv")

printf -- '---\n汇总: 用户 %s 个，时间窗口内 post 共 %s 条\n' "${#ROWS[@]}" "$TOTAL_POSTS"

# 可选：把完整 JSON 也以 NDJSON 形式输出到 fd 3（如果调用方打开了）
if [ "$EMIT_JSON" = 1 ] && { true >&3; } 2>/dev/null; then
  while IFS=$'\t' read -r line_no handle uname status; do
    [ "$status" = "ok" ] || continue
    POSTS="$(cat "$TMP/$handle.json")"
    jq -nc --arg h "$handle" --arg u "$uname" --argjson p "$POSTS" \
      '{handle: $h, username: $u, posts: $p}' >&3
  done < <(sort -n -k1,1 "$TMP/result.tsv")
fi
