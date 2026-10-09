#!/usr/bin/env bash
# 内部 helper：拿到某个 handle 的 list JSON 后，做窗口过滤 + cache diff +
# 下图（仅未命中）+ 写 cache + 输出窗口内全部 post（按 created_at 倒序）。
#
# 用法:
#   TWITTER_POSTS_HOURS=24 TWITTER_POSTS_REFRESH=0 \
#     ./_process_user.sh <handle> <input_json_file>
#
# 输入: input_json_file 是该 handle 的 post 数组 JSON（autocli user-posts 输出格式）。
#       脚本会自己按 SINCE 过滤，所以传完整 list（含窗口外的）也 OK。
# 输出: cache 窗口内全部 post（含本次新写的），按 created_at 倒序。stderr 走日志。

set -euo pipefail

HANDLE="${1:?用法: $0 <handle> <input_json_file>}"
INPUT_JSON_FILE="${2:?用法: $0 <handle> <input_json_file>}"
HOURS="${TWITTER_POSTS_HOURS:-24}"
LIST_LIMIT="${TWITTER_POSTS_LIST_LIMIT:-30}"
REFRESH="${TWITTER_POSTS_REFRESH:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CACHE_ROOT="$SKILL_DIR/cache"
CACHE_DIR="$CACHE_ROOT/$HANDLE"
DOWNLOAD_MEDIA="$HOME/.autocli/adapters/twitter/download-media.py"
OCR_SCRIPT="$SCRIPT_DIR/enrich_media_ocr.py"
OCR_ENABLED="${TWITTER_POSTS_OCR:-1}"
OCR_REFRESH="${TWITTER_POSTS_OCR_REFRESH:-0}"

mkdir -p "$CACHE_DIR"

log() { printf '[_process_user:%s] %s\n' "$HANDLE" "$*" >&2; }

