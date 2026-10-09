import uuid
from datetime import datetime, timezone

from ..canny import BrowserTransport, CannyCollector, FixtureTransport
from ..errors import ConfigError
from ..facebook import (
    FacebookCollector,
    SlackTransport,
)
from ..facebook import (
    FixtureTransport as FacebookFixtureTransport,
)
from ..intercom import (
    DatadogTransport,
    IntercomCollector,
)
from ..intercom import (
    FixtureTransport as IntercomFixtureTransport,
)
from ..jira import (
    JIRA_PRIVACY_POLICY,
    JIRA_SELECTION_RULE_VERSION,
    JiraCollector,
    JiraTransport,
)
from ..jira import (
    FixtureTransport as JiraFixtureTransport,
)
from ..report import parse_period
from ..store import LocalStore


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def register(subparsers):
    parser = subparsers.add_parser("collect", help="采集需求反馈信息源")
    parser.add_argument(
        "--source", required=True, choices=["canny", "intercom", "jira", "facebook"]
    )
    parser.add_argument(
        "--mode", choices=["probe", "incremental", "full", "period"], default=None
    )
    parser.add_argument("--sink", choices=["local"], default="local")
    parser.add_argument("--account-ref", default="", help="内部测试账号 aid:<id>")
    parser.add_argument("--headed", action="store_true", help="显示浏览器，便于调试")
    parser.add_argument("--fixture", default="", help="离线 fixture JSON")
    parser.add_argument("--period-start", default="", help="周期开始 YYYY-MM-DD")
    parser.add_argument("--period-end", default="", help="周期结束 YYYY-MM-DD")
    parser.add_argument(
        "--allow-partial-period",
        action="store_true",
        help="允许周一开始、同一自然周内少于 7 天的周期",
    )
    parser.add_argument(
        "--month-segment",
        default="",
        help="允许目标自然月与所在 ISO 周的精确边界交集，格式 YYYY-MM",
    )
    parser.set_defaults(_handler=run)


