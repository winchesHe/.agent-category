"""Small typed values shared by the CLI application services."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str

    def to_payload(self) -> dict[str, str]:
        return {"name": self.name, "dataType": self.data_type}


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[Column, ...]
    records: tuple[dict[str, Any], ...]
    row_count: int
    truncated: bool
    elapsed_ms: int
    connection_database: str
    statement_timeout_ms: int


@dataclass(frozen=True)
class CommandResult:
    """Channel-neutral result returned by a CLI application service."""

    data: Any
    meta: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class InvocationState:
    """Tracks only state needed to report interruption without unsafe cleanup."""

    artifact_state: str | None = None
    output_ref: str | None = None
    temp_name: str | None = None
    final_name: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def interruption_details(self) -> dict[str, str]:
        if self.artifact_state == "durable_published" and self.output_ref:
            return {"artifactState": "published", "outputRef": self.output_ref}
        if self.artifact_state == "final_link_created":
            return {"artifactState": "may_exist"}
        return {}
