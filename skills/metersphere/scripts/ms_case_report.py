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


def case_detail(case_id: str):
    return (get_json(f'/track/test/case/get/edit/simple/{case_id}').get('data') or {})


def case_reviews(project_id: str, case_id: str):
    """v2 没有按 case 反查评审的接口；遍历项目下所有评审单的 case 列表反向匹配。"""
    reviews = post_json('/track/test/case/review/list/all', {'projectId': project_id}).get('data') or []
    out = []
    for r in reviews:
        review_id = r.get('id')
        current = 1
        page_size = 200
        while True:
            data = post_json(f'/track/test/review/case/list/{current}/{page_size}', {'reviewId': review_id}).get('data') or {}
            lst = data.get('listObject') or []
            for c in lst:
                if (c.get('caseId') or c.get('id')) == case_id:
                    out.append({
                        'reviewId': review_id,
                        'reviewName': r.get('name'),
                        'reviewStatus': r.get('status'),
                        'caseReviewStatus': c.get('reviewStatus'),
                    })
                    break
            total = data.get('itemCount') or len(lst)
            if len(lst) == 0 or current * page_size >= total:
                break
            current += 1
    return out


def case_bugs(project_id: str, case_id: str):
    data = get_json(f'/track/issues/get/case/FUNCTIONAL/{case_id}').get('data') or []
    return data if isinstance(data, list) else []


def build_summary(detail: dict, bugs: list, reviews: list):
    return {
        'caseId': detail.get('id'),
        'num': detail.get('num'),
        'name': detail.get('name'),
        'nodeId': detail.get('nodeId'),
        'nodePath': detail.get('nodePath'),
        'projectId': detail.get('projectId'),
        'versionId': detail.get('versionId'),
        'priority': detail.get('priority'),
        'status': detail.get('status'),
        'reviewStatus': detail.get('reviewStatus'),
        'maintainer': detail.get('maintainer'),
        'lastExecuteResult': detail.get('lastExecuteResult'),
        'bugCount': len(bugs),
        'caseReviewCount': len(reviews),
        'reviewed': bool(reviews),
    }


def main():
    if len(sys.argv) != 3:
        die('用法: ms_case_report.py <projectId> <caseId>')
    project_id = sys.argv[1]
    case_id = sys.argv[2]

    detail = case_detail(case_id)
    reviews = case_reviews(project_id, case_id)
    bugs = case_bugs(project_id, case_id)

    try:
        steps = json.loads(detail.get('steps') or '[]')
    except json.JSONDecodeError:
        steps = []
    tags = detail.get('tags')
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            tags = [tags] if tags else []

    result = {
        'summary': build_summary(detail, bugs, reviews),
        'detail': {
            'prerequisite': detail.get('prerequisite'),
            'remark': detail.get('remark'),
            'stepDescription': detail.get('stepDescription'),
            'expectedResult': detail.get('expectedResult'),
            'steps': steps,
            'tags': tags or [],
        },
        'bugs': [
            {
                'id': b.get('id'),
                'num': b.get('num'),
                'title': b.get('title') or b.get('name'),
                'status': b.get('status') or b.get('platformStatus'),
                'creator': b.get('creator') or b.get('createUser'),
                'createTime': b.get('createTime'),
            }
            for b in bugs
        ],
        'reviews': reviews,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        die(f'HTTP {e.code}: {detail}')
    except Exception as e:
        die(str(e))
