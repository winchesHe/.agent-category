#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a Grooming Ops Review evidence pack into Markdown or Lark DocxXML."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any


REQUIRED_SECTIONS = [
    "growth",
    "retention",
    "onboarding",
    "product_usage",
    "customer_feedback",
    "bug_tickets",
    "cs_related",
    "system_loading",
]

SECTION_TITLES = {
    "growth": "Growth / 增长",
    "retention": "Retention / 留存",
    "onboarding": "Onboarding / 激活",
    "product_usage": "Product Usage / 产品使用",
    "customer_feedback": "Customer Feedback & FR",
    "bug_tickets": "Bug Tickets / 缺陷工单",
    "cs_related": "CS Related / 客服相关",
    "system_loading": "System Loading / 系统体验",
}

SECTION_DESCRIPTIONS = {
    "Overall Summary / 总览": "汇总本期最重要的业务变化、风险与需要团队决策的事项，帮助会议快速聚焦。",
    "Growth / 增长": "观察新注册、新订阅及转化变化，判断获客与新增增长是否健康。",
    "Retention / 留存": "观察存量客户留存与流失情况，识别主要流失场景及可干预原因。",
    "Onboarding / 激活": "观察新注册或新订阅商家从初始设置到首次获得业务价值的效率，定位激活过程中的阻塞环节。",
    "Product Usage / 产品使用": "观察核心功能使用量与覆盖率变化，判断商家是否持续采用关键工作流。",
    "Customer Feedback & FR": "汇总本期用户反馈与功能诉求，识别高频问题、重复需求与优先关注的产品机会。",
    "Bug Tickets / 缺陷工单": "跟踪本期缺陷数量、严重程度与处理状态，识别需要优先解决的质量风险。",
    "CS Related / 客服相关": "观察客服工单量、活跃队列与重点问题分布，判断客户支持压力和反馈闭环效率。",
    "System Loading / 系统体验": "观察关键服务错误率、页面加载与交互性能，识别影响用户体验的系统异常。",
    "Meeting Notes / Open Questions / 会议讨论与待开放问题": "将本期异常、影响和建议动作转化为会议讨论、决策与后续责任人。",
    "Data Source & Traceability / 数据源与可追溯性": "说明本期结论的数据来源、查询口径、拉取时间与责任人，确保结果可追溯。",
}

ALLOWED_CONFIDENCE = {"verified", "derived", "manual", "visual_only", "missing"}
ALLOWED_PERIOD_GRANULARITY = {"monthly", "biweekly", "weekly", "quarterly", "custom"}
ALLOWED_CUSTOMER_FEEDBACK_SOURCE_MODES = {"four_source", "jira_only"}
CUSTOMER_EXAMPLE_SECTIONS = {"customer_feedback", "bug_tickets"}
ALLOWED_CUSTOMER_EXAMPLE_REPRESENTATIONS = {
    "direct_anonymized",
    "anonymized_paraphrase",
}
CUSTOMER_EXAMPLE_MAX_LENGTH = 280
HTTP_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
REQUIRED_CUSTOMER_FEEDBACK_SOURCES = {
    "community_fr": "Community FR",
    "quick_win_canny": "Quick-win Canny",
    "intercom_feedback": "Intercom feedback",
    "jira_grooming_cs": "Jira Grooming CS",
}

ONBOARDING_PRIMARY_METRICS = {
    "Days to first value": re.compile(r"days?\s+to\s+first\s+value|first[-\s]?value", re.IGNORECASE),
    "Go-live rate": re.compile(r"go[-\s]?live\s+rate", re.IGNORECASE),
    "Key feature first-use rate": re.compile(
        r"first[-\s]?use\s+rate|首次使用率",
        re.IGNORECASE,
    ),
}

MONTHLY_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
MONEY_METRIC_RE = re.compile(
    r"(\$|usd|sales|revenue|net\s*sales|gmv|arr|mrr|金额|收入|销售额)",
    re.IGNORECASE,
)
SENSITIVE_CHURN_REASON_RE = re.compile(
    r"(passed\s+away|died|death|deceased|cancer|illness|hospital|pregnan|family\s+emergency|personal\s+tragedy|"
    r"去世|死亡|病逝|癌|住院|怀孕|家庭变故|亲属)",
    re.IGNORECASE,
)

SECRET_PATTERNS = [
    re.compile(r"password\s*[:=]", re.IGNORECASE),
    re.compile(r"\bpsw\s*[:=]", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"\bcookie\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(token|api[_-]?key|secret)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\bconversation[_ -]?id\b", re.IGNORECASE),
    re.compile(r"\b(raw\s+feedback|quote)\b", re.IGNORECASE),
]

PRE_GENERATION_CONFIRMATION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"是否接受",
        r"是否需要",
        r"要不要补",
        r"自然月\s*exact",
        r"正式版需",
        r"发布前需要",
        r"仍缺",
        r"仍未",
        r"owner\s*暴露",
        r"owner\s*导出",
        r"owner\s*确认",
        r"底层\s*sheet",
        r"crosstab",
        r"PNG\s*视觉兜底",
        r"fallback\s*是否",
        r"source\s+of\s+truth",
        r"official\s+actual",
        r"人工收集.*待",
        r"样本范围.*确认",
        r"分层口径.*确认",
        r"permission\s+denied",
        r"权限不足",
        r"permission\s+denied.*owner",
    ]
]

FORBIDDEN_OUTPUT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"reason\s*type.*结构化质量",
        r"结构化\s*reason\s*type",
        r"空/未分类.*占比",
        r"大部分\s*reason\s*为空",
        r"reason.*未捕获",
        r"classification\s+top\s*:\s*unknown",
        r"\b[a-z0-9_]+_missing\b",
        r"\bgap_summary\b",
        r"\bnps[_ -](official[_ -])?(source[_ -]search|gap[_ -]search|permission)",
        r"(permission\s+denied|权限不足).*(nps|source|relation)",
    ]
]

CHURN_REASON_IDENTITY_KEYS = {
    "email",
    "account_email",
    "customer",
    "customer_name",
    "company",
    "company_name",
    "company_id",
    "intercom",
    "intercom_url",
}

SUMMARY_TEXT_COLORS = {"red", "orange", "yellow", "green", "blue", "purple", "gray"}


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON: {path}: {exc}") from exc


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def x(value: Any) -> str:
    return escape(text(value), quote=True)


def has_secret(value: Any) -> bool:
    serialized = json.dumps(value, ensure_ascii=False)
    return any(pattern.search(serialized) for pattern in SECRET_PATTERNS)


def contains_pre_generation_confirmation(value: Any) -> bool:
    serialized = json.dumps(value, ensure_ascii=False)
    return any(pattern.search(serialized) for pattern in PRE_GENERATION_CONFIRMATION_PATTERNS)


def contains_forbidden_output(value: Any) -> bool:
    serialized = json.dumps(value, ensure_ascii=False)
    return any(pattern.search(serialized) for pattern in FORBIDDEN_OUTPUT_PATTERNS)