def _run_canny(args, config):
    mode = args.mode or "incremental"
    if mode not in {"probe", "incremental", "full"}:
        raise ConfigError("Canny collect 不支持 --mode period")
    start, end = parse_period(
        args.period_start,
        args.period_end,
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    account_ref = args.account_ref
    transport = (
        FixtureTransport(args.fixture)
        if args.fixture
        else BrowserTransport(config, headed=args.headed)
    )
    store = LocalStore(config.output_root)
    lock = store.acquire_source_lock("canny")
    run_id = f"canny-{uuid.uuid4().hex}"
    started_at = _now()
    try:
        checkpoint = (
            {"schemaVersion": 1, "sourceKey": "canny", "posts": {}}
            if mode == "probe"
            else store.load_checkpoint("canny")
        )
        transport.start()
        auth = transport.ensure_authenticated(account_ref)
        collector = CannyCollector(
            transport,
            board_url=config.canny_board_url,
            min_vote=config.min_vote,
            page_cap=config.page_cap,
        )
        result = collector.collect(
            checkpoint,
            mode,
            period_start=start,
            period_end=end,
        )
        finished_at = _now()
        manifest = {
            "schemaVersion": 1,
            "collectorVersion": "0.1.0",
            "runId": run_id,
            "sourceKey": "canny",
            "mode": mode,
            "status": "succeeded",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "fetchedCount": result["observed"],
            "baseline": result["baseline"],
            "baselineCount": result["baselineCount"],
            "newCount": result["newCount"],
            "changedCount": result["changedCount"],
            "checkpointDiscoveredCount": result["discoveredCount"],
            "snapshotChangedCount": result["snapshotChangedCount"],
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "authMethod": auth["method"],
        }
        manifest_path, saved = store.save_run(
            "canny",
            run_id,
            manifest,
            result["evidence"],
            result["checkpoint"],
            result["reportRows"],
        )
        sample = [
            {
                "evidenceId": item["evidenceId"],
                "title": item["title"],
                "voteCount": item["voteCount"],
                "commentCount": item["commentCount"],
                "status": item["status"],
                "sourceUrl": item["sourceUrl"],
            }
            for item in result["evidence"][:3]
        ]
        return {
            "ok": True,
            "runId": run_id,
            "source": "canny",
            "mode": mode,
            "counts": {
                "fetched": result["observed"],
                "baseline": result["baselineCount"],
                "new": result["newCount"],
                "changed": result["changedCount"],
                "checkpointDiscovered": result["discoveredCount"],
                "snapshotChanged": result["snapshotChangedCount"],
                "sourceRows": len(result["evidence"]),
                "reportRows": len(result["reportRows"]),
            },
            "sample": sample,
            "manifest": manifest_path,
            "checkpoint": saved["checkpointArtifact"],
        }
    finally:
        transport.close()
        store.release_source_lock(lock)


def _run_intercom(args, config):
    mode = args.mode or "period"
    if mode not in {"probe", "period"}:
        raise ConfigError("Intercom collect 只支持 --mode period|probe")
    if args.account_ref or args.headed:
        raise ConfigError("Intercom collect 不接受 Canny 登录参数")
    start, end = parse_period(
        args.period_start,
        args.period_end,
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    transport = (
        IntercomFixtureTransport(args.fixture)
        if args.fixture
        else DatadogTransport(config)
    )
    store = LocalStore(config.output_root)
    lock = store.acquire_source_lock("intercom")
    run_id = f"intercom-{uuid.uuid4().hex}"
    started_at = _now()
    try:
        result = IntercomCollector(transport).collect(
            start,
            end,
            probe=mode == "probe",
        )
        finished_at = _now()
        manifest = {
            "schemaVersion": 1,
            "collectorVersion": "0.2.0",
            "runId": run_id,
            "sourceKey": "intercom",
            "mode": mode,
            "status": "succeeded",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "fetchedCount": result["observed"],
            "baseline": False,
            "baselineCount": 0,
            "newCount": result["observed"],
            "changedCount": 0,
            "period": result["period"],
            "transport": "datadog-skill" if not args.fixture else "fixture",
            "privacyPolicy": "intercom-safe-v1",
        }
        manifest_path, _saved = store.save_run(
            "intercom",
            run_id,
            manifest,
            result["evidence"],
            None,
            result["reportRows"],
        )
        sample = [
            {
                "evidenceId": item["evidenceId"],
                "requirement": item["requirement"],
                "domain": item["domain"],
                "feedbackType": item["feedbackType"],
                "sentiment": item["sentiment"],
                "squad": item["squad"],
                "createdAt": item["createdAt"],
            }
            for item in result["evidence"][:3]
        ]
        return {
            "ok": True,
            "runId": run_id,
            "source": "intercom",
            "mode": mode,
            "period": result["period"],
            "counts": {
                "fetched": result["observed"],
                "sourceRows": len(result["evidence"]),
                "reportRows": len(result["reportRows"]),
            },
            "sample": sample,
            "manifest": manifest_path,
        }
    finally:
        store.release_source_lock(lock)


def _run_jira(args, config):
    mode = args.mode or "period"
    if mode != "period":
        raise ConfigError("Jira collect 只支持 --mode period")
    if args.account_ref or args.headed:
        raise ConfigError("Jira collect 不接受 Canny 登录参数")
    if not config.squad:
        raise ConfigError("缺少 MFC_SQUAD，无法采集 Jira 团队反馈")
    start, end = parse_period(
        args.period_start,
        args.period_end,
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    transport = (
        JiraFixtureTransport(args.fixture)
        if args.fixture
        else JiraTransport(config)
    )
    store = LocalStore(config.output_root)
    lock = store.acquire_source_lock("jira")
    run_id = f"jira-{uuid.uuid4().hex}"
    started_at = _now()
    try:
        result = JiraCollector(transport).collect(start, end, config.squad)
        finished_at = _now()
        manifest = {
            "schemaVersion": 1,
            "collectorVersion": "0.3.0",
            "runId": run_id,
            "sourceKey": "jira",
            "mode": mode,
            "status": "succeeded",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "fetchedCount": result["selected"],
            "observedCount": result["observed"],
            "inPeriodCount": result["inPeriod"],
            "baseline": False,
            "baselineCount": 0,
            "newCount": result["selected"],
            "changedCount": 0,
            "period": result["period"],
            "squad": config.squad,
            "query": result["query"],
            "transport": "jira-skill" if not args.fixture else "fixture",
            "privacyPolicy": JIRA_PRIVACY_POLICY,
            "selectionRule": JIRA_SELECTION_RULE_VERSION,
            "feedbackCandidateCount": result["feedbackCandidates"],
            "manualReviewCount": result["manualReview"],
            "excludedScopeCount": result["excludedScope"],
        }
        manifest_path, _saved = store.save_run(
            "jira",
            run_id,
            manifest,
            result["evidence"],
            None,
            result["reportRows"],
        )
        sample = [
            {
                "evidenceId": item["evidenceId"],
                "sourceObjectId": item["sourceObjectId"],
                "title": item["title"],
                "issueType": item["issueType"],
                "feedbackKinds": item["feedbackKinds"],
                "scopeReasons": item["scopeReasons"],
                "businessCategory": item["businessCategory"],
                "classificationConfidence": item["classificationConfidence"],
                "createdAt": item["createdAt"],
            }
            for item in result["evidence"][:3]
        ]
        return {
            "ok": True,
            "runId": run_id,
            "source": "jira",
            "mode": mode,
            "period": result["period"],
            "squad": config.squad,
            "counts": {
                "observed": result["observed"],
                "inPeriod": result["inPeriod"],
                "selected": result["selected"],
                "featureRequest": result["featureRequest"],
                "designLinked": result["designLinked"],
                "feedbackCandidates": result["feedbackCandidates"],
                "manualReview": result["manualReview"],
                "excludedScope": result["excludedScope"],
                "sourceRows": len(result["evidence"]),
                "reportRows": len(result["reportRows"]),
            },
            "sample": sample,
            "manifest": manifest_path,
        }
    finally:
        store.release_source_lock(lock)


def _run_facebook(args, config):
    mode = args.mode or "period"
    if mode not in {"probe", "period"}:
        raise ConfigError("Facebook collect 只支持 --mode period|probe")
    if args.account_ref or args.headed:
        raise ConfigError("Facebook collect 不接受 Canny 登录参数")
    start, end = parse_period(
        args.period_start,
        args.period_end,
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    transport = (
        FacebookFixtureTransport(args.fixture)
        if args.fixture
        else SlackTransport(config)
    )
    store = LocalStore(config.output_root)
    lock = store.acquire_source_lock("facebook")
    run_id = f"facebook-{uuid.uuid4().hex}"
    started_at = _now()
    try:
        result = FacebookCollector(
            transport,
            channel_id=config.facebook_slack_channel,
            domain=config.feedback_domain,
        ).collect(start, end, probe=mode == "probe")
        finished_at = _now()
        manifest = {
            "schemaVersion": 1,
            "collectorVersion": "0.4.0",
            "runId": run_id,
            "sourceKey": "facebook",
            "mode": mode,
            "status": "succeeded",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "fetchedCount": result["observed"],
            "baseline": False,
            "baselineCount": 0,
            "newCount": len(result["evidence"]),
            "changedCount": 0,
            "period": result["period"],
            "transport": "slack-skill" if not args.fixture else "fixture",
            "domain": config.feedback_domain,
            "coverage": "channel-summary",
            "privacyPolicy": "facebook-slack-safe-v1",
        }
        manifest_path, _saved = store.save_run(
            "facebook",
            run_id,
            manifest,
            result["evidence"],
            None,
            result["reportRows"],
        )
        sample = [
            {
                "evidenceId": item["evidenceId"],
                "feedType": item["feedType"],
                "title": item["title"],
                "domain": item["domain"],
                "createdAt": item["createdAt"],
                "slackUrl": item["slackUrl"],
            }
            for item in result["evidence"][:3]
        ]
        return {
            "ok": True,
            "runId": run_id,
            "source": "facebook",
            "mode": mode,
            "period": result["period"],
            "domain": config.feedback_domain,
            "coverage": "channel-summary",
            "counts": {
                "fetched": result["observed"],
                "accepted": len(result["evidence"]),
                "skipped": result["skipped"],
                "feeds": result["feedCounts"],
                "reportRows": len(result["reportRows"]),
            },
            "sample": sample,
            "manifest": manifest_path,
        }
    finally:
        store.release_source_lock(lock)


def run(args, config):
    if args.source == "jira":
        return _run_jira(args, config)
    if args.source == "intercom":
        return _run_intercom(args, config)
    if args.source == "facebook":
        return _run_facebook(args, config)
    return _run_canny(args, config)
