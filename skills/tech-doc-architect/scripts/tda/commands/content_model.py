"""校验平台无关的技术文档内容模型。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tda.errors import EXIT_INPUT, EXIT_OK, EXIT_VALIDATION, error_payload
from tda.formatter import add_format_argument, output


VALID_MODES = {"new", "refactor", "update", "review"}
VALID_STATUSES = {"verified", "inferred", "assumption", "conflict"}
VALID_OUTPUTS = {"feishu", "obsidian", "markdown"}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any, *, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_nonempty_string(item) for item in value)
    )


def validate_model(payload: Any) -> list[str]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["根节点必须是 JSON object"]

    document = payload.get("document")
    if not isinstance(document, dict):
        return ["缺少 document object"]

    for key in ("title", "one_sentence"):
        if not _nonempty_string(document.get(key)):
            errors.append(f"document.{key} 必须是非空字符串")

    mode = document.get("mode")
    if mode not in VALID_MODES:
        errors.append(
            "document.mode 必须是 " + ", ".join(sorted(VALID_MODES)) + " 之一"
        )

    for key in ("audience", "reader_questions"):
        if not _string_list(document.get(key), allow_empty=False):
            errors.append(f"document.{key} 必须是非空字符串数组")

    scope = document.get("scope")
    if not isinstance(scope, dict):
        errors.append("document.scope 必须是 object")
    else:
        if not _string_list(scope.get("in"), allow_empty=False):
            errors.append("document.scope.in 必须是非空字符串数组")
        if not _string_list(scope.get("out"), allow_empty=True):
            errors.append("document.scope.out 必须是字符串数组")

    evidence = document.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("document.evidence 必须至少包含一条关键事实")
    else:
        for index, item in enumerate(evidence):
            path = f"document.evidence[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{path} 必须是 object")
                continue
            if not _nonempty_string(item.get("claim")):
                errors.append(f"{path}.claim 必须是非空字符串")
            status = item.get("status")
            if status not in VALID_STATUSES:
                errors.append(
                    f"{path}.status 必须是 "
                    + ", ".join(sorted(VALID_STATUSES))
                    + " 之一"
                )
            sources = item.get("sources")
            allow_empty_sources = status in {"assumption", "conflict"}
            if not _string_list(sources, allow_empty=allow_empty_sources):
                errors.append(f"{path}.sources 与事实状态不匹配")
            if not _string_list(item.get("impacts"), allow_empty=False):
                errors.append(f"{path}.impacts 必须是非空字符串数组")

    vocabulary = document.get("vocabulary")
    if not isinstance(vocabulary, list):
        errors.append("document.vocabulary 必须是数组")
    else:
        terms: list[str] = []
        for index, item in enumerate(vocabulary):
            path = f"document.vocabulary[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{path} 必须是 object")
                continue
            if not _nonempty_string(item.get("term")):
                errors.append(f"{path}.term 必须是非空字符串")
            else:
                terms.append(item["term"].strip())
            if not _nonempty_string(item.get("definition")):
                errors.append(f"{path}.definition 必须是非空字符串")
        if len(terms) != len(set(terms)):
            errors.append("document.vocabulary.term 不得重复")

    overview = document.get("overview")
    if not isinstance(overview, dict):
        errors.append("document.overview 必须是 object")
    else:
        for key in ("context", "internal_model"):
            if not _nonempty_string(overview.get(key)):
                errors.append(f"document.overview.{key} 必须是非空字符串")
        if not _string_list(overview.get("invariants"), allow_empty=False):
            errors.append("document.overview.invariants 必须是非空字符串数组")
        deployment = overview.get("deployment_boundary", "")
        if not isinstance(deployment, str):
            errors.append("document.overview.deployment_boundary 必须是字符串")

    topics = document.get("topics")
    if not isinstance(topics, list) or not topics:
        errors.append("document.topics 必须至少包含一个专题")
    else:
        questions: list[str] = []
        list_fields = (
            "concepts",
            "normal_path",
            "failures",
            "recovery",
            "verification",
            "code_entries",
        )
        for index, item in enumerate(topics):
            path = f"document.topics[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{path} 必须是 object")
                continue
            for key in ("question", "answer"):
                if not _nonempty_string(item.get(key)):
                    errors.append(f"{path}.{key} 必须是非空字符串")
            if _nonempty_string(item.get("question")):
                questions.append(item["question"].strip())

            diagram = item.get("diagram")
            if diagram is not None:
                if not isinstance(diagram, dict):
                    errors.append(f"{path}.diagram 必须是 object 或 null")
                else:
                    for key in ("question", "type"):
                        if not _nonempty_string(diagram.get(key)):
                            errors.append(f"{path}.diagram.{key} 必须是非空字符串")

            for key in list_fields:
                allow_empty = key not in {"normal_path", "verification"}
                if not _string_list(item.get(key), allow_empty=allow_empty):
                    errors.append(f"{path}.{key} 必须是字符串数组")

        if len(questions) != len(set(questions)):
            errors.append("document.topics.question 不得重复")

    outputs = document.get("outputs")
    if not _string_list(outputs, allow_empty=False):
        errors.append("document.outputs 必须是非空字符串数组")
    else:
        unknown = sorted(set(outputs) - VALID_OUTPUTS)
        if unknown:
            errors.append("document.outputs 包含未知载体: " + ", ".join(unknown))

    return errors


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "validate-content-model",
        help="校验 document-model.json",
    )
    parser.add_argument("path", type=Path)
    add_format_argument(parser)
    parser.set_defaults(_handler=run)


def run(args: argparse.Namespace) -> int:
    target = args.path.resolve()
    if not target.is_file():
        payload = error_payload(
            "validate-content-model",
            str(target),
            f"内容模型不存在: {target}",
        )
        output(payload, args.format)
        return EXIT_INPUT

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = error_payload(
            "validate-content-model",
            str(target),
            f"无法读取内容模型: {exc}",
        )
        output(result, args.format)
        return EXIT_INPUT

    errors = validate_model(payload)
    result = {
        "ok": not errors,
        "command": "validate-content-model",
        "target": str(target),
        "message": (
            "内容模型校验通过"
            if not errors
            else f"内容模型校验失败，共 {len(errors)} 项"
        ),
        "errors": errors,
    }
    output(result, args.format)
    return EXIT_OK if not errors else EXIT_VALIDATION
