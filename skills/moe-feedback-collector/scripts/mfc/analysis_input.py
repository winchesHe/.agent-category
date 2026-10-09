from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from .dashboard import SOURCE_ORDER, build_dashboard_snapshot
from .errors import BusinessError, ConfigError
from .report import (
    FACEBOOK_PUBLISH_RULE_VERSION,
    INTERCOM_PUBLISH_RULE_VERSION,
    JIRA_PUBLISH_RULE_VERSION,
)

ANALYSIS_INPUT_SCHEMA_VERSION = 1
WEEKLY_ANALYSIS_RULE_VERSION = "grooming-weekly-analysis-v4"
LEGACY_WEEKLY_ANALYSIS_RULE_VERSIONS = {"grooming-weekly-analysis-v3"}
CANNY_SELECTION_RULE_VERSION = "canny-weekly-evidence-v1"
BUSINESS_CATEGORIES = (
    "scheduling",
    "fulfillment",
    "communication",
    "management",
    "payment",
    "van-staff-shift-management",
    "others",
)
AI_BUSINESS_CATEGORIES = BUSINESS_CATEGORIES[:-1]
ANALYSIS_CONFIDENCES = {"high", "medium", "low"}
SOURCE_SELECTION_RULES = {
    "canny": CANNY_SELECTION_RULE_VERSION,
    "intercom": INTERCOM_PUBLISH_RULE_VERSION,
    "jira": JIRA_PUBLISH_RULE_VERSION,
    "facebook": FACEBOOK_PUBLISH_RULE_VERSION,
}
FINAL_ANALYSIS_KEYS = {
    "schemaVersion",
    "analysisRule",
    "scope",
    "currentPeriod",
    "comparisonPeriod",
    "comparisonBaseline",
    "baselineExport",
    "classifications",
    "quickWinAssessments",
    "quickWinCandidates",
    "categoryOverview",
    "reviewQueue",
    "weekComparison",
    "summary",
    "themes",
    "featuredEvidenceRefs",
    "insights",
    "recommendations",
}
FINAL_CLASSIFICATION_KEYS = {
    "evidenceId",
    "decision",
    "primaryCategory",
    "auxiliaryCategories",
    "candidateCategories",
    "confidence",
    "reason",
    "classificationSource",
    "reviewMetadata",
}


def _load_json(path, label):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"无法读取{label}：{path}") from exc
    if not isinstance(payload, dict):
        raise BusinessError(f"{label}结构无效")
    return payload


def _text(value, label, *, limit=2000):
    text = str(value or "").strip()
    if not text or len(text) > limit or "\x00" in text:
        raise ConfigError(f"{label}必须是 {limit} 字以内的非空文本")
    return text


def _period(value, label):
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise ConfigError(f"{label}结构无效")
    try:
        start = date.fromisoformat(str(value.get("start") or ""))
        end = date.fromisoformat(str(value.get("end") or ""))
    except ValueError as exc:
        raise ConfigError(f"{label}日期无效") from exc
    if end < start or (end - start).days > 6:
        raise ConfigError(f"{label}必须位于同一自然周内")
    return start, end


def _date_time(value, label):
    text = _text(value, label, limit=100)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"{label}日期时间无效") from exc
    if parsed.utcoffset() is None:
        raise ConfigError(f"{label}必须包含时区")
    return text


def _safe_url(value, label):
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{label}必须是 http(s) URL 或空字符串")
    return text


def _unavailable_baseline(reason):
    return {
        "status": "unavailable",
        "reason": reason,
        "period": None,
        "artifactId": None,
        "schemaVersion": None,
        "scope": None,
        "categories": [],
        "reviewCount": None,
    }