def parse_signal_count(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    normalized = text(value).replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", normalized):
        return None
    return float(normalized)


def same_signal_count(left: float, right: float) -> bool:
    return abs(left - right) < 0.000001


def format_signal_count(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def contains_cjk(value: Any) -> bool:
    return bool(CJK_RE.search(json.dumps(value, ensure_ascii=False)))


def classify_feedback_source(source_name: str) -> str:
    normalized = source_name.lower().replace("_", " ").replace("-", " ")
    if "community" in normalized:
        return "community_fr"
    if "quick" in normalized or "canny" in normalized:
        return "quick_win_canny"
    if "intercom" in normalized:
        return "intercom_feedback"
    if "jira" in normalized:
        return "jira_grooming_cs"
    return ""


def trace_text(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    return " ".join(
        text(item.get(field))
        for field in ["source_id", "source_type", "title", "source_url", "query_or_filter", "owner"]
    )


def is_truthy_bool(value: Any) -> bool:
    return value is True or text(value).strip().lower() in {"true", "yes", "1"}


def validate_pack(pack: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    report = pack.get("report")
    report_granularity = ""
    if not isinstance(report, dict):
        errors.append("missing report object")
    else:
        for field in ["title", "period", "target_business"]:
            if not text(report.get(field)).strip():
                errors.append(f"report.{field} is required")
        language = text(report.get("language")).strip()
        if language != "zh-CN":
            errors.append("report.language must be zh-CN")
        report_granularity = text(report.get("period_granularity")).strip().lower()
        if not report_granularity:
            errors.append("report.period_granularity is required")
        elif report_granularity not in ALLOWED_PERIOD_GRANULARITY:
            errors.append(
                f"report.period_granularity has unsupported value '{report_granularity}'"
            )

    sections = pack.get("sections")
    if not isinstance(sections, dict):
        errors.append("missing sections object")
        sections = {}

    narrative_payload = {
        "overall_summary": pack.get("overall_summary"),
        "sections": sections,
        "meeting_notes": pack.get("meeting_notes"),
        "open_questions": pack.get("open_questions"),
    }
    if sections and not contains_cjk(narrative_payload):
        errors.append("business narrative must be written in Chinese")

    for section_key in REQUIRED_SECTIONS:
        section = sections.get(section_key)
        if not isinstance(section, dict):
            errors.append(f"sections.{section_key} is required")
            continue
        for field in ["highlights", "metrics", "visuals", "risks", "source_ids"]:
            if field not in section:
                errors.append(f"sections.{section_key}.{field} is required")
        if "visuals" in section and not isinstance(section.get("visuals"), list):
            errors.append(f"sections.{section_key}.visuals must be a list when present")
        if "insights" in section and not isinstance(section.get("insights"), list):
            errors.append(f"sections.{section_key}.insights must be a list when present")
        if section_key == "retention" and "churn_reason_details" in section:
            if not isinstance(section.get("churn_reason_details"), list):
                errors.append("sections.retention.churn_reason_details must be a list when present")
        section_narrative = {
            "summary": section.get("summary"),
            "insights": section.get("insights"),
            "highlights": section.get("highlights"),
            "risks": section.get("risks"),
        }
        if not contains_cjk(section_narrative):
            errors.append(f"sections.{section_key} business narrative must be written in Chinese")

    traceability = pack.get("traceability")
    if not isinstance(traceability, list):
        errors.append("traceability must be a list")
        traceability = []

    source_ids = {
        text(item.get("source_id"))
        for item in traceability
        if isinstance(item, dict) and text(item.get("source_id"))
    }
    source_by_id = {
        text(item.get("source_id")): item
        for item in traceability
        if isinstance(item, dict) and text(item.get("source_id"))
    }
    for index, item in enumerate(traceability, start=1):
        if not isinstance(item, dict):
            continue
        source_id = text(item.get("source_id"))
        source_type = text(item.get("source_type"))
        serialized = json.dumps(item, ensure_ascii=False)
        if (
            source_id.endswith("_missing")
            or source_type == "missing_source"
            or source_type == "gap_summary"
            or "source search" in serialized.lower()
            or re.search(r"(permission\s+denied|权限不足).*(nps|source|relation)", serialized, re.IGNORECASE)
        ):
            errors.append(
                f"traceability[{index}] looks like a superseded missing/gap/probe source; keep it in internal debug evidence, not final traceability"
            )

    for section_key, section in sections.items():
        if not isinstance(section, dict):
            continue
        section_source_ids = section.get("source_ids") or []
        if not isinstance(section_source_ids, list):
            errors.append(f"sections.{section_key}.source_ids must be a list")
            section_source_ids = []
        elif not section_source_ids:
            errors.append(f"sections.{section_key}.source_ids must include at least one source_id")
        for source_id in section_source_ids:
            source_id_text = text(source_id)
            if source_id_text and source_id_text not in source_ids:
                errors.append(
                    f"section source_id '{source_id_text}' in section '{section_key}' is not in traceability"
                )

        for field in ["highlights", "risks"]:
            for index, item in enumerate(section.get(field, []) or [], start=1):
                if contains_pre_generation_confirmation(item):
                    errors.append(
                        f"sections.{section_key}.{field}[{index}] looks like a pre-generation data confirmation; move it to pre_generation_confirmations"
                    )
                if contains_forbidden_output(item):
                    errors.append(
                        f"sections.{section_key}.{field}[{index}] uses deprecated churn reason quality wording; use direct sanitized churn_reason_details instead"
                    )

        for index, insight in enumerate(section.get("insights", []) or [], start=1):
            if not isinstance(insight, dict):
                errors.append(f"sections.{section_key}.insights[{index}] must be an object")
                continue
            if contains_pre_generation_confirmation(insight):
                errors.append(
                    f"sections.{section_key}.insights[{index}] looks like a pre-generation data confirmation; move it to pre_generation_confirmations"
                )
            if contains_forbidden_output(insight):
                    errors.append(
                        f"sections.{section_key}.insights[{index}] uses deprecated churn reason quality wording; use direct sanitized churn_reason_details instead"
                    )
            if section_key in CUSTOMER_EXAMPLE_SECTIONS:
                examples = insight.get("customer_examples")
                if not isinstance(examples, list) or not examples:
                    errors.append(
                        f"sections.{section_key}.insights[{index}].customer_examples must be a non-empty list"
                    )
                    continue
                for example_index, example in enumerate(examples, start=1):
                    path = (
                        f"sections.{section_key}.insights[{index}]"
                        f".customer_examples[{example_index}]"
                    )
                    if not isinstance(example, dict):
                        errors.append(f"{path} must be an object")
                        continue
                    example_text = text(example.get("text")).strip()
                    if not example_text:
                        errors.append(f"{path}.text is required")
                    elif len(example_text) > CUSTOMER_EXAMPLE_MAX_LENGTH:
                        errors.append(
                            f"{path}.text must be at most {CUSTOMER_EXAMPLE_MAX_LENGTH} characters"
                        )
                    representation = text(example.get("representation")).strip()
                    if representation not in ALLOWED_CUSTOMER_EXAMPLE_REPRESENTATIONS:
                        errors.append(
                            f"{path}.representation must be one of: "
                            + ", ".join(sorted(ALLOWED_CUSTOMER_EXAMPLE_REPRESENTATIONS))
                        )
                    sources = example.get("sources")
                    if not isinstance(sources, list) or not sources:
                        errors.append(f"{path}.sources must be a non-empty list")
                        continue
                    for source_index, source in enumerate(sources, start=1):
                        source_path = f"{path}.sources[{source_index}]"
                        if not isinstance(source, dict):
                            errors.append(f"{source_path} must be an object")
                            continue
                        if not text(source.get("label")).strip():
                            errors.append(f"{source_path}.label is required")
                        source_url = text(source.get("url")).strip()
                        if not source_url:
                            errors.append(f"{source_path}.url is required")
                        elif not HTTP_URL_RE.match(source_url):
                            errors.append(f"{source_path}.url must be an http(s) link")
        if section_key == "customer_feedback":
            source_mode = text(section.get("source_mode")).strip().lower()
            if source_mode not in ALLOWED_CUSTOMER_FEEDBACK_SOURCE_MODES:
                errors.append(
                    "sections.customer_feedback.source_mode must be one of: four_source, jira_only"
                )
            if not is_truthy_bool(section.get("excludes_bug_only")):
                errors.append("sections.customer_feedback.excludes_bug_only must be true")
            if source_mode == "four_source":
                seen_sources = {
                    classify_feedback_source(text(row.get("source")))
                    for row in section.get("source_coverage", []) or []
                    if isinstance(row, dict)
                }
                missing_sources = [
                    label
                    for key, label in REQUIRED_CUSTOMER_FEEDBACK_SOURCES.items()
                    if key not in seen_sources
                ]
                if missing_sources:
                    errors.append(
                        "sections.customer_feedback.source_coverage is missing four-source coverage for: "
                        + ", ".join(missing_sources)
                    )
                for index, row in enumerate(section.get("theme_rows", []) or [], start=1):
                    if not isinstance(row, dict):
                        continue
                    missing_columns = [
                        key
                        for key in REQUIRED_CUSTOMER_FEEDBACK_SOURCES
                        if key not in row
                    ]
                    if missing_columns:
                        errors.append(
                            f"sections.customer_feedback.theme_rows[{index}] is missing four-source columns: {', '.join(missing_columns)}"
                        )
                source_totals = {key: 0.0 for key in REQUIRED_CUSTOMER_FEEDBACK_SOURCES}
                theme_total = 0.0
                can_compare_theme_totals = True
                for index, row in enumerate(section.get("theme_rows", []) or [], start=1):
                    if not isinstance(row, dict):
                        continue
                    row_total = parse_signal_count(row.get("total_signals") or row.get("total"))
                    if row_total is None:
                        errors.append(
                            f"sections.customer_feedback.theme_rows[{index}].total_signals must be a numeric signal count"
                        )
                        can_compare_theme_totals = False
                        continue
                    row_source_total = 0.0
                    for key in REQUIRED_CUSTOMER_FEEDBACK_SOURCES:
                        source_value = parse_signal_count(row.get(key))
                        if source_value is None:
                            errors.append(
                                f"sections.customer_feedback.theme_rows[{index}].{key} must be a numeric signal count"
                            )
                            can_compare_theme_totals = False
                            continue
                        row_source_total += source_value
                        source_totals[key] += source_value
                    if not same_signal_count(row_total, row_source_total):
                        errors.append(
                            f"sections.customer_feedback.theme_rows[{index}].total_signals="
                            f"{format_signal_count(row_total)} does not equal four-source column sum="
                            f"{format_signal_count(row_source_total)}"
                        )
                    theme_total += row_total

                coverage_totals: dict[str, float] = {}
                can_compare_coverage_totals = True
                for index, row in enumerate(section.get("source_coverage", []) or [], start=1):
                    if not isinstance(row, dict):
                        continue
                    source_key = classify_feedback_source(text(row.get("source")))
                    if not source_key:
                        continue
                    signals_used = parse_signal_count(row.get("signals_used"))
                    if signals_used is None:
                        errors.append(
                            f"sections.customer_feedback.source_coverage[{index}].signals_used must be a numeric signal count"
                        )
                        can_compare_coverage_totals = False
                        continue
                    coverage_totals[source_key] = coverage_totals.get(source_key, 0.0) + signals_used

                if can_compare_theme_totals and can_compare_coverage_totals and coverage_totals:
                    for key, label in REQUIRED_CUSTOMER_FEEDBACK_SOURCES.items():
                        if key not in coverage_totals:
                            continue
                        if not same_signal_count(source_totals[key], coverage_totals[key]):
                            errors.append(
                                f"sections.customer_feedback {label} themed total="
                                f"{format_signal_count(source_totals[key])} does not equal source_coverage signals_used="
                                f"{format_signal_count(coverage_totals[key])}; add an Other/Triage row or fix the counts"
                            )
                    coverage_total = sum(coverage_totals.values())
                    if not same_signal_count(theme_total, coverage_total):
                        errors.append(
                            "sections.customer_feedback theme_rows total_signals sum="
                            f"{format_signal_count(theme_total)} does not equal source_coverage signals_used sum="
                            f"{format_signal_count(coverage_total)}; add an Other/Triage row or fix the headline"
                        )

        if section_key == "onboarding":
            source_text_blob = " ".join(trace_text(source_by_id.get(text(source_id))) for source_id in section_source_ids)
            has_onboarding_source = bool(
                re.search(r"(posthog|onboarding|funnel|first[-\s]?value|go[-\s]?live)", source_text_blob, re.IGNORECASE)
            )
            if not has_onboarding_source and not is_truthy_bool(section.get("proxy_only")):
                errors.append(
                    "sections.onboarding must set proxy_only=true when it has no PostHog/onboarding/funnel source"
                )
            has_daily_metrics_onboarding = bool(
                re.search(r"dailyMetricsUpload", source_text_blob, re.IGNORECASE)
            )
            if has_daily_metrics_onboarding:
                if is_truthy_bool(section.get("proxy_only")):
                    errors.append(
                        "sections.onboarding must set proxy_only=false when dailyMetricsUpload onboarding metrics are available"
                    )
                metric_names = " ".join(
                    text(metric.get("name"))
                    for metric in section.get("metrics", []) or []
                    if isinstance(metric, dict)
                )
                for label, pattern in ONBOARDING_PRIMARY_METRICS.items():
                    if not pattern.search(metric_names):
                        errors.append(
                            f"sections.onboarding is missing primary metric: {label}"
                        )

        for metric in section.get("metrics", []) or []:
            if not isinstance(metric, dict):
                errors.append(f"sections.{section_key}.metrics contains non-object item")
                continue
            metric_source = text(metric.get("source_id"))
            if metric_source and metric_source not in source_ids:
                errors.append(
                    f"metric source_id '{metric_source}' in section '{section_key}' is not in traceability"
                )
            confidence = text(metric.get("confidence"))
            if not confidence:
                errors.append(f"metric '{text(metric.get('name'))}' in section '{section_key}' is missing confidence")
            elif confidence not in ALLOWED_CONFIDENCE:
                errors.append(
                    f"metric '{text(metric.get('name'))}' in section '{section_key}' has unsupported confidence '{confidence}'"
                )
            metric_period = text(metric.get("period")).strip()
            if (
                report_granularity == "biweekly"
                and MONTHLY_PERIOD_RE.fullmatch(metric_period)
                and not is_truthy_bool(metric.get("context_only"))
            ):
                errors.append(
                    f"monthly metric '{text(metric.get('name'))}' in biweekly report must set context_only=true"
                )
            metric_trace = trace_text(source_by_id.get(metric_source)).lower()
            metric_text = json.dumps(metric, ensure_ascii=False)
            if "posthog" in metric_trace and MONEY_METRIC_RE.search(metric_text):
                metric_type = text(metric.get("metric_type")).strip().lower()
                if metric_type not in {"telemetry", "usage_proxy"}:
                    errors.append(
                        f"PostHog money-like metric '{text(metric.get('name'))}' must set metric_type=telemetry or usage_proxy"
                    )
                if confidence == "verified":
                    errors.append(
                        f"PostHog money-like metric '{text(metric.get('name'))}' must not use confidence=verified without a finance/Tableau actual source"
                    )

        for index, visual in enumerate(section.get("visuals", []) or [], start=1):
            if not isinstance(visual, dict):
                errors.append(f"sections.{section_key}.visuals[{index}] must be an object")
                continue
            visual_source = text(visual.get("source_id"))
            if visual_source and visual_source not in source_ids:
                errors.append(
                    f"visual source_id '{visual_source}' in section '{section_key}' is not in traceability"
                )
            confidence = text(visual.get("confidence") or "visual_only")
            if confidence not in ALLOWED_CONFIDENCE:
                errors.append(
                    f"visual '{text(visual.get('title'))}' in section '{section_key}' has unsupported confidence '{confidence}'"
                )
            if not any(text(visual.get(field)) for field in ["src", "href", "image_url", "url"]):
                errors.append(
                    f"visual '{text(visual.get('title'))}' in section '{section_key}' needs src, href, image_url, or url"
                )

        if section_key == "retention":
            for index, detail in enumerate(section.get("churn_reason_details", []) or [], start=1):
                if not isinstance(detail, dict):
                    errors.append(f"sections.retention.churn_reason_details[{index}] must be an object")
                    continue
                keys = {text(key).lower() for key in detail.keys()}
                leaked_keys = sorted(keys & CHURN_REASON_IDENTITY_KEYS)
                if leaked_keys:
                    errors.append(
                        f"sections.retention.churn_reason_details[{index}] contains identity keys: {', '.join(leaked_keys)}"
                    )
                reason = text(detail.get("reason") or detail.get("churn_reason"))
                if SENSITIVE_CHURN_REASON_RE.search(reason):
                    errors.append(
                        f"sections.retention.churn_reason_details[{index}] contains sensitive personal churn reason; rewrite to a low-sensitivity business reason"
                    )

    if has_secret(pack):
        errors.append("possible secret found in evidence pack")
    if contains_forbidden_output(pack):
        errors.append(
            "deprecated churn reason quality wording found; use direct sanitized churn_reason_details instead"
        )

    pre_generation_confirmations = pack.get("pre_generation_confirmations") or []
    if pre_generation_confirmations:
        errors.append(
            "pre_generation_confirmations is not empty; confirm data questions before rendering the final document"
        )

    meeting_notes = pack.get("meeting_notes") or []
    if meeting_notes and not contains_cjk(meeting_notes):
        errors.append("meeting_notes business narrative must be written in Chinese")
    for index, note in enumerate(meeting_notes, start=1):
        if contains_pre_generation_confirmation(note):
            errors.append(
                f"meeting_notes[{index}] looks like a pre-generation data confirmation; move it to pre_generation_confirmations"
            )

    return errors


def render_list(items: list[Any], empty_text: str) -> str:
    if not items:
        return f"<p><span text-color=\"gray\">{x(empty_text)}</span></p>"
    lines = []
    for item in items:
        if isinstance(item, dict):
            body = item.get("text") or item.get("question") or item.get("name") or json.dumps(item, ensure_ascii=False)
        else:
            body = item
        lines.append(f"<li><p>{x(body)}</p></li>")
    return "<ul>" + "".join(lines) + "</ul>"


def render_summary_callout(items: list[Any], empty_text: str) -> str:
    if not items:
        return f"<p><span text-color=\"gray\">{x(empty_text)}</span></p>"
    lines = []
    for item in items:
        body = item.get("text") if isinstance(item, dict) else item
        lines.append(f"<li>{x(body)}</li>")
    return (
        '<callout emoji="📌" background-color="light-blue" border-color="blue">'
        "<ul>"
        + "".join(lines)
        + "</ul></callout>"
    )


def render_metrics(metrics: list[Any]) -> str:
    if not metrics:
        return "<p><span text-color=\"gray\">暂无已验证指标。</span></p>"
    rows = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        confidence = text(metric.get("confidence") or "unknown")
        color = "green" if confidence == "verified" else "orange" if confidence in {"derived", "manual", "visual_only"} else "gray"
        rows.append(
            "<tr>"
            f"<td>{x(metric.get('name'))}</td>"
            f"<td>{x(metric.get('value'))}</td>"
            f"<td>{x(metric.get('delta'))}</td>"
            f"<td>{x(metric.get('period'))}</td>"
            f"<td><span text-color=\"{color}\">{x(confidence)}</span></td>"
            f"<td><code>{x(metric.get('source_id'))}</code></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">指标</th>"
        "<th background-color=\"light-gray\">数值</th>"
        "<th background-color=\"light-gray\">变化 / 口径</th>"
        "<th background-color=\"light-gray\">周期</th>"
        "<th background-color=\"light-gray\">置信度</th>"
        "<th background-color=\"light-gray\">来源</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_customer_examples(examples: list[Any]) -> str:
    rendered = []
    for example in examples:
        if not isinstance(example, dict):
            continue
        example_text = x(example.get("text"))
        if not example_text:
            continue
        if text(example.get("representation")).strip() == "anonymized_paraphrase":
            body = f"匿名转述：“{example_text}”"
        else:
            body = f"“{example_text}”"
        source_links = []
        for source in example.get("sources") or []:
            if not isinstance(source, dict):
                continue
            label = source.get("label") or source.get("url")
            url = source.get("url")
            if url:
                source_links.append(f'<a href="{x(url)}">{x(label)}</a>')
        if source_links:
            body += "<br/>出处：" + " · ".join(source_links)
        rendered.append(body)
    return "<br/><br/>".join(rendered)


def render_insights(insights: list[Any], *, include_customer_examples: bool = False) -> str:
    if not insights:
        return "<p><span text-color=\"gray\">暂无模块洞察；请补充 Data / Insight / Team attention。</span></p>"
    rows = []
    for item in insights:
        if not isinstance(item, dict):
            empty_example_cell = "<td></td>" if include_customer_examples else ""
            rows.append(
                "<tr>"
                "<td></td>"
                f"<td>{x(item)}</td>"
                "<td></td>"
                + empty_example_cell
                + "<td></td>"
                "</tr>"
            )
            continue
        example_cell = (
            f"<td>{render_customer_examples(item.get('customer_examples') or [])}</td>"
            if include_customer_examples
            else ""
        )
        rows.append(
            "<tr>"
            f"<td>{x(item.get('topic') or item.get('name'))}</td>"
            f"<td>{x(item.get('data') or item.get('data_point') or item.get('observation'))}</td>"
            f"<td>{x(item.get('insight') or item.get('interpretation') or item.get('impact'))}</td>"
            + example_cell
            + f"<td>{x(item.get('team_attention') or item.get('suggested_action') or item.get('recommendation'))}</td>"
            + "</tr>"
        )
    example_header = (
        "<th background-color=\"light-gray\">客户原话 example（匿名）</th>"
        if include_customer_examples
        else ""
    )
    return (
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">主题</th>"
        "<th background-color=\"light-gray\">数据</th>"
        "<th background-color=\"light-gray\">洞察</th>"
        + example_header
        + "<th background-color=\"light-gray\">团队关注</th>"
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_customer_feedback_data(section: dict[str, Any]) -> str:
    rows = section.get("theme_rows") or section.get("data_rows") or []
    if not rows:
        return render_metrics(section.get("metrics") or [])

    source_mode = text(section.get("source_mode")).strip().lower()
    rendered_rows = []
    for row in rows:
        if isinstance(row, dict) and source_mode == "jira_only":
            values = [
                row.get("theme") or row.get("problem_area"),
                row.get("jira_grooming_cs") or row.get("jira") or row.get("total_signals") or row.get("total"),
                row.get("readout") or row.get("interpretation"),
            ]
        elif isinstance(row, dict):
            values = [
                row.get("theme") or row.get("problem_area"),
                row.get("total_signals") or row.get("total"),
                row.get("community_fr"),
                row.get("quick_win_canny"),
                row.get("intercom_feedback"),
                row.get("jira_grooming_cs") or row.get("jira"),
                row.get("readout") or row.get("interpretation"),
            ]
        elif source_mode == "jira_only":
            values = list(row)[:3]
            values += [""] * (3 - len(values))
        else:
            values = list(row)[:7]
            values += [""] * (7 - len(values))
        rendered_rows.append("<tr>" + "".join(f"<td>{x(value)}</td>" for value in values) + "</tr>")

    if source_mode == "jira_only":
        return (
            "<table><thead><tr>"
            "<th background-color=\"light-gray\">主题 / 问题域</th>"
            "<th background-color=\"light-gray\">Jira Grooming CS</th>"
            "<th background-color=\"light-gray\">解读</th>"
            "</tr></thead><tbody>"
            + "".join(rendered_rows)
            + "</tbody></table>"
        )

    return (
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">主题 / 问题域</th>"
        "<th background-color=\"light-gray\">总信号数</th>"
        "<th background-color=\"light-gray\">Community FR</th>"
        "<th background-color=\"light-gray\">Quick-win Canny</th>"
        "<th background-color=\"light-gray\">Intercom feedback</th>"
        "<th background-color=\"light-gray\">Jira Grooming CS</th>"
        "<th background-color=\"light-gray\">解读</th>"
        "</tr></thead><tbody>"
        + "".join(rendered_rows)
        + "</tbody></table>"
    )


def render_customer_feedback_source_coverage(section: dict[str, Any]) -> str:
    rows = section.get("source_coverage") or []
    if not rows:
        return ""

    rendered_rows = []
    for row in rows:
        if isinstance(row, dict):
            values = [
                row.get("source"),
                row.get("signals_used"),
                row.get("rows_scanned"),
                row.get("window") or row.get("filter"),
            ]
        else:
            values = list(row)[:4]
            values += [""] * (4 - len(values))
        rendered_rows.append("<tr>" + "".join(f"<td>{x(value)}</td>" for value in values) + "</tr>")

    return (
        "<p><b>来源覆盖</b></p>"
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">来源</th>"
        "<th background-color=\"light-gray\">使用信号数</th>"
        "<th background-color=\"light-gray\">扫描行数</th>"
        "<th background-color=\"light-gray\">窗口 / 过滤条件</th>"
        "</tr></thead><tbody>"
        + "".join(rendered_rows)
        + "</tbody></table>"
    )


def render_churn_reason_details(details: list[Any]) -> str:
    if not details:
        return ""
    rows = []
    for item in details:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{x(item.get('date') or item.get('period'))}</td>"
            f"<td>{x(item.get('segment') or item.get('business_type') or item.get('business_segment'))}</td>"
            f"<td>{x(item.get('tier') or item.get('logo_tier'))}</td>"
            f"<td>{x(item.get('reason') or item.get('churn_reason'))}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        "<h3>Churn reason 明细</h3>"
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">日期</th>"
        "<th background-color=\"light-gray\">分组 / Business Type</th>"
        "<th background-color=\"light-gray\">Tier</th>"
        "<th background-color=\"light-gray\">Churn reason</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_visuals(visuals: list[Any]) -> str:
    if not visuals:
        return ""
    blocks = ["<h3>图表 / 截图</h3>"]
    for visual in visuals:
        if not isinstance(visual, dict):
            continue
        title = text(visual.get("title") or visual.get("name") or "Visual evidence")
        confidence = text(visual.get("confidence") or "visual_only")
        source_id = text(visual.get("source_id"))
        caption = text(visual.get("caption") or title)
        width = text(visual.get("width") or 960)
        height = text(visual.get("height"))
        name = text(visual.get("file_name") or visual.get("name") or f"{title}.png")
        src = text(visual.get("src"))
        href = text(visual.get("href") or visual.get("image_url") or visual.get("url"))

        blocks.append(f"<p><b>{x(title)}</b> <span text-color=\"orange\">{x(confidence)}</span></p>")
        if src or href:
            attrs = [f'width="{x(width)}"', f'caption="{x(caption)}"', f'name="{x(name)}"']
            if height:
                attrs.append(f'height="{x(height)}"')
            if src:
                attrs.insert(0, f'src="{x(src)}"')
            else:
                attrs.insert(0, f'href="{x(href)}"')
            blocks.append("<img " + " ".join(attrs) + "/>")
        if source_id:
            blocks.append(f"<p><span text-color=\"gray\">来源：<code>{x(source_id)}</code></span></p>")
    return "".join(blocks)


def is_publishable_traceability_item(item: Any) -> bool:
    return isinstance(item, dict) and text(item.get("source_type")).strip().lower() != "manual_policy"


def format_retrieved_at(value: Any) -> str:
    raw = text(value).strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.removesuffix("Z") + ("+00:00" if raw.endswith("Z") else ""))
    except ValueError:
        return raw
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone(timedelta(hours=8)))
    return parsed.strftime("%Y-%m-%d %H:%M")


def render_traceability(items: list[Any]) -> str:
    if not items:
        return "<p><span text-color=\"red\">缺少 traceability 数据。</span></p>"
    rows = []
    for item in items:
        if not is_publishable_traceability_item(item):
            continue
        url = text(item.get("source_url"))
        title = x(item.get("title"))
        link = f"<a href=\"{x(url)}\">{title}</a>" if url else title
        rows.append(
            "<tr>"
            f"<td>{link}</td>"
            f"<td>{x(item.get('query_or_filter'))}</td>"
            f"<td>{x(format_retrieved_at(item.get('retrieved_at')))}</td>"
            f"<td>{x(item.get('owner'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">标题</th>"
        "<th background-color=\"light-gray\">查询 / 过滤条件</th>"
        "<th background-color=\"light-gray\">拉取时间</th>"
        "<th background-color=\"light-gray\">Owner</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_meeting_notes(meeting_notes: list[Any], open_questions: list[Any]) -> str:
    items = meeting_notes or open_questions
    if not items:
        return "<p><span text-color=\"gray\">暂无会议讨论项。</span></p>"

    rows = []
    structured = any(isinstance(item, dict) and item.get("observation") for item in items)
    if structured:
        for item in items:
            if not isinstance(item, dict):
                rows.append(
                    "<tr>"
                    f"<td>{x(item)}</td>"
                    "<td></td><td></td><td></td><td></td>"
                    "</tr>"
                )
                continue
            rows.append(
                "<tr>"
                f"<td>{x(item.get('topic') or item.get('section'))}</td>"
                f"<td>{x(item.get('observation'))}</td>"
                f"<td>{x(item.get('impact') or item.get('why_it_matters'))}</td>"
                f"<td>{x(item.get('suggested_action') or item.get('recommendation') or item.get('question'))}</td>"
                f"<td>{x(item.get('owner'))}</td>"
                "</tr>"
            )
        return (
            "<table><thead><tr>"
            "<th background-color=\"light-gray\">主题</th>"
            "<th background-color=\"light-gray\">观察</th>"
            "<th background-color=\"light-gray\">影响</th>"
            "<th background-color=\"light-gray\">建议动作 / 决策</th>"
            "<th background-color=\"light-gray\">Owner</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )

    for item in items:
        if isinstance(item, dict):
            topic = item.get("section") or item.get("topic")
            question = item.get("question") or item.get("text") or item.get("name") or json.dumps(item, ensure_ascii=False)
            owner = item.get("owner")
        else:
            topic = ""
            question = item
            owner = ""
        rows.append(
            "<tr>"
            f"<td>{x(topic)}</td>"
            f"<td>{x(question)}</td>"
            f"<td>{x(owner)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">领域</th>"
        "<th background-color=\"light-gray\">问题 / 后续动作</th>"
        "<th background-color=\"light-gray\">Owner</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def md_text(value: Any) -> str:
    return text(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def md_cell(value: Any) -> str:
    normalized = md_text(value).replace("\n", "<br>")
    return normalized.replace("|", "\\|")


def md_link(label: Any, url: Any) -> str:
    label_text = md_text(label)
    url_text = md_text(url)
    if not url_text:
        return label_text
    safe_label = label_text.replace("[", "\\[").replace("]", "\\]")
    safe_url = url_text.replace(")", "%29")
    return f"[{safe_label}]({safe_url})"


def md_table(headers: list[str], rows: list[list[Any]], empty_text: str = "") -> str:
    if not rows:
        return f"{empty_text}\n" if empty_text else ""
    header = "| " + " | ".join(md_cell(item) for item in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = []
    for row in rows:
        normalized = list(row[: len(headers)])
        normalized += [""] * (len(headers) - len(normalized))
        body.append("| " + " | ".join(md_cell(item) for item in normalized) + " |")
    return "\n".join([header, separator, *body]) + "\n"


def md_list(items: list[Any], empty_text: str) -> str:
    if not items:
        return f"{empty_text}\n"
    lines = []
    for item in items:
        if isinstance(item, dict):
            body = item.get("text") or item.get("question") or item.get("name") or json.dumps(item, ensure_ascii=False)
        else:
            body = item
        lines.append(f"- {md_text(body)}")
    return "\n".join(lines) + "\n"


def md_summary_callout(items: list[Any], empty_text: str) -> str:
    if not items:
        return f"> {empty_text}\n"
    lines = []
    for item in items:
        body = item.get("text") if isinstance(item, dict) else item
        lines.append(f"> - {md_text(body)}")
    return "\n".join(lines) + "\n"


def md_metrics(metrics: list[Any]) -> str:
    rows = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        rows.append(
            [
                metric.get("name"),
                metric.get("value"),
                metric.get("delta"),
                metric.get("period"),
                metric.get("confidence"),
                metric.get("source_id"),
            ]
        )
    return md_table(
        ["指标", "数值", "变化 / 口径", "周期", "置信度", "来源"],
        rows,
        "暂无已验证指标。",
    )


def md_customer_examples(examples: list[Any]) -> str:
    rendered = []
    for example in examples:
        if not isinstance(example, dict):
            continue
        example_text = md_text(example.get("text"))
        if not example_text:
            continue
        if text(example.get("representation")).strip() == "anonymized_paraphrase":
            body = f"匿名转述：“{example_text}”"
        else:
            body = f"“{example_text}”"
        source_links = []
        for source in example.get("sources") or []:
            if not isinstance(source, dict):
                continue
            label = source.get("label") or source.get("url")
            url = source.get("url")
            if url:
                source_links.append(md_link(label, url))
        if source_links:
            body += "<br>出处：" + " · ".join(source_links)
        rendered.append(body)
    return "<br><br>".join(rendered)


def md_insights(insights: list[Any], *, include_customer_examples: bool = False) -> str:
    rows = []
    for item in insights:
        if not isinstance(item, dict):
            row = ["", item, ""]
            if include_customer_examples:
                row.append("")
            row.append("")
            rows.append(row)
            continue
        row = [
            item.get("topic") or item.get("name"),
            item.get("data") or item.get("data_point") or item.get("observation"),
            item.get("insight") or item.get("interpretation") or item.get("impact"),
        ]
        if include_customer_examples:
            row.append(md_customer_examples(item.get("customer_examples") or []))
        row.append(
            item.get("team_attention") or item.get("suggested_action") or item.get("recommendation")
        )
        rows.append(row)
    headers = ["主题", "数据", "洞察"]
    if include_customer_examples:
        headers.append("客户原话 example（匿名）")
    headers.append("团队关注")
    return md_table(
        headers,
        rows,
        "暂无模块洞察；请补充 Data / Insight / Team attention。",
    )


def md_customer_feedback_data(section: dict[str, Any]) -> str:
    rows = section.get("theme_rows") or section.get("data_rows") or []
    if not rows:
        return md_metrics(section.get("metrics") or [])

    source_mode = text(section.get("source_mode")).strip().lower()
    rendered_rows = []
    if source_mode == "jira_only":
        headers = ["主题 / 问题域", "Jira Grooming CS", "解读"]
        for row in rows:
            if isinstance(row, dict):
                rendered_rows.append(
                    [
                        row.get("theme") or row.get("problem_area"),
                        row.get("jira_grooming_cs") or row.get("jira") or row.get("total_signals") or row.get("total"),
                        row.get("readout") or row.get("interpretation"),
                    ]
                )
            else:
                rendered_rows.append(list(row)[:3])
        return md_table(headers, rendered_rows)

    headers = [
        "主题 / 问题域",
        "总信号数",
        "Community FR",
        "Quick-win Canny",
        "Intercom feedback",
        "Jira Grooming CS",
        "解读",
    ]
    for row in rows:
        if isinstance(row, dict):
            rendered_rows.append(
                [
                    row.get("theme") or row.get("problem_area"),
                    row.get("total_signals") or row.get("total"),
                    row.get("community_fr"),
                    row.get("quick_win_canny"),
                    row.get("intercom_feedback"),
                    row.get("jira_grooming_cs") or row.get("jira"),
                    row.get("readout") or row.get("interpretation"),
                ]
            )
        else:
            rendered_rows.append(list(row)[:7])
    return md_table(headers, rendered_rows)


def md_customer_feedback_source_coverage(section: dict[str, Any]) -> str:
    rows = []
    for row in section.get("source_coverage") or []:
        if isinstance(row, dict):
            rows.append(
                [
                    row.get("source"),
                    row.get("signals_used"),
                    row.get("rows_scanned"),
                    row.get("window") or row.get("filter"),
                ]
            )
        else:
            rows.append(list(row)[:4])
    if not rows:
        return ""
    return "#### 来源覆盖\n\n" + md_table(["来源", "使用信号数", "扫描行数", "窗口 / 过滤条件"], rows)


def md_churn_reason_details(details: list[Any]) -> str:
    rows = []
    for item in details:
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                item.get("date") or item.get("period"),
                item.get("segment") or item.get("business_type") or item.get("business_segment"),
                item.get("tier") or item.get("logo_tier"),
                item.get("reason") or item.get("churn_reason"),
            ]
        )
    if not rows:
        return ""
    return "### Churn reason 明细\n\n" + md_table(["日期", "分组 / Business Type", "Tier", "Churn reason"], rows)


def md_visuals(visuals: list[Any]) -> str:
    if not visuals:
        return ""
    blocks = ["### 图表 / 截图\n"]
    for visual in visuals:
        if not isinstance(visual, dict):
            continue
        title = md_text(visual.get("title") or visual.get("name") or "Visual evidence")
        confidence = md_text(visual.get("confidence") or "visual_only")
        source_id = md_text(visual.get("source_id"))
        caption = md_text(visual.get("caption") or title)
        href = md_text(visual.get("href") or visual.get("image_url") or visual.get("url") or visual.get("src"))
        blocks.append(f"**{title}** `{confidence}`\n")
        if href:
            blocks.append(f"![{title}]({href})\n")
        if caption:
            blocks.append(f"{caption}\n")
        if source_id:
            blocks.append(f"来源：`{source_id}`\n")
    return "\n".join(blocks) + "\n"


def md_traceability(items: list[Any]) -> str:
    rows = []
    for item in items:
        if not is_publishable_traceability_item(item):
            continue
        rows.append(
            [
                md_link(item.get("title"), item.get("source_url")),
                item.get("query_or_filter"),
                format_retrieved_at(item.get("retrieved_at")),
                item.get("owner"),
            ]
        )
    return md_table(
        ["标题", "查询 / 过滤条件", "拉取时间", "Owner"],
        rows,
        "缺少 traceability 数据。",
    )


def md_meeting_notes(meeting_notes: list[Any], open_questions: list[Any]) -> str:
    items = meeting_notes or open_questions
    if not items:
        return "暂无会议讨论项。\n"

    structured = any(isinstance(item, dict) and item.get("observation") for item in items)
    rows = []
    if structured:
        for item in items:
            if not isinstance(item, dict):
                rows.append([item, "", "", "", ""])
                continue
            rows.append(
                [
                    item.get("topic") or item.get("section"),
                    item.get("observation"),
                    item.get("impact") or item.get("why_it_matters"),
                    item.get("suggested_action") or item.get("recommendation") or item.get("question"),
                    item.get("owner"),
                ]
            )
        return md_table(["主题", "观察", "影响", "建议动作 / 决策", "Owner"], rows)

    for item in items:
        if isinstance(item, dict):
            rows.append(
                [
                    item.get("section") or item.get("topic"),
                    item.get("question") or item.get("text") or item.get("name") or json.dumps(item, ensure_ascii=False),
                    item.get("owner"),
                ]
            )
        else:
            rows.append(["", item, ""])
    return md_table(["领域", "问题 / 后续动作", "Owner"], rows)


def md_section(key: str, section: dict[str, Any]) -> str:
    if key == "customer_feedback":
        return md_customer_feedback_section(section)

    title = SECTION_TITLES[key]
    parts = [
        f"## {title}",
        md_section_description(title),
        "### 数据 / 洞察 / 团队关注\n",
        md_insights(
            section.get("insights") or [],
            include_customer_examples=key in CUSTOMER_EXAMPLE_SECTIONS,
        ),
        "### 重点\n",
        md_list(section.get("highlights") or [], "暂无重点。"),
        "### 指标\n",
        md_metrics(section.get("metrics") or []),
    ]
    if key == "retention":
        churn_details = md_churn_reason_details(section.get("churn_reason_details") or [])
        if churn_details:
            parts.append(churn_details)
    visuals = md_visuals(section.get("visuals") or [])
    if visuals:
        parts.append(visuals)
    parts.extend(["### 风险 / 关注点\n", md_list(section.get("risks") or [], "暂无风险。")])
    return "\n".join(parts)


def md_customer_feedback_section(section: dict[str, Any]) -> str:
    summary = section.get("summary") or section.get("summary_bullets") or section.get("highlights") or []
    parts = [
        f"## {SECTION_TITLES['customer_feedback']}",
        md_section_description(SECTION_TITLES["customer_feedback"]),
        "### 摘要\n",
        md_summary_callout(summary, "暂无 Customer Feedback & FR 摘要。"),
        "### 洞察\n",
        md_insights(section.get("insights") or [], include_customer_examples=True),
    ]
    risks = section.get("risks") or []
    if risks:
        parts.extend(["#### 关注点\n", md_list(risks, "暂无风险。")])
    parts.extend(
        [
            "### 数据\n",
            md_customer_feedback_data(section),
            md_customer_feedback_source_coverage(section),
        ]
    )
    return "\n".join(part for part in parts if part)


def md_overall_summary(items: Any) -> str:
    if isinstance(items, dict):
        items = [items]
    if not items:
        return "暂无总览；请先补充各模块 insights。\n"
    if not isinstance(items, list):
        items = [items]
    return "\n".join(f"- {md_summary_text(item)}" for item in items) + "\n"


def collect_summary_items(pack: dict[str, Any]) -> list[Any]:
    sections = pack.get("sections") or {}
    overall_summary = pack.get("overall_summary") or []
    if isinstance(overall_summary, list):
        summary_items = list(overall_summary)
    elif overall_summary:
        summary_items = [overall_summary]
    else:
        summary_items = []
    if not summary_items:
        for key in REQUIRED_SECTIONS:
            section = sections.get(key) or {}
            for insight in section.get("insights") or []:
                if len(summary_items) < 5:
                    summary_items.append(insight)
    if not summary_items:
        for key in REQUIRED_SECTIONS:
            section = sections.get(key) or {}
            for highlight in section.get("highlights") or []:
                if len(summary_items) < 5:
                    summary_items.append(text(highlight))
    return summary_items


def render_markdown(pack: dict[str, Any]) -> str:
    sections = pack.get("sections") or {}
    parts = [
        "## Overall Summary / 总览\n",
        md_section_description("Overall Summary / 总览"),
        md_overall_summary(collect_summary_items(pack)),
    ]
    for key in REQUIRED_SECTIONS:
        parts.append(md_section(key, sections.get(key) or {}))
    parts.extend(
        [
            "## Meeting Notes / Open Questions / 会议讨论与待开放问题\n",
            md_section_description("Meeting Notes / Open Questions / 会议讨论与待开放问题"),
            md_meeting_notes(pack.get("meeting_notes") or [], pack.get("open_questions") or []),
            "## Data Source & Traceability / 数据源与可追溯性\n",
            md_section_description("Data Source & Traceability / 数据源与可追溯性"),
            md_traceability(pack.get("traceability") or []),
        ]
    )
    return "\n".join(part.rstrip() for part in parts if part is not None) + "\n"


def render_section(key: str, section: dict[str, Any]) -> str:
    if key == "customer_feedback":
        return render_customer_feedback_section(section)

    title = SECTION_TITLES[key]
    return (
        f"<h2>{x(title)}</h2>"
        + render_section_description(title)
        + "<h3>数据 / 洞察 / 团队关注</h3>"
        + render_insights(
            section.get("insights") or [],
            include_customer_examples=key in CUSTOMER_EXAMPLE_SECTIONS,
        )
        + "<h3>重点</h3>"
        + render_list(section.get("highlights") or [], "暂无重点。")
        + "<h3>指标</h3>"
        + render_metrics(section.get("metrics") or [])
        + (render_churn_reason_details(section.get("churn_reason_details") or []) if key == "retention" else "")
        + render_visuals(section.get("visuals") or [])
        + "<h3>风险 / 关注点</h3>"
        + render_list(section.get("risks") or [], "暂无风险。")
    )


def render_customer_feedback_section(section: dict[str, Any]) -> str:
    summary = section.get("summary") or section.get("summary_bullets") or section.get("highlights") or []
    insight_blocks = render_insights(
        section.get("insights") or [],
        include_customer_examples=True,
    )
    risks = section.get("risks") or []
    if risks:
        insight_blocks += "<p><b>关注点</b></p>" + render_list(risks, "暂无风险。")

    return (
        f"<h2>{x(SECTION_TITLES['customer_feedback'])}</h2>"
        + render_section_description(SECTION_TITLES["customer_feedback"])
        + "<h3>摘要</h3>"
        + render_summary_callout(summary, "暂无 Customer Feedback & FR 摘要。")
        + "<h3>洞察</h3>"
        + insight_blocks
        + "<h3>数据</h3>"
        + render_customer_feedback_data(section)
        + render_customer_feedback_source_coverage(section)
    )


def render_overall_summary(items: Any) -> str:
    if isinstance(items, dict):
        items = [items]
    if not items:
        return "<p><span text-color=\"gray\">暂无总览；请先补充各模块 insights。</span></p>"
    if not isinstance(items, list):
        items = [items]
    lines = [f"<li><p>{render_summary_text(item)}</p></li>" for item in items]
    return "<ul>" + "".join(lines) + "</ul>"


def summary_conclusion(item: Any) -> str:
    if not isinstance(item, dict):
        return text(item).strip()
    return text(
        item.get("conclusion")
        or item.get("text")
        or item.get("insight")
        or item.get("data")
        or item.get("observation")
        or item.get("name")
    ).strip()


def summary_emphasis(item: Any, body: str) -> list[tuple[str, str]]:
    raw_items = (item.get("emphasis") or []) if isinstance(item, dict) else []
    if isinstance(raw_items, (str, dict)):
        raw_items = [raw_items]

    emphasis: list[tuple[str, str]] = []
    for raw_item in raw_items:
        if isinstance(raw_item, dict):
            phrase = text(raw_item.get("text")).strip()
            color = text(raw_item.get("color") or "blue").strip().lower()
        else:
            phrase = text(raw_item).strip()
            color = "blue"
        if phrase:
            emphasis.append((phrase, color if color in SUMMARY_TEXT_COLORS else "blue"))

    if not emphasis:
        lead = re.match(r"^([^：:\n]{2,24}[：:])", body)
        if lead:
            emphasis.append((lead.group(1), "blue"))
    return emphasis


def emphasized_ranges(body: str, emphasis: list[tuple[str, str]]) -> list[tuple[int, int, str]]:
    candidates = []
    for phrase, color in emphasis:
        candidates.extend((match.start(), match.end(), color) for match in re.finditer(re.escape(phrase), body))

    ranges = []
    cursor = 0
    for start, end, color in sorted(candidates, key=lambda value: (value[0], -(value[1] - value[0]))):
        if start < cursor:
            continue
        ranges.append((start, end, color))
        cursor = end
    return ranges


def render_summary_text(item: Any) -> str:
    body = summary_conclusion(item)
    ranges = emphasized_ranges(body, summary_emphasis(item, body))
    if not ranges:
        return x(body)

    parts = []
    cursor = 0
    for start, end, color in ranges:
        parts.append(x(body[cursor:start]))
        parts.append(f'<b><span text-color="{color}">{x(body[start:end])}</span></b>')
        cursor = end
    parts.append(x(body[cursor:]))
    return "".join(parts)


def md_summary_text(item: Any) -> str:
    body = summary_conclusion(item)
    ranges = emphasized_ranges(body, summary_emphasis(item, body))
    if not ranges:
        return md_inline(body)

    parts = []
    cursor = 0
    for start, end, _color in ranges:
        parts.append(md_inline(body[cursor:start]))
        parts.append(f"**{md_inline(body[start:end])}**")
        cursor = end
    parts.append(md_inline(body[cursor:]))
    return "".join(parts)


def md_inline(value: Any) -> str:
    normalized = text(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    return normalized.replace("\\", "\\\\").replace("*", "\\*")


def md_section_description(title: str) -> str:
    return f"> {SECTION_DESCRIPTIONS[title]}\n"


def render_section_description(title: str) -> str:
    return f'<p><span text-color="gray">{x(SECTION_DESCRIPTIONS[title])}</span></p>'


def render_xml(pack: dict[str, Any]) -> str:
    report = pack["report"]
    title = text(report.get("title") or "Grooming Ops Review").strip()
    period = text(report.get("period") or "")

    sections = pack.get("sections") or {}

    parts = [
        f"<title>{x(title)} - {x(period)}</title>",
        "<h2>Overall Summary / 总览</h2>",
        render_section_description("Overall Summary / 总览"),
        render_overall_summary(collect_summary_items(pack)),
    ]
    for key in REQUIRED_SECTIONS:
        parts.append(render_section(key, sections.get(key) or {}))

    open_questions = pack.get("open_questions") or []
    parts.extend(
        [
            "<h2>Meeting Notes / Open Questions / 会议讨论与待开放问题</h2>",
            render_section_description("Meeting Notes / Open Questions / 会议讨论与待开放问题"),
            render_meeting_notes(pack.get("meeting_notes") or [], open_questions),
            "<h2>Data Source &amp; Traceability / 数据源与可追溯性</h2>",
            render_section_description("Data Source & Traceability / 数据源与可追溯性"),
            render_traceability(pack.get("traceability") or []),
        ]
    )
    return "".join(parts)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Evidence pack JSON path")
    parser.add_argument("--output", type=Path, help="Output path; stdout when omitted")
    parser.add_argument(
        "--format",
        choices=["markdown", "xml"],
        default="markdown",
        help="Output format; defaults to markdown",
    )
    parser.add_argument("--check", action="store_true", help="Validate evidence pack before rendering")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    pack = load_json(args.input)
    errors = validate_pack(pack)
    if args.check and errors:
        for error in errors:
            print(f"[ops-review-doc-generator] {error}", file=sys.stderr)
        return 2
    rendered = render_xml(pack) if args.format == "xml" else render_markdown(pack)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    if args.check:
        print("[ops-review-doc-generator] evidence pack check passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
