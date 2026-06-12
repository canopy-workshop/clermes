#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Smoke tests for clermes-on-bell.sh, the tmux alert-bell handler.
#
# Exercises the handler's decision logic directly. The handler reads from
# $CLERMES_HOME, so we point it at a scratch dir under /tmp for isolation
# and stub tmux on PATH so no real session is required.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HANDLER="$REPO/scripts/clermes-on-bell.sh"
[[ -x "$HANDLER" ]] || { echo "FATAL: handler not executable at $HANDLER" >&2; exit 2; }

CLERMES_HOME="$(mktemp -d -t clermes-bell-test.XXXXXX)"
export CLERMES_HOME
trap 'rm -rf "$CLERMES_HOME"' EXIT

mkdir -p "$CLERMES_HOME"/{assigned,done,disputes,announcing,idle-queue,state,logs}

pass=0
fail=0
fail_msgs=()

assert() {
    local label="$1" condition="$2"
    if eval "$condition"; then
        pass=$((pass + 1))
        printf '  PASS  %s\n' "$label"
    else
        fail=$((fail + 1))
        fail_msgs+=("FAIL  $label  (condition: $condition)")
        printf '  FAIL  %s\n    condition: %s\n' "$label" "$condition"
    fi
}

# Stub `tmux capture-pane` so the handler does not need a real session.
FAKE_BIN="$CLERMES_HOME/bin"
mkdir -p "$FAKE_BIN"
cat > "$FAKE_BIN/tmux" <<'STUB'
#!/usr/bin/env bash
case "$1" in
    capture-pane)
        printf '%s' "${TMUX_FAKE_PANE:-<empty pane>}"
        ;;
    *)
        exit 0
        ;;
esac
STUB
chmod +x "$FAKE_BIN/tmux"
export PATH="$FAKE_BIN:$PATH"

queue_count() { ls -1 "$CLERMES_HOME/idle-queue" 2>/dev/null | wc -l; }

reset_state() {
    rm -f "$CLERMES_HOME/idle-queue"/*.json 2>/dev/null
    rm -f "$CLERMES_HOME/state"/last-notify-* 2>/dev/null
    rm -f "$CLERMES_HOME/assigned"/* 2>/dev/null
    rm -f "$CLERMES_HOME/done"/*.json 2>/dev/null
    rm -f "$CLERMES_HOME/disputes"/*.md 2>/dev/null
}

# Case 1: bell fires for unassigned worker. No notification.
echo "## Case 1: bell fires for unassigned worker"
reset_state
export TMUX_FAKE_PANE="pane content for unassigned case"
"$HANDLER" claude-scratch
assert "no queue file created" "[[ $(queue_count) -eq 0 ]]"

# Case 2: assigned worker, no done file. Notification queued.
echo ""
echo "## Case 2: assigned worker, no done file"
reset_state
echo "test-bell-A" > "$CLERMES_HOME/assigned/scratch"
export TMUX_FAKE_PANE="pane content case 2"
"$HANDLER" claude-scratch
assert "one queue file created" "[[ $(queue_count) -eq 1 ]]"
qf="$(ls "$CLERMES_HOME/idle-queue"/*.json)"
assert "queue file has event_hash field" "jq -e '.event_hash' '$qf' > /dev/null"
assert "queue file has task_id = test-bell-A" "[[ \"\$(jq -r .task_id '$qf')\" == 'test-bell-A' ]]"
assert "queue file pane_tail matches stub" "[[ \"\$(jq -r .pane_tail '$qf')\" == 'pane content case 2' ]]"
assert "last-notify hash written" "[[ -f '$CLERMES_HOME/state/last-notify-scratch' ]]"

# Case 3: same pane on next fire. Dedupe suppresses.
echo ""
echo "## Case 3: same pane on next fire"
"$HANDLER" claude-scratch
assert "still one queue file (dedupe held)" "[[ $(queue_count) -eq 1 ]]"

# Case 4: pane content changes. New notification queued.
echo ""
echo "## Case 4: pane content changes"
export TMUX_FAKE_PANE="pane content case 4 different"
"$HANDLER" claude-scratch
assert "queue count incremented to 2" "[[ $(queue_count) -eq 2 ]]"

# Case 5: task already in done/. Bail and clean up.
echo ""
echo "## Case 5: matching done file exists"
reset_state
echo "test-bell-B" > "$CLERMES_HOME/assigned/scratch"
echo '{"task_id":"test-bell-B","status":"done"}' > "$CLERMES_HOME/done/test-bell-B.json"
export TMUX_FAKE_PANE="pane content case 5"
"$HANDLER" claude-scratch
assert "no queue file produced" "[[ $(queue_count) -eq 0 ]]"
assert "assigned marker removed" "[[ ! -f '$CLERMES_HOME/assigned/scratch' ]]"

# Case 6: empty assigned marker. Remove and bail.
echo ""
echo "## Case 6: empty assigned marker"
reset_state
: > "$CLERMES_HOME/assigned/scratch"
"$HANDLER" claude-scratch
assert "no queue file produced" "[[ $(queue_count) -eq 0 ]]"
assert "empty marker removed" "[[ ! -f '$CLERMES_HOME/assigned/scratch' ]]"

# Case 7: missing session argument.
echo ""
echo "## Case 7: missing session argument"
set +e
"$HANDLER"
rc=$?
set -e
assert "handler exited with code 1" "[[ $rc -eq 1 ]]"

# Source-level invariants.
echo ""
echo "## Source-level invariants"
assert "handler is the alert-bell hook handler" \
    "grep -q 'alert-bell' '$HANDLER'"
assert "handler uses event_hash (not pane_hash)" \
    "grep -q 'event_hash' '$HANDLER' && ! grep -q '\"pane_hash\"' '$HANDLER'"
assert "dispatcher binds monitor-bell + alert-bell" \
    "grep -q 'monitor-bell on' '$REPO/bin/clermes' && grep -q 'alert-bell' '$REPO/bin/clermes'"
assert "dispatcher exposes install-claude-hooks subcommand" \
    "grep -q 'install-claude-hooks' '$REPO/bin/clermes'"
assert "bell-on-input-needed.sh shipped" \
    "[[ -f '$REPO/scripts/bell-on-input-needed.sh' ]]"

echo ""
echo "Results: $pass pass, $fail fail"
if (( fail > 0 )); then
    printf '\nFailures:\n'
    for m in "${fail_msgs[@]}"; do printf '  - %s\n' "$m"; done
    exit 1
fi
exit 0