def _baseline_categories(value):
    if not isinstance(value, list) or len(value) != len(BUSINESS_CATEGORIES):
        raise ConfigError("上周 v3 baselineExport 必须包含完整七类")
    normalized = []
    evidence_ids = set()
    for index, expected_category in enumerate(BUSINESS_CATEGORIES):
        item = value[index]
        if not isinstance(item, dict) or set(item) != {
            "businessCategory",
            "count",
            "representativeEvidence",
        }:
            raise ConfigError(f"上周 v3 baselineExport.categories[{index}] 结构无效")
        if item.get("businessCategory") != expected_category:
            raise ConfigError("上周 v3 baselineExport 分类顺序无效")
        count = item.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ConfigError("上周 v3 baselineExport 分类计数无效")
        raw_evidence = item.get("representativeEvidence")
        if not isinstance(raw_evidence, list) or len(raw_evidence) > 5:
            raise ConfigError("上周 v3 baselineExport 代表证据无效")
        if len(raw_evidence) > count:
            raise ConfigError("上周 v3 baselineExport 代表证据超过分类计数")
        evidence = []
        for evidence_index, raw_item in enumerate(raw_evidence):
            if not isinstance(raw_item, dict) or set(raw_item) != {
                "evidenceId",
                "sourceKey",
                "title",
                "summary",
                "sourceUrl",
            }:
                raise ConfigError(
                    "上周 v3 baselineExport 代表证据结构无效："
                    f"{expected_category}[{evidence_index}]"
                )
            evidence_id = _text(
                raw_item.get("evidenceId"), "上周代表证据 evidenceId", limit=500
            )
            if evidence_id in evidence_ids:
                raise ConfigError("上周 v3 baselineExport 包含重复 evidenceId")
            evidence_ids.add(evidence_id)
            source = str(raw_item.get("sourceKey") or "").strip().casefold()
            if source not in SOURCE_ORDER:
                raise ConfigError("上周 v3 baselineExport 代表证据来源无效")
            evidence.append(
                {
                    "evidenceId": evidence_id,
                    "sourceKey": source,
                    "title": _text(
                        raw_item.get("title"), "上周代表证据 title", limit=1000
                    ),
                    "summary": _text(
                        raw_item.get("summary"), "上周代表证据 summary"
                    ),
                    "sourceUrl": _safe_url(
                        raw_item.get("sourceUrl"), "上周代表证据 sourceUrl"
                    ),
                }
            )
        normalized.append(
            {
                "businessCategory": expected_category,
                "count": count,
                "representativeEvidence": evidence,
            }
        )
    return normalized


