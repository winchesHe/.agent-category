from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .client import Client
from .config import Config
from .errors import EXIT_API, EXIT_CONFIG, CapabilityUnavailable, MeterSphereError


PATHS = {
    "organization": {"list": ("GET", "/track/workspace/list/userworkspace")},
    "project": {"list": ("POST", "/track/project/list/related")},
    "functional-module": {
        "list": ("POST", "/track/case/node/list/{projectId}"),
        "create": ("POST", "/track/case/node/add"),
        "delete": ("POST", "/track/case/node/delete"),
    },
    "functional-template": {"list": ("GET", "/track/field/template/case/{projectId}")},
    "functional-case": {
        "list": ("POST", "/track/test/case/list/{current}/{pageSize}"),
        "get": ("GET", "/track/test/case/get/edit/simple/{id}"),
        "create": ("POST", "/track/test/case/add"),
        "edit": ("POST", "/track/test/case/edit"),
        "delete": ("POST", "/track/test/case/delete/{id}"),
    },
    "functional-case-review": {"list": ("POST", "/track/test/case/reviews/case/{current}/{pageSize}")},
    "case-review": {
        "list": ("POST", "/track/test/case/review/list/{current}/{pageSize}"),
        "get": ("GET", "/track/test/case/review/get/{id}"),
    },
    "case-review-detail": {"list": ("POST", "/track/test/review/case/list/{current}/{pageSize}")},
    "case-review-module": {"list": ("POST", "/track/case/review/node/list/{projectId}")},
    "case-review-user": {"list": ("POST", "/track/test/case/review/reviewer")},
    "api-module": {"list": ("POST", "/api/definition/module/tree")},
    "api": {"list": ("POST", "/api/definition/page")},
    "api-case": {"list": ("POST", "/api/case/page")},
}

CAPABILITIES = {
    "functional-template": "功能用例模板服务",
    "api-module": "接口测试模块",
    "api": "接口定义模块",
    "api-case": "接口用例模块",
}