# SINCE
NOW_SEC=$(date +%s)
SINCE_SEC=$((NOW_SEC - HOURS * 3600))
SINCE_ISO="$(date -u -r "$SINCE_SEC" +'%Y-%m-%dT%H:%M:%SZ')"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

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
    jq -s '
      map(select(
        (((.created_at // "") >= $ENV.SINCE_ISO)
         and ((((.media_urls // []) | length) == 0 and ((.local_media_paths // []) | length) == 0)
              or ((.ocr_checked_at // "") != "")
              or ($ENV.OCR_ENABLED == "0")))
      )) | sort_by(.created_at // "") | reverse
    ' "${files[@]}"
  fi
}

# 窗口过滤
WIN_JSON="$(jq --arg s "$SINCE_ISO" '[.[] | select((.created_at // "") >= $s)]' "$INPUT_JSON_FILE")"
WIN_LEN="$(printf '%s' "$WIN_JSON" | jq 'length' 2>/dev/null || echo 0)"
LIST_LEN="$(jq 'length' "$INPUT_JSON_FILE" 2>/dev/null || echo 0)"
log "list 总 ${LIST_LEN}，窗口内 ${WIN_LEN}"

# LIST_LIMIT 不够检查
if [ "$WIN_LEN" -gt 0 ] && [ "$WIN_LEN" -eq "$LIST_LEN" ]; then
  EARLIEST_TS="$(jq -r '.[-1].created_at // ""' "$INPUT_JSON_FILE" 2>/dev/null || true)"
  if [ -n "$EARLIEST_TS" ] && [ ! "$EARLIEST_TS" \< "$SINCE_ISO" ]; then
    log "warn: list 最早一条 ${EARLIEST_TS} 仍 ≥ SINCE，LIST_LIMIT 可能不够"
  fi
fi

# diff
NEED_IDS_FILE="$TMP/need_ids"
: >"$NEED_IDS_FILE"
while IFS= read -r pid; do
  [ -z "$pid" ] && continue
  if [ "$REFRESH" = 1 ] || [ ! -f "$CACHE_DIR/$pid.json" ]; then
    printf '%s\n' "$pid" >>"$NEED_IDS_FILE"
  fi
done < <(printf '%s' "$WIN_JSON" | jq -r '.[].id')

NEED_COUNT=$(grep -c . "$NEED_IDS_FILE" 2>/dev/null || true)
NEED_COUNT="${NEED_COUNT:-0}"
HIT_COUNT=$((WIN_LEN - NEED_COUNT))
log "cache diff: 命中 ${HIT_COUNT}，未命中 ${NEED_COUNT}"

# 未命中 → 下图 + OCR + 写 cache
if [ "$NEED_COUNT" -gt 0 ]; then
  NEED_IDS_JSON="$(jq -R . "$NEED_IDS_FILE" | jq -s .)"
  NEED_JSON="$(printf '%s' "$WIN_JSON" | jq --argjson ids "$NEED_IDS_JSON" \
    '[.[] | select(.id as $i | $ids | index($i))]')"

  if [ -f "$DOWNLOAD_MEDIA" ]; then
    UPDATED_JSON="$(printf '%s' "$NEED_JSON" | python3 "$DOWNLOAD_MEDIA" --output "$CACHE_ROOT" --pretty 2>/dev/null || true)"
  else
    log "warn: 找不到 download-media.py，仅保存 JSON 不下载图片"
    UPDATED_JSON="$NEED_JSON"
  fi
  [ -z "$UPDATED_JSON" ] && UPDATED_JSON="[]"

  # 带图片/媒体的 post 必须先 OCR：下载到本地后，用 macOS Vision 提取图中文字。
  # 如果图片下载或 OCR 失败，也写入 ocr_status/ocr_media，供最终报告明确兜底说明。
  if [ "$OCR_ENABLED" != 0 ] && [ -f "$OCR_SCRIPT" ]; then
    if [ "$OCR_REFRESH" = 1 ]; then
      OCR_JSON="$(printf '%s' "$UPDATED_JSON" | python3 "$OCR_SCRIPT" \
        --cache-root "$CACHE_ROOT" --skill-dir "$SKILL_DIR" --pretty --refresh 2>"$TMP/ocr.stderr" || true)"
    else
      OCR_JSON="$(printf '%s' "$UPDATED_JSON" | python3 "$OCR_SCRIPT" \
        --cache-root "$CACHE_ROOT" --skill-dir "$SKILL_DIR" --pretty 2>"$TMP/ocr.stderr" || true)"
    fi
    if [ -n "$OCR_JSON" ] && printf '%s' "$OCR_JSON" | jq empty >/dev/null 2>&1; then
      UPDATED_JSON="$OCR_JSON"
    else
      log "warn: OCR 处理失败，保留原 JSON；stderr=$(tr '\n' ' ' <"$TMP/ocr.stderr" 2>/dev/null | cut -c1-500)"
    fi
  elif [ "$OCR_ENABLED" != 0 ]; then
    log "warn: 找不到 enrich_media_ocr.py，带图 post 将缺少 OCR 字段"
  fi

  while IFS= read -r pid; do
    [ -z "$pid" ] && continue
    POST="$(printf '%s' "$UPDATED_JSON" | jq --arg id "$pid" 'map(select(.id == $id)) | first')"
    if [ "$POST" = "null" ] || [ -z "$POST" ]; then
      log "warn: 落 cache 时找不到 id=$pid"
      continue
    fi
    printf '%s\n' "$POST" | jq '.' >"$CACHE_DIR/$pid.json"
    log "保存 cache/$HANDLE/$pid.json"
  done <"$NEED_IDS_FILE"
fi

# 历史缓存可能没有 OCR 字段或图片路径来自旧目录：输出前补齐/规范化窗口内媒体 OCR。
if [ "$OCR_ENABLED" != 0 ] && [ -f "$OCR_SCRIPT" ]; then
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    NEED_OCR="$(jq -r --arg cache_root "$CACHE_ROOT" '
      (((.media_urls // []) | length) > 0 or ((.local_media_paths // []) | length) > 0)
      and (
        ((.ocr_checked_at // "") == "")
        or (env.TWITTER_POSTS_OCR_REFRESH == "1")
        or (((.local_media_paths // []) | length) > 0 and ([.local_media_paths[] | select(startswith($cache_root) | not)] | length) > 0)
      )
    ' "$f" 2>/dev/null || echo false)"
    [ "$NEED_OCR" = "true" ] || continue
    if [ "$OCR_REFRESH" = 1 ]; then
      OCR_POST="$(python3 "$OCR_SCRIPT" --cache-root "$CACHE_ROOT" --skill-dir "$SKILL_DIR" --pretty --refresh <"$f" 2>"$TMP/ocr-cache.stderr" || true)"
    else
      OCR_POST="$(python3 "$OCR_SCRIPT" --cache-root "$CACHE_ROOT" --skill-dir "$SKILL_DIR" --pretty <"$f" 2>"$TMP/ocr-cache.stderr" || true)"
    fi
    if [ -n "$OCR_POST" ] && printf '%s' "$OCR_POST" | jq empty >/dev/null 2>&1; then
      printf '%s\n' "$OCR_POST" | jq '.' >"$f"
      log "OCR 更新 $(basename "$f")"
    else
      log "warn: OCR 更新失败 $(basename "$f"): $(tr '\n' ' ' <"$TMP/ocr-cache.stderr" 2>/dev/null | cut -c1-300)"
    fi
  done < <(find "$CACHE_DIR" -maxdepth 1 -name '*.json' -type f)
fi

# 输出
output_window