def _validate_previous_analysis_artifact(payload, categories, review_count):
    if set(payload) != FINAL_ANALYSIS_KEYS:
        raise ConfigError("上周 analysis 不是完整 weekly-analysis v3 artifact")
    classifications = payload.get("classifications")
    if not isinstance(classifications, list) or not classifications:
        raise ConfigError("上周 analysis classifications 无效")
    counts = {category: 0 for category in BUSINESS_CATEGORIES}
    seen_ids = set()
    calculated_review_count = 0
    classifications_by_id = {}
    for index, item in enumerate(classifications):
        if not isinstance(item, dict) or set(item) != FINAL_CLASSIFICATION_KEYS:
            raise ConfigError(f"上周 analysis classifications[{index}] 结构无效")
        evidence_id = _text(
            item.get("evidenceId"),
            f"上周 analysis classifications[{index}].evidenceId",
            limit=500,
        )
        if evidence_id in seen_ids:
            raise ConfigError("上周 analysis classifications 包含重复 evidenceId")
        seen_ids.add(evidence_id)
        classifications_by_id[evidence_id] = item
        decision = item.get("decision")
        primary_category = item.get("primaryCategory")
        auxiliary = item.get("auxiliaryCategories")
        candidates = item.get("candidateCategories")
        if (
            not isinstance(auxiliary, list)
            or len(auxiliary) > 2
            or len(auxiliary) != len(set(auxiliary))
            or any(value not in AI_BUSINESS_CATEGORIES for value in auxiliary)
            or primary_category in auxiliary
            or not isinstance(candidates, list)
            or len(candidates) > 3
            or len(candidates) != len(set(candidates))
            or any(value not in BUSINESS_CATEGORIES for value in candidates)
            or item.get("confidence") not in ANALYSIS_CONFIDENCES
        ):
            raise ConfigError(f"上周 analysis classifications[{index}] 分类字段无效")
        _text(item.get("reason"), f"上周 analysis classifications[{index}].reason")
        source = item.get("classificationSource")
        metadata = item.get("reviewMetadata")
        if decision == "classified" and primary_category in counts:
            if candidates:
                raise ConfigError(f"上周 analysis classifications[{index}] 决策无效")
            if source == "ai":
                if primary_category == "others" or metadata is not None:
                    raise ConfigError("上周 analysis AI 分类身份无效")
            elif source == "human":
                if not isinstance(metadata, dict) or set(metadata) != {
                    "reviewedBy",
                    "reviewedAt",
                } or item.get("confidence") != "high":
                    raise ConfigError("上周 analysis 人工分类身份无效")
                _text(metadata.get("reviewedBy"), "上周 analysis reviewedBy")
                _date_time(metadata.get("reviewedAt"), "上周 analysis reviewedAt")
            else:
                raise ConfigError("上周 analysis classificationSource 无效")
            counts[primary_category] += 1
        elif (
            decision == "review"
            and primary_category is None
            and source == "ai"
            and metadata is None
            and not auxiliary
            and 1 <= len(candidates) <= 3
            and item.get("confidence") == "low"
        ):
            calculated_review_count += 1
        else:
            raise ConfigError(f"上周 analysis classifications[{index}] 决策无效")

    overview = payload.get("categoryOverview")
    if not isinstance(overview, list) or len(overview) != len(BUSINESS_CATEGORIES):
        raise ConfigError("上周 analysis categoryOverview 无效")
    for index, expected_category in enumerate(BUSINESS_CATEGORIES):
        item = overview[index]
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "businessCategory",
                "currentCount",
                "previousCount",
                "delta",
                "volumeTrend",
            }
            or item.get("businessCategory") != expected_category
        ):
            raise ConfigError("上周 analysis categoryOverview 分类顺序无效")
        if item.get("currentCount") != counts[expected_category]:
            raise ConfigError("上周 analysis categoryOverview 与 classifications 不一致")
        if categories[index]["count"] != counts[expected_category]:
            raise ConfigError("上周 analysis baselineExport 与 classifications 不一致")
        for evidence in categories[index]["representativeEvidence"]:
            classification = classifications_by_id.get(evidence["evidenceId"])
            if (
                not classification
                or classification["decision"] != "classified"
                or classification["primaryCategory"] != expected_category
                or evidence["evidenceId"].split(":", 1)[0]
                != evidence["sourceKey"]
            ):
                raise ConfigError("上周 analysis 代表证据与 classifications 不一致")

    queue = payload.get("reviewQueue")
    if not isinstance(queue, dict) or set(queue) != {"currentCount", "previousCount"}:
        raise ConfigError("上周 analysis reviewQueue 无效")
    if queue.get("currentCount") != calculated_review_count:
        raise ConfigError("上周 analysis reviewQueue 与 classifications 不一致")
    if review_count != calculated_review_count:
        raise ConfigError("上周 analysis baselineExport.reviewCount 与 classifications 不一致")

    assessments = payload.get("quickWinAssessments")
    if not isinstance(assessments, list) or len(assessments) != len(classifications):
        raise ConfigError("上周 analysis quickWinAssessments 覆盖无效")
    for index, (assessment, classification) in enumerate(
        zip(assessments, classifications)
    ):
        if not isinstance(assessment, dict) or set(assessment) != {
            "evidenceId",
            "criteria",
            "decision",
            "reason",
        }:
            raise ConfigError(f"上周 analysis quickWinAssessments[{index}] 结构无效")
        criteria = assessment.get("criteria")
        if (
            assessment.get("evidenceId") != classification["evidenceId"]
            or not isinstance(criteria, dict)
            or set(criteria) != {"clearNeed", "focusedScope", "estimatedSmallChange"}
            or any(not isinstance(value, bool) for value in criteria.values())
            or assessment.get("decision")
            != ("candidate" if all(criteria.values()) else "rejected")
            or (all(criteria.values()) and classification["decision"] != "classified")
        ):
            raise ConfigError(f"上周 analysis quickWinAssessments[{index}] 决策无效")
        _text(assessment.get("reason"), f"上周 analysis quickWinAssessments[{index}].reason")

    selected_ids = {
        item["evidenceId"]
        for item in assessments
        if item["decision"] == "candidate"
    }
    candidates = payload.get("quickWinCandidates")
    if not isinstance(candidates, list):
        raise ConfigError("上周 analysis quickWinCandidates 无效")
    used_ids = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != {
            "title",
            "summary",
            "businessCategory",
            "confidence",
            "whyQuickWin",
            "evidenceRefs",
        }:
            raise ConfigError(f"上周 analysis quickWinCandidates[{index}] 结构无效")
        category = candidate.get("businessCategory")
        if (
            category not in AI_BUSINESS_CATEGORIES
            or candidate.get("confidence") not in ANALYSIS_CONFIDENCES
        ):
            raise ConfigError(f"上周 analysis quickWinCandidates[{index}] 分类无效")
        for key in ("title", "summary", "whyQuickWin"):
            _text(
                candidate.get(key),
                f"上周 analysis quickWinCandidates[{index}].{key}",
            )
        refs = candidate.get("evidenceRefs")
        _validate_previous_evidence_refs(
            refs,
            f"上周 analysis quickWinCandidates[{index}].evidenceRefs",
            seen_ids,
            maximum=max(1, len(seen_ids)),
        )
        for ref in refs:
            evidence_id = ref["evidenceId"]
            classification = classifications_by_id[evidence_id]
            if (
                ref["period"] != "current"
                or evidence_id not in selected_ids
                or evidence_id in used_ids
                or category
                not in {
                    classification["primaryCategory"],
                    *classification["auxiliaryCategories"],
                }
            ):
                raise ConfigError(f"上周 analysis quickWinCandidates[{index}] 证据无效")
            used_ids.add(evidence_id)
    if used_ids != selected_ids:
        raise ConfigError("上周 analysis quickWinCandidates 覆盖无效")

    narrative_contracts = {
        "summary": ({"text", "confidence", "evidenceRefs"}, 1, 6),
        "themes": (
            {"name", "summary", "businessCategories", "confidence", "evidenceRefs"},
            1,
            12,
        ),
        "insights": (
            {"title", "observation", "whyItMatters", "confidence", "evidenceRefs"},
            1,
            10,
        ),
        "recommendations": (
            {"title", "action", "confidence", "evidenceRefs"},
            1,
            10,
        ),
    }
    for name, (keys, minimum, maximum) in narrative_contracts.items():
        values = payload.get(name)
        if not isinstance(values, list) or not minimum <= len(values) <= maximum:
            raise ConfigError(f"上周 analysis {name} 无效")
        for index, item in enumerate(values):
            if (
                not isinstance(item, dict)
                or set(item) != keys
                or item.get("confidence") not in ANALYSIS_CONFIDENCES
            ):
                raise ConfigError(f"上周 analysis {name}[{index}] 结构无效")
            for key in keys - {"confidence", "evidenceRefs", "businessCategories"}:
                _text(item.get(key), f"上周 analysis {name}[{index}].{key}")
            if name == "themes":
                business_categories = item.get("businessCategories")
                if (
                    not isinstance(business_categories, list)
                    or not 1 <= len(business_categories) <= 3
                    or len(business_categories) != len(set(business_categories))
                    or any(
                        category not in BUSINESS_CATEGORIES
                        for category in business_categories
                    )
                ):
                    raise ConfigError(f"上周 analysis {name}[{index}] 分类无效")
            _validate_previous_evidence_refs(
                item.get("evidenceRefs"),
                f"上周 analysis {name}[{index}].evidenceRefs",
                seen_ids,
            )
    _validate_previous_evidence_refs(
        payload.get("featuredEvidenceRefs"),
        "上周 analysis featuredEvidenceRefs",
        seen_ids,
        maximum=30,
    )
    expected_representatives = {
        category: [] for category in BUSINESS_CATEGORIES
    }
    for ref in payload["featuredEvidenceRefs"]:
        if ref["period"] != "current":
            continue
        classification = classifications_by_id[ref["evidenceId"]]
        if classification["decision"] != "classified":
            continue
        values = expected_representatives[classification["primaryCategory"]]
        if len(values) < 5:
            values.append(ref["evidenceId"])
    for category in categories:
        actual_ids = [
            item["evidenceId"] for item in category["representativeEvidence"]
        ]
        if actual_ids != expected_representatives[category["businessCategory"]]:
            raise ConfigError("上周 analysis 代表证据不是 featuredEvidenceRefs 确定性结果")

    comparison = payload.get("weekComparison")
    if not isinstance(comparison, dict) or set(comparison) != {
        "status",
        "headline",
        "improvements",
        "attentionItems",
    }:
        raise ConfigError("上周 analysis weekComparison 无效")
    _text(comparison.get("headline"), "上周 analysis weekComparison.headline")
    status = comparison.get("status")
    baseline = payload.get("comparisonBaseline")
    if not isinstance(baseline, dict) or set(baseline) != {
        "status",
        "reason",
        "analysisArtifactId",
    }:
        raise ConfigError("上周 analysis comparisonBaseline 无效")
    if status not in {"available", "unavailable"} or baseline.get("status") != status:
        raise ConfigError("上周 analysis comparisonBaseline 状态不一致")
    previous_review_count = queue.get("previousCount")
    if status == "unavailable":
        if previous_review_count is not None:
            raise ConfigError("上周 analysis reviewQueue.previousCount 无效")
    elif (
        not isinstance(previous_review_count, int)
        or isinstance(previous_review_count, bool)
        or previous_review_count < 0
    ):
        raise ConfigError("上周 analysis reviewQueue.previousCount 无效")
    _text(baseline.get("reason"), "上周 analysis comparisonBaseline.reason")
    for key in ("improvements", "attentionItems"):
        values = comparison.get(key)
        if not isinstance(values, list) or len(values) > 7:
            raise ConfigError(f"上周 analysis weekComparison.{key} 无效")
        if status == "unavailable" and values:
            raise ConfigError("上周 analysis 无基线时不能包含周环比结论")
        for index, item in enumerate(values):
            if not isinstance(item, dict) or set(item) != {
                "businessCategory",
                "title",
                "summary",
                "confidence",
                "evidenceRefs",
            }:
                raise ConfigError(f"上周 analysis weekComparison.{key}[{index}] 无效")
            if (
                item.get("businessCategory") not in BUSINESS_CATEGORIES
                or item.get("confidence") not in ANALYSIS_CONFIDENCES
            ):
                raise ConfigError(f"上周 analysis weekComparison.{key}[{index}] 无效")
            _text(item.get("title"), f"上周 analysis weekComparison.{key}.title")
            _text(item.get("summary"), f"上周 analysis weekComparison.{key}.summary")
            _validate_previous_evidence_refs(
                item.get("evidenceRefs"),
                f"上周 analysis weekComparison.{key}[{index}].evidenceRefs",
                seen_ids,
                minimum=2,
            )
            periods = {ref["period"] for ref in item["evidenceRefs"]}
            if periods != {"current", "previous"}:
                raise ConfigError(
                    f"上周 analysis weekComparison.{key}[{index}] 缺少跨周证据"
                )
            for ref in item["evidenceRefs"]:
                if ref["period"] != "current":
                    continue
                classification = classifications_by_id[ref["evidenceId"]]
                if item["businessCategory"] not in {
                    classification["primaryCategory"],
                    *classification["auxiliaryCategories"],
                }:
                    raise ConfigError(
                        f"上周 analysis weekComparison.{key}[{index}] 分类不一致"
                    )
    if status == "unavailable":
        if payload.get("comparisonPeriod") is not None or baseline.get(
            "analysisArtifactId"
        ) is not None:
            raise ConfigError("上周 analysis 无基线身份无效")
    else:
        _comparison_start, comparison_end = _period(
            payload.get("comparisonPeriod"), "上周 analysis comparisonPeriod"
        )
        current_start, _current_end = _period(
            payload.get("currentPeriod"), "上周 analysis currentPeriod"
        )
        if comparison_end + timedelta(days=1) != current_start:
            raise ConfigError("上周 analysis comparisonPeriod 不是紧邻周期")
        _text(
            baseline.get("analysisArtifactId"),
            "上周 analysis comparisonBaseline.analysisArtifactId",
            limit=500,
        )

    for item in overview:
        previous_count = item["previousCount"]
        delta = item["delta"]
        trend = item["volumeTrend"]
        if status == "unavailable":
            if previous_count is not None or delta is not None or trend != "not-comparable":
                raise ConfigError("上周 analysis categoryOverview 不可比字段无效")
            continue
        if (
            not isinstance(previous_count, int)
            or isinstance(previous_count, bool)
            or previous_count < 0
            or delta != item["currentCount"] - previous_count
        ):
            raise ConfigError("上周 analysis categoryOverview 环比派生字段无效")
        if delta > 0:
            expected_trend = "up"
        elif delta < 0:
            expected_trend = "down"
        else:
            expected_trend = "flat"
        if trend != expected_trend:
            raise ConfigError("上周 analysis categoryOverview 趋势字段无效")


