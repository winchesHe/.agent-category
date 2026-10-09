#!/usr/bin/env python3
import copy
import json
import os
import sys
import urllib.request
import urllib.error
import subprocess
import uuid
import time
from pathlib import Path
import mimetypes
from urllib.parse import urlencode

BASE_URL = os.environ.get('METERSPHERE_BASE_URL', '').rstrip('/')
AK = os.environ.get('METERSPHERE_ACCESS_KEY') or os.environ.get('METERSPHERE_ACCESS_KEY', '')
SK = os.environ.get('METERSPHERE_SECRET_KEY') or os.environ.get('METERSPHERE_SECRET_KEY', '')


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def signature():
    plain = f"{AK}|{uuid.uuid4()}|{int(time.time()*1000)}"
    p = subprocess.run([
        'openssl', 'enc', '-aes-128-cbc', '-K', SK.encode().hex(), '-iv', AK.encode().hex(), '-base64', '-A', '-nosalt'
    ], input=plain.encode(), capture_output=True, check=True)
    return p.stdout.decode().strip()


def headers(extra=None):
    if not BASE_URL or not AK or not SK:
        die('缺少 METERSPHERE_BASE_URL / METERSPHERE_ACCESS_KEY / METERSPHERE_SECRET_KEY')
    result = {'Content-Type': 'application/json', 'accessKey': AK, 'signature': signature()}
    headers_json = os.environ.get('METERSPHERE_HEADERS_JSON')
    if headers_json:
        result.update(json.loads(headers_json))
    workspace_id = os.environ.get('METERSPHERE_WORKSPACE_ID')
    if workspace_id:
        result.setdefault('WORKSPACE', workspace_id)
    project_id = os.environ.get('METERSPHERE_PROJECT_ID')
    if project_id:
        result.setdefault('PROJECT', project_id)
    if extra:
        result.update(extra)
    return result


def request_json(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    extra_headers = {}
    if isinstance(body, dict) and body.get('projectId'):
        extra_headers['PROJECT'] = body['projectId']
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers(extra_headers), method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'HTTP {e.code}: {detail}') from e


def request_functional_case_create(item):
    path = os.environ.get('METERSPHERE_FUNCTIONAL_CASE_CREATE_PATH', '/track/test/case/add')
    create_mode = os.environ.get('METERSPHERE_FUNCTIONAL_CASE_CREATE_MODE', 'multipart')
    if create_mode == 'json' or path.endswith('/save'):
        return request_json('POST', path, item)

    import tempfile

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(item, f, ensure_ascii=False)
        json_file = f.name

    try:
        request_headers = headers({'PROJECT': item['projectId']})
        curl_cmd = ['curl', '-sS', '-X', 'POST']
        for key, value in request_headers.items():
            if key.lower() == 'content-type':
                continue
            curl_cmd.extend(['-H', f'{key}: {value}'])
        curl_cmd.extend([
            '-F', f'request=@{json_file};type=application/json',
            BASE_URL + path,
        ])
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f'curl exited {result.returncode}')
        if not result.stdout:
            return {'error': 'No response', 'data': None}
        return json.loads(result.stdout)
    finally:
        os.unlink(json_file)


def normalize_functional_case(item):
    # MeterSphere v2 的 TestCase 表单接口使用 nodeId/stepModel，且 tags/customFields 是字符串列。
    node_id = item.get('nodeId') or item.get('moduleId')
    if item.get('moduleId') and not item.get('nodeId'):
        item['nodeId'] = item['moduleId']
    item.pop('moduleId', None)

    if not item.get('nodePath'):
        node_path_map = os.environ.get('METERSPHERE_NODE_PATH_MAP_JSON')
        if node_path_map and node_id:
            item['nodePath'] = json.loads(node_path_map).get(node_id)
        item.setdefault('nodePath', os.environ.get('METERSPHERE_DEFAULT_NODE_PATH', ''))
    if not item.get('nodePath'):
        raise ValueError('创建功能用例需要 nodePath；请在 payload 中传 nodePath，或设置 METERSPHERE_DEFAULT_NODE_PATH / METERSPHERE_NODE_PATH_MAP_JSON')
    if not item['nodePath'].startswith('/'):
        item['nodePath'] = '/' + item['nodePath']

    if item.get('caseEditType') and not item.get('stepModel'):
        item['stepModel'] = item['caseEditType']
    item.pop('caseEditType', None)
    item.pop('templateId', None)

    item.setdefault('stepModel', 'STEP')
    item.setdefault('status', 'Prepare')
    item.setdefault('method', 'manual')
    item.setdefault('priority', 'P1')
    item.setdefault('maintainer', os.environ.get('METERSPHERE_DEFAULT_MAINTAINER', 'Winches'))
    item.setdefault('stepDescription', '')
    item.setdefault('expectedResult', '')
    item.setdefault('remark', '')
    item.setdefault('prerequisite', '')

    if 'tags' in item and not isinstance(item['tags'], str):
        item['tags'] = json.dumps(item['tags'] or [], ensure_ascii=False)
    else:
        item.setdefault('tags', '[]')

    if 'customFields' in item and not isinstance(item['customFields'], str):
        if item['customFields']:
            item['customFields'] = json.dumps(item['customFields'], ensure_ascii=False)
        else:
            item.pop('customFields', None)

    if isinstance(item.get('steps'), list):
        steps = item['steps']
    elif isinstance(item.get('steps'), str):
        try:
            steps = json.loads(item['steps'])
        except Exception:
            steps = None
    else:
        steps = None

    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                step.setdefault('id', uuid.uuid4().hex[:8])
        item['steps'] = json.dumps(steps, ensure_ascii=False)

    if not item.get('versionId'):
        version_id = os.environ.get('METERSPHERE_DEFAULT_VERSION_ID')
        if version_id:
            item['versionId'] = version_id

    return item

