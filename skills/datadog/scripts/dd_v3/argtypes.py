"""Reusable fail-closed argparse value types."""
from __future__ import annotations

import argparse
import math
from typing import Callable


def bounded_int_type(
    label: str,
    minimum: int,
    maximum: int,
) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} 必须是整数") from exc
        if parsed < minimum or parsed > maximum:
            raise argparse.ArgumentTypeError(
                f"{label} 必须在 {minimum} 到 {maximum} 之间"
            )
        return parsed

    return parse


def positive_finite_float_type(label: str) -> Callable[[str], float]:
    def parse(value: str) -> float:
        try:
            parsed = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} 必须是数字") from exc
        if not math.isfinite(parsed) or parsed <= 0:
            raise argparse.ArgumentTypeError(f"{label} 必须是大于 0 的有限数字")
        return parsed

    return parse
