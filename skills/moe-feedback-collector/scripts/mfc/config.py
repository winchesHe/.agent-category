from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .errors import ConfigError

DEFAULT_WIKI_URL = "https://mengshikeji.feishu.cn/wiki/OjbbwLwfPikMF7kQBPWcEE0Lnjb"
DEFAULT_CANNY_URL = "https://moego.canny.io/feature-request"
DEFAULT_INTERCOM_DATASTORE_ID = "a56cf9ac-2d2d-4e72-b19a-f9f0107868aa"
DEFAULT_FACEBOOK_SLACK_CHANNEL = "C0BEL8Y0Y74"
DEFAULT_FEEDBACK_DOMAIN = "grooming"
SQUAD_ENV = "MFC_SQUAD"
DEFAULT_MIN_VOTE = 3
DEFAULT_PAGE_CAP = 32
DEFAULT_OUTPUT_ROOT = "~/.moe-feedback-collector"
DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class Config:
    skill_root: Path
    wiki_url: str
    canny_board_url: str
    min_vote: int
    page_cap: int
    output_root: Path
    moe_mis_script: Path | None
    moe_mis_workdir: Path | None
    datadog_script: Path | None
    jira_script: Path | None
    slack_script: Path | None
    facebook_slack_channel: str
    feedback_domain: str
    squad: str
    agent_browser: str
    lark_cli: str
    timeout: float


    @property
    def internal_ops_script(self):
        """兼容旧调用方；新代码应使用 moe_mis_script。"""
        return self.moe_mis_script

    @property
    def internal_ops_workdir(self):
        """兼容旧调用方；新代码应使用 moe_mis_workdir。"""
        return self.moe_mis_workdir


def _find_moe_mis(skill_root):
    configured = os.environ.get("MOE_MIS_SKILL")
    if configured:
        candidates = [Path(configured).expanduser() / "scripts" / "moe_mis.py"]
    else:
        candidates = [
            skill_root.parent / "moe-mis" / "scripts" / "moe_mis.py",
            Path.home() / ".codex/skills/moe-mis/scripts/moe_mis.py",
            Path.home() / ".agents/skills/moe-mis/scripts/moe_mis.py",
        ]
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        root = resolved.parents[1]
        skill_file = root / "SKILL.md"
        try:
            contents = skill_file.read_text(encoding="utf-8")
        except OSError:
            continue
        parts = contents.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            continue
        frontmatter = parts[1]
        if any(line.strip() == "name: moe-mis" for line in frontmatter.splitlines()):
            return resolved
    if configured:
        raise ConfigError("MOE_MIS_SKILL 未指向有效的 moe-mis Skill 根目录")
    return None


def _find_moe_mis_workdir(script):
    return script.parents[1] if script else None


def _find_datadog(skill_root):
    candidates = [
        skill_root.parent / "datadog" / "scripts" / "datadog.py",
        Path.home() / ".codex/skills/datadog/scripts/datadog.py",
        Path.home() / ".agents/skills/datadog/scripts/datadog.py",
    ]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _find_jira(skill_root):
    candidates = [
        skill_root.parent / "jira" / "scripts" / "jira.py",
        Path.home() / ".codex/skills/jira/scripts/jira.py",
        Path.home() / ".agents/skills/jira/scripts/jira.py",
    ]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _find_slack(skill_root):
    candidates = [
        skill_root.parent / "slack" / "scripts" / "slack.py",
        Path.home() / ".codex/skills/slack/scripts/slack.py",
        Path.home() / ".agents/skills/slack/scripts/slack.py",
    ]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _validate_url(value, expected_host, label):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise ConfigError(f"{label} 必须是 https://{expected_host}/ 下的 URL")


def _validate_wiki_url(value):
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not (
        host.endswith(".feishu.cn") or host.endswith(".larksuite.com")
    ):
        raise ConfigError("MFC_LARK_WIKI_URL 必须是 Feishu/Lark HTTPS Wiki URL")


def _validate_squad(value):
    if len(value) > 200 or any(character in value for character in "\r\n\x00"):
        raise ConfigError(f"{SQUAD_ENV} 必须是 200 字符以内的单行文本")


def _validate_feedback_domain(value):
    if not value or len(value) > 200 or any(
        character in value for character in "\r\n\x00"
    ):
        raise ConfigError("MFC_DOMAIN 必须是 200 字符以内的非空单行文本")


def load_config(*, wiki_url=None, output_root=None):
    skill_root = Path(__file__).resolve().parents[2]
    env_values = {}
    for path in (skill_root / ".env", Path.cwd() / ".env"):
        if path.exists():
            values = dotenv_values(path)
            for key in (
                "MFC_LARK_WIKI_URL",
                SQUAD_ENV,
                "MFC_FACEBOOK_SLACK_CHANNEL",
                "MFC_DOMAIN",
            ):
                if key in values:
                    env_values[key] = values[key]
    for key in (
        "MFC_LARK_WIKI_URL",
        SQUAD_ENV,
        "MFC_FACEBOOK_SLACK_CHANNEL",
        "MFC_DOMAIN",
    ):
        if key in os.environ:
            env_values[key] = os.environ[key]

    wiki = (
        wiki_url
        if wiki_url is not None
        else env_values.get("MFC_LARK_WIKI_URL", DEFAULT_WIKI_URL)
    )
    squad = str(env_values.get(SQUAD_ENV) or "").strip()
    facebook_slack_channel = str(
        env_values.get("MFC_FACEBOOK_SLACK_CHANNEL", DEFAULT_FACEBOOK_SLACK_CHANNEL)
        or ""
    ).strip()
    feedback_domain = str(
        env_values.get("MFC_DOMAIN", DEFAULT_FEEDBACK_DOMAIN) or ""
    ).strip()
    _validate_wiki_url(wiki)
    _validate_squad(squad)
    if not re.fullmatch(r"C[A-Z0-9]+", facebook_slack_channel):
        raise ConfigError("MFC_FACEBOOK_SLACK_CHANNEL 必须是 Slack 频道 ID")
    _validate_feedback_domain(feedback_domain)
    _validate_url(DEFAULT_CANNY_URL, "moego.canny.io", "Canny Board URL")

    script = _find_moe_mis(skill_root)
    workdir = _find_moe_mis_workdir(script)
    datadog_script = _find_datadog(skill_root)
    jira_script = _find_jira(skill_root)
    slack_script = _find_slack(skill_root)
    agent_browser = "agent-browser"
    lark_cli = "lark-cli"
    if "/" not in agent_browser:
        agent_browser = shutil.which(agent_browser) or agent_browser
    if "/" not in lark_cli:
        lark_cli = shutil.which(lark_cli) or lark_cli
    root_value = output_root or DEFAULT_OUTPUT_ROOT
    return Config(
        skill_root=skill_root,
        wiki_url=wiki,
        canny_board_url=DEFAULT_CANNY_URL,
        min_vote=DEFAULT_MIN_VOTE,
        page_cap=DEFAULT_PAGE_CAP,
        output_root=Path(root_value).expanduser().resolve(),
        moe_mis_script=script,
        moe_mis_workdir=workdir,
        datadog_script=datadog_script,
        jira_script=jira_script,
        slack_script=slack_script,
        facebook_slack_channel=facebook_slack_channel,
        feedback_domain=feedback_domain,
        squad=squad,
        agent_browser=agent_browser,
        lark_cli=lark_cli,
        timeout=DEFAULT_TIMEOUT,
    )
