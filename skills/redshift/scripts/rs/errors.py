"""Stable public error contract for the Redshift CLI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


EXIT_BY_CATEGORY = {
    "usage": 2,
    "config": 3,
    "safety": 4,
    "connection": 5,
    "capability": 5,
    "catalog": 6,
    "metadata": 6,
    "query": 7,
    "output": 8,
    "internal": 8,
    "control": 1,
}


_AGENT_ACTION_BY_ERROR = {
    "config.connection_not_found": "list_connections",
    "connection.aws_credentials_unavailable": "configure_aws_credentials",
    "connection.auth_interaction_required": "refresh_aws_auth",
    "connection.permission_denied": "request_platform_access",
    "connection.target_not_found": "select_connection",
    "connection.secret_unavailable": "configure_secret",
    "connection.auth_failed": "verify_aws_identity",
    "connection.endpoint_unreachable": "check_network_path",
    "connection.unavailable": "retry_connection",
    "capability.parameter_shape_unavailable": "simplify_parameters",
    "capability.readonly_unavailable": "fix_readonly_role",
    "capability.transport_unavailable": "select_supported_transport",
    "capability.auth_mode_unavailable": "select_supported_auth_mode",
    "capability.cross_database_read_unavailable": "use_single_database_or_recipe",
    "capability.recipe_source_unavailable": "select_connection",
    "query.permission_denied": "request_data_access",
    "metadata.permission_denied": "request_data_access",
    "metadata.failed": "inspect_provider_failure",
}


@dataclass(eq=False)
class SkillError(Exception):
    """An expected failure safe to expose through the public JSON envelope."""

    category: str
    code: str
    retry_class: str
    message: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    suggestion: str | None = None
    exit_code_override: int | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, f"{self.category}.{self.code}")
        if self.suggestion is None:
            self.suggestion = _AGENT_ACTION_BY_ERROR.get(self.full_code)

    @property
    def exit_code(self) -> int:
        if self.exit_code_override is not None:
            return self.exit_code_override
        return EXIT_BY_CATEGORY.get(self.category, 8)

    @property
    def full_code(self) -> str:
        return f"{self.category}.{self.code}"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self.category,
            "code": self.code,
            "retryClass": self.retry_class,
        }
        if self.message:
            payload["message"] = self.message
        if self.details:
            payload["details"] = dict(self.details)
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload


class Interrupted(SkillError):
    """A captured process-control signal; signal handlers perform no I/O."""

    def __init__(self, signum: int, details: Mapping[str, Any] | None = None) -> None:
        exit_code = 130 if signum == 2 else 143 if signum == 15 else 128 + signum
        super().__init__(
            category="control",
            code="interrupted",
            retry_class="never",
            details=details or {},
            exit_code_override=exit_code,
        )
        self.signum = signum


def usage_error(
    code: str,
    *,
    details: Mapping[str, Any] | None = None,
    suggestion: str | None = None,
) -> SkillError:
    return SkillError(
        category="usage",
        code=code,
        retry_class="after_change",
        details=details or {},
        suggestion=suggestion,
    )


def config_error(code: str, *, key: str | None = None) -> SkillError:
    details = {"key": key} if key else {}
    return SkillError(
        category="config",
        code=code,
        retry_class="after_change",
        details=details,
    )


def output_error(
    code: str,
    *,
    retry_class: str | None = None,
    suggestion: str | None = None,
) -> SkillError:
    if retry_class is None:
        retry_class = {
            "path_not_allowed": "after_change",
            "already_exists": "after_change",
            "write_failed": "after_change",
            "size_limit_exceeded": "after_change",
            "inline_size_limit_exceeded": "after_change",
            "unsupported_value_type": "after_change",
            "publish_unknown": "never",
        }.get(code, "never")
    return SkillError(
        category="output",
        code=code,
        retry_class=retry_class,
        suggestion=suggestion,
    )
