import os
import shutil

from ..lark import resolve_wiki


def register(subparsers):
    parser = subparsers.add_parser("doctor", help="检查采集运行依赖和控制页")
    parser.set_defaults(_handler=run)


def run(_args, config):
    config.output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config.output_root, 0o700)
    agent_browser = shutil.which(config.agent_browser) or (
        config.agent_browser if os.path.isfile(config.agent_browser) else ""
    )
    lark_cli = shutil.which(config.lark_cli) or (
        config.lark_cli if os.path.isfile(config.lark_cli) else ""
    )
    wiki = resolve_wiki(config) if lark_cli else None
    canny_ready = bool(agent_browser and config.moe_mis_script)
    intercom_ready = bool(config.datadog_script)
    jira_ready = bool(config.jira_script)
    facebook_ready = bool(config.slack_script and config.facebook_slack_channel)
    shared_ready = bool(lark_cli and wiki) and os.access(config.output_root, os.W_OK)
    checks = {
        "agentBrowser": bool(agent_browser),
        "larkCli": bool(lark_cli),
        "capabilitiesSchemaVersion": 2,
        "moeMis": bool(config.moe_mis_script),
        "moeMisWorkdir": bool(config.moe_mis_workdir),
        "internalOps": bool(config.moe_mis_script),
        "internalOpsWorkdir": bool(config.moe_mis_workdir),
        "datadogSkill": bool(config.datadog_script),
        "slackSkill": bool(config.slack_script),
        "squadConfigured": bool(config.squad),
        "outputWritable": os.access(config.output_root, os.W_OK),
        "wikiResolved": bool(wiki),
    }
    return {
        "ok": bool(
            shared_ready
            and (canny_ready or intercom_ready or jira_ready or facebook_ready)
        ),
        "checks": checks,
        "wiki": wiki,
        "larkWeeklyPublishEnabled": bool(lark_cli and wiki),
        "sources": {
            "canny": canny_ready,
            "intercom": intercom_ready,
            "jira": jira_ready,
            "facebook": facebook_ready,
        },
        "intercomPublish": {
            "enabled": bool(
                config.datadog_script and config.squad and lark_cli
            ),
            "squad": config.squad or None,
        },
        "jiraPublish": {
            "enabled": bool(config.jira_script and config.squad and lark_cli),
            "squad": config.squad or None,
        },
        "next": "按 source 执行 collect；Jira 采集与 Jira/Intercom 发布需要 MFC_SQUAD",
    }
