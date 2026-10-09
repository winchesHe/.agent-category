#!/usr/bin/env python3
"""Enrich X/Twitter post JSON with OCR text extracted from local/downloaded images.

Input: a JSON object or array of post objects on stdin.
Output: the same shape, with these fields on media posts:
  - local_media_paths: normalized/downloaded local image paths when available
  - ocr_media: per-image OCR results
  - ocr_text: concatenated OCR text for model/report consumption
  - ocr_status: ok | partial | empty | failed | no_image_media | unavailable
  - ocr_checked_at: UTC timestamp

OCR backend: macOS Vision via PyObjC. It intentionally avoids tesseract/easyocr
runtime dependencies because this skill runs on macOS where Vision is available.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

VISION_READY = False
VISION_ERROR: Optional[str] = None
VNRecognizeTextRequest = None
VNImageRequestHandler = None
NSURL = None


def load_vision() -> bool:
    """Load Vision.framework classes via PyObjC dynamic lookup."""
    global VISION_READY, VISION_ERROR, VNRecognizeTextRequest, VNImageRequestHandler, NSURL
    if VISION_READY:
        return True
    if VISION_ERROR:
        return False
    try:
        import objc  # type: ignore
        from Foundation import NSBundle, NSURL as _NSURL  # type: ignore

        bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/Vision.framework")
        if bundle is None or not bundle.load():
            raise RuntimeError("failed to load /System/Library/Frameworks/Vision.framework")
        VNRecognizeTextRequest = objc.lookUpClass("VNRecognizeTextRequest")
        VNImageRequestHandler = objc.lookUpClass("VNImageRequestHandler")
        NSURL = _NSURL
        VISION_READY = True
        return True
    except Exception as exc:  # pragma: no cover - environment dependent
        VISION_ERROR = f"{type(exc).__name__}: {exc}"
        return False


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_probably_image_url(url: str) -> bool:
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    fmt = (qs.get("format") or [""])[0].lower()
    if fmt in {"jpg", "jpeg", "png", "webp", "gif", "heic"}:
        return True
    path = parsed.path.lower()
    return bool(re.search(r"\.(jpe?g|png|webp|gif|heic)$", path)) or "pbs.twimg.com/media/" in url


def extension_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    fmt = (qs.get("format") or [""])[0].lower().strip(".")
    if fmt == "jpeg":
        fmt = "jpg"
    if fmt in {"jpg", "png", "webp", "gif", "heic"}:
        return fmt
    m = re.search(r"\.([A-Za-z0-9]+)$", parsed.path)
    if m:
        ext = m.group(1).lower()
        if ext == "jpeg":
            ext = "jpg"
        if ext in {"jpg", "png", "webp", "gif", "heic"}:
            return ext
    return "jpg"


def resolve_existing_path(path_value: Any, cache_root: Path, skill_dir: Path) -> Optional[Path]:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    raw = path_value.strip()
    candidates: List[Path] = []

    if raw.startswith("file://"):
        raw = urllib.parse.unquote(urllib.parse.urlparse(raw).path)

    p = Path(raw).expanduser()
    candidates.append(p if p.is_absolute() else (Path.cwd() / p))
    if not p.is_absolute():
        candidates.append(skill_dir / p)
        candidates.append(cache_root / p)

    # Historical cache JSON may contain an absolute path from another checkout,
    # e.g. /.../skills/stock-infos/cache/<handle>/<id>/images/img_001.jpg.
    marker = f"{os.sep}cache{os.sep}"
    if marker in raw:
        suffix = raw.split(marker, 1)[1]
        candidates.append(cache_root / suffix)

    seen = set()
    for cand in candidates:
        try:
            cand = cand.resolve()
        except Exception:
            cand = cand.absolute()
        if cand in seen:
            continue
        seen.add(cand)
        if cand.is_file() and cand.stat().st_size > 0:
            return cand
    return None


def download_image(url: str, dest: Path, timeout: int = 25) -> Tuple[Optional[Path], Optional[str]]:
    if not is_probably_image_url(url):
        return None, "not_image_url"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest, None
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as f:
            f.write(resp.read())
        if tmp.stat().st_size <= 0:
            tmp.unlink(missing_ok=True)
            return None, "empty_download"
        tmp.replace(dest)
        return dest, None
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return None, f"download_failed: {type(exc).__name__}: {exc}"


def bbox_sort_key(obs: Any) -> Tuple[float, float]:
    try:
        bb = obs.boundingBox()
        return (-float(bb.origin.y), float(bb.origin.x))
    except Exception:
        return (0.0, 0.0)


def clean_ocr_lines(lines: Iterable[str]) -> List[str]:
    out: List[str] = []
    prev = None
    for line in lines:
        s = re.sub(r"[ \t\u3000]+", " ", (line or "")).strip()
        if not s:
            continue
        if s == prev:
            continue
        out.append(s)
        prev = s
    return out


def ocr_image(path: Path, languages: List[str], max_chars: int) -> Tuple[str, Dict[str, Any]]:
    if not load_vision():
        return "", {"status": "unavailable", "error": VISION_ERROR or "Vision unavailable"}

    assert NSURL is not None and VNRecognizeTextRequest is not None and VNImageRequestHandler is not None
    request = VNRecognizeTextRequest.alloc().init()
    # 0 = accurate, 1 = fast. Accurate is much better for Chinese screenshots.
    try:
        request.setRecognitionLevel_(0)
    except Exception:
        pass
    try:
        request.setUsesLanguageCorrection_(True)
    except Exception:
        pass
    try:
        request.setRecognitionLanguages_(languages)
    except Exception:
        pass

    url = NSURL.fileURLWithPath_(str(path))
    handler = VNImageRequestHandler.alloc().initWithURL_options_(url, {})
    try:
        ok = handler.performRequests_error_([request], None)
        if ok is False:
            return "", {"status": "failed", "error": "Vision performRequests returned false"}
    except Exception as exc:
        return "", {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    results = list(request.results() or [])
    lines: List[str] = []
    confidences: List[float] = []
    for obs in sorted(results, key=bbox_sort_key):
        try:
            candidates = obs.topCandidates_(1)
            if not candidates:
                continue
            cand = candidates[0]
            text = str(cand.string())
            lines.append(text)
            try:
                confidences.append(float(cand.confidence()))
            except Exception:
                pass
        except Exception:
            continue

    cleaned = clean_ocr_lines(lines)
    text = "\n".join(cleaned).strip()
    truncated = False
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（OCR 过长已截断）"
        truncated = True
    avg_conf = sum(confidences) / len(confidences) if confidences else None
    return text, {
        "status": "ok" if text else "empty",
        "line_count": len(cleaned),
        "avg_confidence": avg_conf,
        "truncated": truncated,
    }


def post_handle(post: Dict[str, Any]) -> str:
    for key in ("requested_username", "username", "screen_name", "handle"):
        val = post.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lstrip("@")
    author = post.get("author")
    if isinstance(author, dict):
        for key in ("screen_name", "username", "handle"):
            val = author.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().lstrip("@")
    return "unknown"


def enrich_post(post: Dict[str, Any], cache_root: Path, skill_dir: Path, languages: List[str], max_chars: int, refresh: bool) -> Dict[str, Any]:
    media_urls = post.get("media_urls") if isinstance(post.get("media_urls"), list) else []
    local_paths_raw = post.get("local_media_paths") if isinstance(post.get("local_media_paths"), list) else []
    media_count = max(len(media_urls), len(local_paths_raw), int(post.get("media_count") or 0))
    if media_count <= 0:
        return post

    # Reuse existing OCR unless refresh requested. Still normalize broken paths if possible.
    if not refresh and isinstance(post.get("ocr_media"), list) and post.get("ocr_checked_at"):
        normalized_existing: List[str] = []
        for raw in local_paths_raw:
            resolved = resolve_existing_path(raw, cache_root, skill_dir)
            normalized_existing.append(str(resolved) if resolved else str(raw))
        if normalized_existing:
            post["local_media_paths"] = normalized_existing
            post["output"] = str(cache_root)
        return post

    handle = post_handle(post)
    post_id = str(post.get("id") or "unknown")
    entries: List[Dict[str, Any]] = []
    resolved_paths: List[str] = []

    for idx in range(media_count):
        raw_path = local_paths_raw[idx] if idx < len(local_paths_raw) else None
        media_url = str(media_urls[idx]) if idx < len(media_urls) and media_urls[idx] is not None else ""
        entry: Dict[str, Any] = {"index": idx + 1}
        if media_url:
            entry["media_url"] = media_url

        path = resolve_existing_path(raw_path, cache_root, skill_dir)
        if path is None and media_url and is_probably_image_url(media_url):
            ext = extension_from_url(media_url)
            dest = cache_root / handle / post_id / "images" / f"img_{idx + 1:03d}.{ext}"
            path, dl_error = download_image(media_url, dest)
            if dl_error:
                entry["status"] = dl_error.split(":", 1)[0]
                entry["error"] = dl_error
        elif path is None and media_url:
            entry["status"] = "not_image_media"
            entry["error"] = "media url is not an image; OCR skipped"

        if path is None:
            entry.setdefault("status", "missing_local_image")
            entry.setdefault("error", "local image is unavailable and could not be downloaded")
            entries.append(entry)
            continue

        entry["source_path"] = str(path)
        resolved_paths.append(str(path))
        text, meta = ocr_image(path, languages=languages, max_chars=max_chars)
        entry.update(meta)
        if text:
            entry["text"] = text
        entries.append(entry)

    texts: List[str] = []
    for entry in entries:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        texts.append(f"[图{entry.get('index')} OCR]\n{text}")

    ok_count = sum(1 for e in entries if e.get("status") == "ok" and e.get("text"))
    if ok_count == len(entries) and ok_count > 0:
        status = "ok"
    elif ok_count > 0:
        status = "partial"
    elif any(e.get("status") == "unavailable" for e in entries):
        status = "unavailable"
    elif entries and all(e.get("status") == "not_image_media" for e in entries):
        status = "no_image_media"
    elif entries and all(e.get("status") == "empty" for e in entries):
        status = "empty"
    else:
        status = "failed"

    # Preserve order, drop duplicates. Also overwrite historical broken paths
    # with the normalized/downloaded paths so future runs do not point at an old checkout.
    seen = set()
    deduped = []
    for p in resolved_paths:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    post["local_media_paths"] = deduped
    if deduped:
        post["output"] = str(cache_root)

    post["ocr_media"] = entries
    post["ocr_text"] = "\n\n".join(texts).strip()
    post["ocr_status"] = status
    post["ocr_checked_at"] = now_iso()
    return post


def main() -> int:
    parser = argparse.ArgumentParser(description="Add OCR fields to Twitter/X post JSON containing images")
    parser.add_argument("--cache-root", required=True, help="twitter-user-posts cache root")
    parser.add_argument("--skill-dir", default=None, help="skill directory; defaults to parent of cache-root")
    parser.add_argument("--languages", default="zh-Hans,zh-Hant,en-US", help="comma-separated Vision OCR languages")
    parser.add_argument("--max-chars-per-image", type=int, default=4000)
    parser.add_argument("--refresh", action="store_true", help="rerun OCR even when ocr_media exists")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    cache_root = Path(args.cache_root).expanduser().resolve()
    skill_dir = Path(args.skill_dir).expanduser().resolve() if args.skill_dir else cache_root.parent
    languages = [x.strip() for x in args.languages.split(",") if x.strip()]

    try:
        data = json.load(sys.stdin)
    except Exception as exc:
        print(f"enrich_media_ocr.py: invalid JSON: {exc}", file=sys.stderr)
        return 2

    single = isinstance(data, dict)
    posts = [data] if single else data
    if not isinstance(posts, list):
        print("enrich_media_ocr.py: input must be a JSON object or array", file=sys.stderr)
        return 2

    out = []
    for item in posts:
        if isinstance(item, dict):
            out.append(enrich_post(item, cache_root, skill_dir, languages, args.max_chars_per_image, args.refresh))
        else:
            out.append(item)

    result = out[0] if single else out
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