def _validate_previous_evidence_refs(
    value, label, current_ids, *, minimum=1, maximum=20
):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ConfigError(f"{label} 无效")
    identities = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"period", "evidenceId"}:
            raise ConfigError(f"{label} 结构无效")
        period = item.get("period")
        evidence_id = _text(item.get("evidenceId"), f"{label}.evidenceId", limit=500)
        if period not in {"current", "previous"}:
            raise ConfigError(f"{label} 周期无效")
        if period == "current" and evidence_id not in current_ids:
            raise ConfigError(f"{label} 引用了未知本周证据")
        identities.append((period, evidence_id))
    if len(identities) != len(set(identities)):
        raise ConfigError(f"{label} 包含重复引用")


def load_previous_analysis_baseline(path, *, current_start, scope):
    if not path:
        return _unavailable_baseline("未提供 --previous-analysis")
    payload = _load_json(path, "上周 weekly-analysis v3")
    if payload.get("schemaVersion") != 3:
        raise ConfigError("上周 analysis schemaVersion 必须为 3")
    if payload.get("analysisRule") not in {
        WEEKLY_ANALYSIS_RULE_VERSION,
        *LEGACY_WEEKLY_ANALYSIS_RULE_VERSIONS,
    }:
        raise ConfigError("上周 analysis analysisRule 不匹配")
    export = payload.get("baselineExport")
    if not isinstance(export, dict) or set(export) != {
        "artifactId",
        "period",
        "scope",
        "categories",
        "reviewCount",
    }:
        raise ConfigError("上周 analysis 缺少有效 baselineExport")
    start, end = _period(export.get("period"), "上周 baselineExport.period")
    exported_scope = _text(export.get("scope"), "上周 baselineExport.scope", limit=300)
    artifact_id = _text(
        export.get("artifactId"), "上周 baselineExport.artifactId", limit=500
    )
    categories = _baseline_categories(export.get("categories"))
    review_count = export.get("reviewCount")
    if (
        not isinstance(review_count, int)
        or isinstance(review_count, bool)
        or review_count < 0
    ):
        raise ConfigError("上周 baselineExport.reviewCount 无效")
    _validate_previous_analysis_artifact(payload, categories, review_count)
    if payload.get("currentPeriod") != export.get("period"):
        raise ConfigError("上周 analysis currentPeriod 与 baselineExport 不一致")
    if str(payload.get("scope") or "").strip().casefold() != exported_scope.casefold():
        raise ConfigError("上周 analysis scope 与 baselineExport 不一致")
    if exported_scope.casefold() != str(scope).strip().casefold():
        return _unavailable_baseline("上周已发布 v3 scope 与本周不一致")
    if end + timedelta(days=1) != current_start:
        return _unavailable_baseline("上周已发布 v3 不是紧邻本周的自然周")
    return {
        "status": "available",
        "reason": "读取紧邻上周已经校验并发布的 weekly-analysis v3 artifact",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "artifactId": artifact_id,
        "schemaVersion": 3,
        "scope": exported_scope,
        "categories": categories,
        "reviewCount": review_count,
    }