def request_multipart(method, path, fields=None, files=None):
    """发送multipart/form-data请求"""
    import io
    import random
    import string
    
    if fields is None:
        fields = {}
    if files is None:
        files = {}
    
    # 生成边界字符串
    boundary = '----WebKitFormBoundary' + ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    
    # 构建multipart数据
    data_parts = []
    
    # 添加字段
    for key, value in fields.items():
        data_parts.append(f'--{boundary}')
        data_parts.append(f'Content-Disposition: form-data; name="{key}"')
        data_parts.append('')
        data_parts.append(str(value))
    
    # 添加文件（如果有）
    for key, file_info in files.items():
        filename = file_info.get('filename', 'file')
        content = file_info.get('content', b'')
        content_type = file_info.get('content_type', 'application/octet-stream')
        
        data_parts.append(f'--{boundary}')
        data_parts.append(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"')
        data_parts.append(f'Content-Type: {content_type}')
        data_parts.append('')
        data_parts.append('')  # 空行后是二进制内容
        
    data_parts.append(f'--{boundary}--')
    data_parts.append('')
    
    # 构建请求体
    body = '\r\n'.join(data_parts).encode('utf-8')
    
    # 如果是文件，需要特殊处理
    if files:
        # 对于文件上传，我们需要构建真正的multipart数据
        import tempfile
        import io as io_module
        
        # 创建临时文件来构建multipart数据
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as tmp:
            # 写入boundary
            for part in data_parts[:-2]:  # 排除最后的boundary结束标记
                tmp.write(part.encode('utf-8') + b'\r\n')
            
            # 写入文件内容
            for key, file_info in files.items():
                content = file_info.get('content', b'')
                if isinstance(content, str):
                    content = content.encode('utf-8')
                tmp.write(content)
                tmp.write(b'\r\n')
            
            # 写入结束boundary
            tmp.write(data_parts[-2].encode('utf-8') + b'\r\n')
            tmp.write(data_parts[-1].encode('utf-8'))
            tmp.flush()
            
            # 读取文件内容
            with open(tmp.name, 'rb') as f:
                body = f.read()
        
        os.unlink(tmp.name)
    
    # 设置headers
    req_headers = headers()
    req_headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    req_headers['Content-Length'] = str(len(body))
    
    req = urllib.request.Request(BASE_URL + path, data=body, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8', errors='replace'))


def create_functional_cases(payloads):
    results = []
    for item in payloads:
        item = normalize_functional_case(item)
        try:
            results.append(request_functional_case_create(item))
        except Exception as e:
            print(f"创建用例失败: {e}", file=sys.stderr)
            results.append({'error': str(e), 'data': None})
    
    return results


def create_api_definitions_and_cases(bundle):
    results = []
    for definition, case_list in zip(bundle.get('definitions', []), bundle.get('cases', [])):
        r = request_json('POST', '/api/definition/add', definition)
        created = r.get('data') or {}
        api_id = created.get('id') if isinstance(created, dict) else None
        case_results = []
        if api_id:
            for case_tpl in case_list:
                case_body = copy.deepcopy(case_tpl)
                case_body['projectId'] = definition['projectId']
                case_body['apiDefinitionId'] = api_id
                case_body['request']['moduleId'] = definition['moduleId']
                case_results.append(request_json('POST', '/api/case/add', case_body))
        results.append({'definition': r, 'cases': case_results})
    return results


def main():
    if len(sys.argv) != 3:
        die('用法: ms_batch.py functional-cases <json-file> | api-import <json-file>')
    mode, file_path = sys.argv[1], sys.argv[2]
    
    # 支持从标准输入读取（当文件路径为"-"时）
    if file_path == '-':
        payload = json.loads(sys.stdin.read())
    else:
        payload = json.loads(Path(file_path).read_text(encoding='utf-8'))
    
    if mode == 'functional-cases':
        print(json.dumps(create_functional_cases(payload), ensure_ascii=False, indent=2))
    elif mode == 'api-import':
        print(json.dumps(create_api_definitions_and_cases(payload), ensure_ascii=False, indent=2))
    else:
        die('未知模式')

if __name__ == '__main__':
    main()