def parse_json_source(raw: str) -> Any:
    if raw == "-":
        return json.load(sys.stdin)
    if raw.lstrip().startswith(("{", "[")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MeterSphereError(f"参数不是有效 JSON: {exc}", EXIT_CONFIG) from exc
    candidate = Path(raw)
    try:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    except OSError:
        pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MeterSphereError(f"参数不是有效 JSON 或 JSON 文件: {exc}", EXIT_CONFIG) from exc


def unwrap(response: Any) -> Any:
    return response.get("data") if isinstance(response, dict) and "data" in response else response


def _project(config: Config, provided: str = "") -> str:
    value = provided or config.project_id
    if not value:
        raise MeterSphereError("需要 projectId，或设置 METERSPHERE_PROJECT_ID", EXIT_CONFIG)
    return value


def _page_payload(config: Config, raw: str = "") -> tuple[dict[str, Any], int, int]:
    if raw and not raw.lstrip().startswith(("{", "[")) and not Path(raw).is_file():
        body = {"name": raw}
    else:
        body = parse_json_source(raw) if raw else {}
    if not isinstance(body, dict):
        raise MeterSphereError("分页参数必须是 JSON object", EXIT_CONFIG)
    body = copy.deepcopy(body)
    current = int(body.pop("current", 1))
    page_size = int(body.pop("pageSize", 20))
    if config.project_id and not body.get("projectId"):
        body["projectId"] = config.project_id
    if "keyword" in body and "name" not in body:
        body["name"] = body.pop("keyword")
    return body, current, page_size


def _normalize_case(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(payload)
    node_id = item.get("nodeId") or item.get("moduleId")
    if item.get("moduleId") and not item.get("nodeId"):
        item["nodeId"] = item["moduleId"]
    item.pop("moduleId", None)
    if not item.get("projectId"):
        item["projectId"] = _project(config)
    if not item.get("nodePath"):
        mapping_raw = os.environ.get("METERSPHERE_NODE_PATH_MAP_JSON", "")
        mapping = json.loads(mapping_raw) if mapping_raw else {}
        item["nodePath"] = mapping.get(node_id) or os.environ.get("METERSPHERE_DEFAULT_NODE_PATH", "")
    if not item.get("nodePath"):
        raise MeterSphereError(
            "创建或编辑功能用例需要 nodePath；请传 nodePath，或配置 METERSPHERE_DEFAULT_NODE_PATH/METERSPHERE_NODE_PATH_MAP_JSON",
            EXIT_CONFIG,
        )
    if not str(item["nodePath"]).startswith("/"):
        item["nodePath"] = "/" + str(item["nodePath"])
    if item.get("caseEditType") and not item.get("stepModel"):
        item["stepModel"] = item["caseEditType"]
    item.pop("caseEditType", None)
    item.pop("templateId", None)
    item.setdefault("stepModel", "STEP")
    item.setdefault("status", "Prepare")
    item.setdefault("method", "manual")
    item.setdefault("priority", "P1")
    item.setdefault("maintainer", os.environ.get("METERSPHERE_DEFAULT_MAINTAINER", "Winches"))
    for key in ("stepDescription", "expectedResult", "remark", "prerequisite"):
        item.setdefault(key, "")
    if not item.get("versionId") and os.environ.get("METERSPHERE_DEFAULT_VERSION_ID"):
        item["versionId"] = os.environ["METERSPHERE_DEFAULT_VERSION_ID"]
    for key in ("tags", "customFields", "steps"):
        value = item.get(key)
        if isinstance(value, (list, dict)):
            if key == "steps" and isinstance(value, list):
                for step in value:
                    if isinstance(step, dict):
                        step.setdefault("id", os.urandom(4).hex())
            item[key] = json.dumps(value, ensure_ascii=False)
    item.setdefault("tags", "[]")
    return item


def _created_id(response: Any) -> str:
    data = unwrap(response)
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return str(data.get("id") or data.get("testCaseId") or "")
    return ""


def _case_get(client: Client, case_id: str) -> Any:
    return client.request("GET", f"/track/test/case/get/edit/simple/{case_id}")


def create_case(client: Client, config: Config, raw: str) -> dict[str, Any]:
    payload = parse_json_source(raw)
    if not isinstance(payload, dict):
        raise MeterSphereError("功能用例 create 需要 JSON object", EXIT_CONFIG)
    normalized = _normalize_case(config, payload)
    response = client.multipart("/track/test/case/add", normalized, project_id=normalized["projectId"])
    case_id = _created_id(response)
    readback = _case_get(client, case_id) if case_id else None
    return {"success": True, "id": case_id, "response": response, "readback": readback}


def edit_case(client: Client, config: Config, case_id: str, raw: str) -> dict[str, Any]:
    existing_response = _case_get(client, case_id)
    existing = unwrap(existing_response)
    if not isinstance(existing, dict) or not existing:
        raise MeterSphereError(f"未找到功能用例: {case_id}", EXIT_API)
    patch = parse_json_source(raw)
    if not isinstance(patch, dict):
        raise MeterSphereError("功能用例 edit 需要 JSON object", EXIT_CONFIG)
    merged = copy.deepcopy(existing)
    merged.update(patch)
    merged["id"] = case_id
    merged["latest"] = True
    normalized = _normalize_case(config, merged)
    response = client.multipart("/track/test/case/edit", normalized, project_id=normalized["projectId"])
    return {"success": True, "id": case_id, "response": response, "readback": _case_get(client, case_id)}


def delete_case(client: Client, case_id: str) -> dict[str, Any]:
    response = client.request("POST", f"/track/test/case/delete/{case_id}")
    return {"success": True, "id": case_id, "deleted": True, "response": response}


def batch_create_cases(client: Client, config: Config, payloads: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    created_ids: list[str] = []
    try:
        for item in payloads:
            if not isinstance(item, dict):
                raise MeterSphereError("batch-create 每一项都必须是 JSON object", EXIT_CONFIG)
            result = create_case(client, config, json.dumps(item, ensure_ascii=False))
            results.append(result)
            if result.get("id"):
                created_ids.append(str(result["id"]))
    except Exception as exc:
        rollback_errors = []
        for case_id in reversed(created_ids):
            try:
                delete_case(client, case_id)
            except Exception as rollback_exc:
                rollback_errors.append(f"{case_id}: {rollback_exc}")
        message = f"batch-create 失败，已回滚 {len(created_ids)} 条: {exc}"
        if rollback_errors:
            message += f"；回滚失败: {'; '.join(rollback_errors)}"
        code = exc.code if isinstance(exc, MeterSphereError) else EXIT_API
        raise MeterSphereError(message, code) from exc
    return {"success": True, "results": results}


def _walk_modules(nodes: list[dict[str, Any]]):
    for node in nodes:
        yield node
        yield from _walk_modules(node.get("children") or [])


def _module_list(client: Client, project_id: str) -> Any:
    return client.request("POST", f"/track/case/node/list/{project_id}", {}, project_id=project_id)


def fetch_all_pages(
    client: Client,
    path_template: str,
    body: dict[str, Any],
    *,
    project_id: str,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    current = 1
    rows: list[dict[str, Any]] = []
    while True:
        path = path_template.replace("{current}", str(current)).replace("{pageSize}", str(page_size))
        data = unwrap(client.request("POST", path, body, project_id=project_id)) or {}
        page = data.get("listObject") or []
        rows.extend(page)
        total = int(data.get("itemCount") or len(rows))
        if not page or len(rows) >= total:
            return rows
        current += 1


def search_cases(client: Client, config: Config, keyword: str, project_id: str = "") -> dict[str, Any]:
    project_id = _project(config, project_id)
    modules_response = _module_list(client, project_id)
    modules = unwrap(modules_response) or []
    hits = [node for node in _walk_modules(modules) if keyword.lower() in str(node.get("name") or "").lower()]
    if hits:
        return {"success": True, "matchType": "module", "keyword": keyword, "data": hits}
    rows = fetch_all_pages(
        client, "/track/test/case/list/{current}/{pageSize}",
        {"projectId": project_id, "name": keyword}, project_id=project_id,
    )
    return {"success": True, "matchType": "case", "keyword": keyword, "data": {"listObject": rows, "itemCount": len(rows)}}


def cases_by_module(client: Client, config: Config, keyword: str, project_id: str = "") -> dict[str, Any]:
    project_id = _project(config, project_id)
    modules = unwrap(_module_list(client, project_id)) or []
    hits = [node for node in _walk_modules(modules) if keyword.lower() in str(node.get("name") or "").lower()]
    if not hits:
        raise MeterSphereError(f"模块树里没有名称包含 {keyword!r} 的节点", EXIT_API)
    node_ids: list[str] = []
    for hit in hits:
        node_ids.extend(str(node.get("id")) for node in _walk_modules([hit]) if node.get("id"))
    rows = fetch_all_pages(
        client, "/track/test/case/list/{current}/{pageSize}",
        {"projectId": project_id, "nodeIds": sorted(set(node_ids))}, project_id=project_id,
    )
    return {"success": True, "matchType": "module-cases", "modules": hits, "data": {"listObject": rows, "itemCount": len(rows)}}


def _run_json_helper(command: list[str]) -> Any:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode:
        raise MeterSphereError(completed.stderr.strip() or f"辅助命令失败: {' '.join(command)}", EXIT_API)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MeterSphereError(f"辅助命令未返回有效 JSON: {completed.stdout[:300]}", EXIT_API) from exc


def reviewed_summary(client: Client, config: Config, project_id: str, keyword: str = "") -> dict[str, Any]:
    project_id = _project(config, project_id)
    case_body: dict[str, Any] = {"projectId": project_id}
    if keyword:
        case_body["name"] = keyword
    cases = fetch_all_pages(
        client, "/track/test/case/list/{current}/{pageSize}", case_body, project_id=project_id,
    )
    reviews = unwrap(client.request("POST", "/track/test/case/review/list/all", {"projectId": project_id}, project_id=project_id)) or []
    review_map: dict[str, list[dict[str, Any]]] = {}
    for review in reviews:
        review_id = review.get("id")
        review_cases = fetch_all_pages(
            client, "/track/test/review/case/list/{current}/{pageSize}",
            {"reviewId": review_id}, project_id=project_id,
        )
        for case in review_cases:
            case_id = case.get("caseId") or case.get("id")
            review_map.setdefault(case_id, []).append({
                "reviewId": review_id,
                "reviewName": review.get("name"),
                "reviewStatus": review.get("status"),
                "caseReviewStatus": case.get("reviewStatus"),
            })
    rows = []
    for case in cases:
        case_id = case.get("id")
        items = review_map.get(case_id, [])
        rows.append({
            "caseId": case_id,
            "num": case.get("num"),
            "name": case.get("name"),
            "reviewStatus": case.get("reviewStatus"),
            "reviewCount": len(items),
            "reviewed": bool(items),
            "reviews": items,
        })
    return {
        "success": True,
        "projectId": project_id,
        "totalCases": len(rows),
        "reviewedCases": sum(1 for row in rows if row["reviewed"]),
        "unreviewedCases": sum(1 for row in rows if not row["reviewed"]),
        "list": rows,
    }


def case_review_records(client: Client, config: Config, project_id: str, case_id: str) -> dict[str, Any]:
    project_id = _project(config, project_id)
    reviews = unwrap(client.request("POST", "/track/test/case/review/list/all", {"projectId": project_id}, project_id=project_id)) or []
    matches: list[dict[str, Any]] = []
    for review in reviews:
        review_id = review.get("id")
        review_cases = fetch_all_pages(
            client, "/track/test/review/case/list/{current}/{pageSize}",
            {"reviewId": review_id}, project_id=project_id,
        )
        for case in review_cases:
            if (case.get("caseId") or case.get("id")) == case_id:
                matches.append({
                    "reviewId": review_id,
                    "reviewName": review.get("name"),
                    "reviewStatus": review.get("status"),
                    "caseReviewStatus": case.get("reviewStatus"),
                })
    return {"success": True, "projectId": project_id, "caseId": case_id, "reviewed": bool(matches), "data": matches}


def doctor(client: Client, config: Config) -> dict[str, Any]:
    projects = client.request("POST", "/track/project/list/related", {})
    capabilities = {"track": True, "functionalTemplate": False, "apiTesting": False}
    try:
        client.request("GET", "/track/v3/api-docs")
    except MeterSphereError:
        capabilities["track"] = False
    if config.project_id:
        try:
            client.request("GET", f"/track/field/template/case/{config.project_id}", capability="功能用例模板服务")
            capabilities["functionalTemplate"] = True
        except CapabilityUnavailable:
            pass
    try:
        client.request("GET", "/api/v3/api-docs", capability="接口测试模块")
        capabilities["apiTesting"] = True
    except CapabilityUnavailable:
        pass
    return {
        "success": True,
        "config": {
            "envFile": str(config.env_file) if config.env_file else None,
            "baseUrlConfigured": bool(config.base_url),
            "accessKeyConfigured": bool(config.access_key),
            "secretKeyConfigured": bool(config.secret_key),
            "projectIdConfigured": bool(config.project_id),
        },
        "connectivity": {"projectsReadable": projects is not None},
        "capabilities": capabilities,
    }


def run(config: Config, client: Client, command: str, args: list[str]) -> Any:
    if command == "doctor":
        return doctor(client, config)
    if command == "raw":
        if len(args) < 2:
            raise MeterSphereError("raw 需要 METHOD PATH [JSON]", EXIT_CONFIG)
        return client.request(args[0], args[1], parse_json_source(args[2]) if len(args) > 2 else None)
    if command == "reviewed-summary":
        return reviewed_summary(client, config, args[0] if args else "", args[1] if len(args) > 1 else "")
    if command == "case-report" or command == "case-report-md":
        if len(args) < 2:
            raise MeterSphereError(f"{command} 需要 projectId caseId", EXIT_CONFIG)
        helper = config.skill_root / "scripts" / ("ms_case_report_md.py" if command.endswith("-md") else "ms_case_report.py")
        completed = subprocess.run([sys.executable, str(helper), args[0], args[1]], capture_output=True, text=True)
        if completed.returncode:
            raise MeterSphereError(completed.stderr.strip() or f"{command} 失败", EXIT_API)
        return completed.stdout if command.endswith("-md") else json.loads(completed.stdout)
    if command not in PATHS:
        raise MeterSphereError(f"不支持的资源: {command}", EXIT_CONFIG)
    if not args:
        raise MeterSphereError("缺少 action", EXIT_CONFIG)
    action, tail = args[0], args[1:]

    if command == "functional-case" and action == "search":
        if not tail:
            raise MeterSphereError("functional-case search 需要关键字", EXIT_CONFIG)
        return search_cases(client, config, tail[0], tail[1] if len(tail) > 1 else "")
    if command == "functional-case" and action == "by-module":
        if not tail:
            raise MeterSphereError("functional-case by-module 需要模块名关键字", EXIT_CONFIG)
        return cases_by_module(client, config, tail[0], tail[1] if len(tail) > 1 else "")
    if command == "functional-case" and action == "create":
        return create_case(client, config, tail[0] if tail else "")
    if command == "functional-case" and action == "edit":
        if len(tail) < 2:
            raise MeterSphereError("functional-case edit 需要 caseId 和 JSON/文件", EXIT_CONFIG)
        return edit_case(client, config, tail[0], tail[1])
    if command == "functional-case" and action == "delete":
        if not tail:
            raise MeterSphereError("functional-case delete 需要 caseId", EXIT_CONFIG)
        return delete_case(client, tail[0])
    if command == "functional-case" and action == "batch-create":
        payloads = parse_json_source(tail[0] if tail else "")
        if not isinstance(payloads, list):
            raise MeterSphereError("batch-create 文件必须是 JSON array", EXIT_CONFIG)
        return batch_create_cases(client, config, payloads)
    if command == "functional-case-review" and action == "list":
        raw = parse_json_source(tail[0] if tail else "")
        if not isinstance(raw, dict) or not raw.get("caseId"):
            raise MeterSphereError("functional-case-review list 需要包含 caseId 的 JSON object", EXIT_CONFIG)
        return case_review_records(client, config, str(raw.get("projectId") or ""), str(raw["caseId"]))
    if command == "functional-case" and action in ("generate", "generate-create"):
        if len(tail) < 4:
            raise MeterSphereError(f"functional-case {action} 需要 projectId moduleId templateId requirement-file", EXIT_CONFIG)
        generator = config.skill_root / "scripts" / "ms_generate.py"
        generated = _run_json_helper([sys.executable, str(generator), "functional-cases", *tail[:4]])
        if action == "generate":
            return generated
        if not isinstance(generated, list):
            raise MeterSphereError("功能用例生成结果不是 JSON array", EXIT_API)
        return batch_create_cases(client, config, generated)
    if command == "functional-module" and action == "create":
        payload = parse_json_source(tail[0] if tail else "")
        if not isinstance(payload, dict):
            raise MeterSphereError("functional-module create 需要 JSON object", EXIT_CONFIG)
        project_id = _project(config, str(payload.get("projectId") or ""))
        payload["projectId"] = project_id
        response = client.request("POST", "/track/case/node/add", payload, project_id=project_id)
        return {"success": True, "id": _created_id(response), "response": response, "readback": _module_list(client, project_id)}
    if command == "functional-module" and action == "delete":
        ids = parse_json_source(tail[0] if tail else "")
        if isinstance(ids, str):
            ids = [ids]
        if not isinstance(ids, list) or not ids:
            raise MeterSphereError("functional-module delete 需要模块 ID JSON array", EXIT_CONFIG)
        response = client.request("POST", "/track/case/node/delete", ids, project_id=config.project_id)
        return {"success": True, "deleted": ids, "response": response}
    if command == "api" and action in ("import-generate", "batch-create", "import-create"):
        try:
            client.request("GET", "/api/v3/api-docs", capability="接口测试模块")
        except CapabilityUnavailable:
            raise
        generator = config.skill_root / "scripts" / "ms_generate.py"
        batch = config.skill_root / "scripts" / "ms_batch.py"
        if action == "import-generate":
            if len(tail) < 3:
                raise MeterSphereError("api import-generate 需要 projectId moduleId openapi-source", EXIT_CONFIG)
            return _run_json_helper([sys.executable, str(generator), "api-import", *tail[:3]])
        if action == "batch-create":
            if not tail:
                raise MeterSphereError("api batch-create 需要 JSON 文件", EXIT_CONFIG)
            return _run_json_helper([sys.executable, str(batch), "api-import", tail[0]])
        if len(tail) < 3:
            raise MeterSphereError("api import-create 需要 projectId moduleId openapi-source", EXIT_CONFIG)
        generated = _run_json_helper([sys.executable, str(generator), "api-import", *tail[:3]])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(generated, handle, ensure_ascii=False)
            generated_path = handle.name
        try:
            return _run_json_helper([sys.executable, str(batch), "api-import", generated_path])
        finally:
            Path(generated_path).unlink(missing_ok=True)

    mapping = PATHS[command].get(action)
    if not mapping:
        raise MeterSphereError(f"不支持的 action: {command} {action}", EXIT_CONFIG)
    method, path = mapping
    capability = CAPABILITIES.get(command, "")
    if action == "get":
        if not tail:
            raise MeterSphereError(f"{command} get 需要 id", EXIT_CONFIG)
        return client.request(method, path.replace("{id}", tail[0]), capability=capability)
    if command in ("functional-module", "case-review-module", "functional-template"):
        project_id = _project(config, tail[0] if tail else "")
        body = {} if method == "POST" else None
        return client.request(method, path.replace("{projectId}", project_id), body, project_id=project_id, capability=capability)
    if command == "case-review-user":
        if not tail:
            raise MeterSphereError("case-review-user list 需要 reviewId", EXIT_CONFIG)
        project_id = config.project_id
        return client.request(method, path, {"id": tail[0], "projectId": project_id}, project_id=project_id)
    if command == "organization":
        return client.request(method, path)
    if command == "project":
        return client.request(method, path, {})
    body, current, page_size = _page_payload(config, tail[0] if tail else "")
    if command in ("api", "api-case") and "protocols" not in body:
        body["protocols"] = json.loads(config.protocols_json)
    path = path.replace("{current}", str(current)).replace("{pageSize}", str(page_size))
    return client.request(method, path, body, project_id=str(body.get("projectId") or ""), capability=capability)