def _manifest_map(manifest_paths):
    manifests = {}
    for path in manifest_paths:
        manifest = _load_json(path, "采集 manifest")
        source = str(manifest.get("sourceKey") or "").strip().casefold()
        if source not in SOURCE_ORDER:
            raise BusinessError(f"AI 分析输入不支持的数据源：{source or 'unknown'}")
        if source in manifests:
            raise ConfigError(f"AI 分析输入包含重复数据源：{source}")
        manifests[source] = manifest
    missing = [source for source in SOURCE_ORDER if source not in manifests]
    if missing:
        raise ConfigError("AI 分析输入必须包含四个来源，当前缺少：" + ", ".join(missing))
    return manifests


def _normalized_input_record(item):
    record = {
        "evidenceId": _text(item.get("evidenceId"), "evidenceId", limit=500),
        "sourceKey": str(item.get("sourceKey") or "").strip().casefold(),
        "sourceObjectId": _text(
            item.get("sourceObjectId"), "sourceObjectId", limit=500
        ),
        "title": _text(item.get("title"), "title", limit=1000),
        "normalizedText": _text(
            item.get("normalizedText"), "normalizedText", limit=5000
        ),
        "sourceCategory": _text(
            item.get("category"), "sourceCategory", limit=300
        ),
        "createdAt": _text(item.get("createdAt"), "createdAt", limit=100),
        "sourceUrl": _safe_url(item.get("sourceUrl"), "sourceUrl"),
        "contextTags": item.get("contextTags"),
    }
    if record["sourceKey"] not in SOURCE_ORDER:
        raise BusinessError("AI 分析输入 evidence 来源无效")
    try:
        datetime.fromisoformat(record["createdAt"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise BusinessError("AI 分析输入 evidence createdAt 无效") from exc
    context_tags = record["contextTags"]
    if (
        not isinstance(context_tags, list)
        or len(context_tags) > 20
        or any(
            not isinstance(value, str) or not value.strip() or len(value) > 100
            for value in context_tags
        )
        or len(context_tags) != len(set(context_tags))
    ):
        raise BusinessError("AI 分析输入 evidence contextTags 无效")
    return record


def build_weekly_analysis_input(
    manifest_paths,
    *,
    squad,
    domain,
    start,
    end,
    scope,
    previous_analysis="",
):
    manifests = _manifest_map(manifest_paths)
    snapshot = build_dashboard_snapshot(
        manifest_paths,
        squad=squad,
        domain=domain,
        start=start,
        end=end,
        require_quick_win_review=False,
        include_analysis_fields=True,
    )
    if snapshot["missingSources"]:
        raise ConfigError(
            "AI 分析输入必须包含四个来源，当前缺少："
            + ", ".join(snapshot["missingSources"])
        )
    records = [_normalized_input_record(item) for item in snapshot["records"]]
    if not records:
        raise BusinessError("本周四源没有可供 AI 分析的入选反馈")
    evidence_ids = [item["evidenceId"] for item in records]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise BusinessError("AI 分析输入包含重复 evidenceId")
    summaries = {item["sourceKey"]: item for item in snapshot["sources"]}
    source_runs = []
    for source in SOURCE_ORDER:
        manifest = manifests[source]
        summary = summaries[source]
        run_id = _text(manifest.get("runId"), f"{source} runId", limit=500)
        if manifest.get("status") != "succeeded":
            raise BusinessError(f"{source} manifest 状态不是 succeeded")
        source_runs.append(
            {
                "sourceKey": source,
                "runId": run_id,
                "status": "succeeded",
                "coverage": _text(
                    summary.get("coverage"), f"{source} coverage", limit=1000
                ),
                "selectionRuleVersion": SOURCE_SELECTION_RULES[source],
                "includedCount": int(summary.get("included") or 0),
            }
        )
    return {
        "schemaVersion": ANALYSIS_INPUT_SCHEMA_VERSION,
        "analysisRule": WEEKLY_ANALYSIS_RULE_VERSION,
        "scope": _text(scope, "scope", limit=300),
        "currentPeriod": {"start": start.isoformat(), "end": end.isoformat()},
        "currentSourceRuns": source_runs,
        "records": records,
        "previousBaseline": load_previous_analysis_baseline(
            previous_analysis,
            current_start=start,
            scope=scope,
        ),
    }
