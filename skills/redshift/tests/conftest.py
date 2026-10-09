from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))


@pytest.fixture(autouse=True)
def isolate_operator_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never inherit operator-managed Redshift configuration."""

    for key in tuple(os.environ):
        if key.startswith("REDSHIFT_") or key.startswith("RS_"):
            monkeypatch.delenv(key, raising=False)
