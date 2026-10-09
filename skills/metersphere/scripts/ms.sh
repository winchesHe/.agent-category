#!/usr/bin/env bash
set -euo pipefail

# 向后兼容入口；真实实现集中在 metersphere.py。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/metersphere.py" "$@"
