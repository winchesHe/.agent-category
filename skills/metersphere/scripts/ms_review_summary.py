#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib import request, error

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ENV_FILE = SKILL_DIR / '.env'

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

BASE_URL = os.environ.get('METERSPHERE_BASE_URL', '').rstrip('/')
ACCESS_KEY = os.environ.get('METERSPHERE_ACCESS_KEY') or os.environ.get('METERSPHERE_ACCESS_KEY', '')
SECRET_KEY = os.environ.get('METERSPHERE_SECRET_KEY') or os.environ.get('METERSPHERE_SECRET_KEY', '')


def die(msg: str):
    print(msg, file=sys.stderr)
    sys.exit(1)


def signature() -> str:
    plain = f"{ACCESS_KEY}|{uuid.uuid4()}|{int(time.time() * 1000)}"
    proc = subprocess.run([
        'openssl', 'enc', '-aes-128-cbc',
        '-K', SECRET_KEY.encode('utf-8').hex(),
        '-iv', ACCESS_KEY.encode('utf-8').hex(),
        '-base64', '-A', '-nosalt'
    ], input=plain.encode('utf-8'), capture_output=True, check=True)
    return proc.stdout.decode('utf-8').strip()


def headers():
    if not BASE_URL or not ACCESS_KEY or not SECRET_KEY:
        die('缺少 METERSPHERE_BASE_URL / METERSPHERE_ACCESS_KEY / METERSPHERE_SECRET_KEY')
    return {
        'Content-Type': 'application/json',
        'accessKey': ACCESS_KEY,
        'signature': signature(),
    }


def post_json(path: str, body: dict):
    req = request.Request(
        BASE_URL + path,
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers=headers(),
        method='POST',
    )
    with request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode('utf-8', errors='replace'))


def get_json(path: str):
    req = request.Request(BASE_URL + path, headers=headers(), method='GET')
    with request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode('utf-8', errors='replace'))


REVIEWED_STATUSES = {'Pass', 'UnPass'}


def fetch_all_functional_cases(project_id: str, keyword: str):
    current = 1
    page_size = 100
    rows = []
    while True:
        body = {'projectId': project_id}
        if keyword:
            body['name'] = keyword
        data = post_json(f'/track/test/case/list/{current}/{page_size}', body).get('data') or {}
        lst = data.get('listObject') or []
        rows.extend(lst)
        total = data.get('itemCount') or len(rows)
        if len(rows) >= total or not lst:
            break
        current += 1
    return rows


def fetch_all_reviews(project_id: str):
    data = post_json('/track/test/case/review/list/all', {'projectId': project_id}).get('data') or []
    return data


def fetch_review_cases(review_id: str):
    current = 1
    page_size = 200
    rows = []
    while True:
        data = post_json(f'/track/test/review/case/list/{current}/{page_size}', {'reviewId': review_id}).get('data') or {}
        lst = data.get('listObject') or []
        rows.extend(lst)
        total = data.get('itemCount') or len(rows)
        if len(rows) >= total or not lst:
            break
        current += 1
    return rows


def build_case_review_map(project_id: str):
    """返回 {caseId: [review_entry, ...]}。一次性遍历，避免每个 case 单独查。"""
    reviews = fetch_all_reviews(project_id)
    mapping = {}
    for r in reviews:
        review_id = r.get('id')
        review_name = r.get('name')
        review_status = r.get('status')
        for c in fetch_review_cases(review_id):
            entry = {
                'reviewId': review_id,
                'reviewName': review_name,
                'reviewStatus': review_status,
                'caseReviewStatus': c.get('reviewStatus'),
            }
            mapping.setdefault(c.get('caseId') or c.get('id'), []).append(entry)
    return mapping


def fetch_case_bug_count(case_id: str) -> int:
    data = get_json(f'/track/issues/get/case/FUNCTIONAL/{case_id}').get('data') or []
    return len(data) if isinstance(data, list) else 0


def main():
    if len(sys.argv) < 2:
        die('用法: ms_review_summary.py <projectId> [keyword]')
    project_id = sys.argv[1]
    keyword = sys.argv[2] if len(sys.argv) > 2 else ''

    cases = fetch_all_functional_cases(project_id, keyword)
    review_map = build_case_review_map(project_id)
    out = []
    for c in cases:
        case_id = c.get('id')
        review_status = c.get('reviewStatus')
        review_items = review_map.get(case_id, [])
        is_reviewed = bool(review_items)
        bug_count = fetch_case_bug_count(case_id)

        out.append({
            'caseId': case_id,
            'num': c.get('num'),
            'name': c.get('name'),
            'nodePath': c.get('nodePath'),
            'priority': c.get('priority'),
            'reviewStatus': review_status,
            'maintainer': c.get('maintainer'),
            'bugCount': bug_count,
            'caseReviewCount': len(review_items),
            'reviewCount': len(review_items),
            'reviewed': is_reviewed,
            'reviews': review_items,
        })

    print(json.dumps({
        'projectId': project_id,
        'keyword': keyword,
        'totalCases': len(out),
        'reviewedCases': sum(1 for x in out if x['reviewed']),
        'unreviewedCases': sum(1 for x in out if not x['reviewed']),
        'totalBugLinks': sum(int(x.get('bugCount') or 0) for x in out),
        'list': out,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        die(f'HTTP {e.code}: {detail}')
    except Exception as e:
        die(str(e))
