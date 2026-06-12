#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Run all Clermes tests: bash + python suites.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

if ! command -v python3 >/dev/null 2>&1; then
    echo "FATAL: python3 not on PATH" >&2
    exit 2
fi

echo "=== bash tests ==="
for t in tests/bash/*.sh; do
    [[ -f "$t" ]] || continue
    echo "-- $t --"
    bash "$t" || exit 1
done

echo ""
echo "=== python tests ==="
exec python3 -m unittest \
    tests.python.test_config \
    tests.python.test_registry \
    tests.python.test_events \
    tests.python.test_history \
    tests.python.test_routing \
    tests.python.test_tools \
    "$@"
