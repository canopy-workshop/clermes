#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Bash unit tests for bin/clermes.
#
# The dispatcher is sourced with CLERMES_LIB_MODE=1, which skips its preflight
# and main case dispatch. The functions are then callable in this shell against
# stubbed tmux/jq/claude binaries on PATH. Sleep is overridden to a no-op so
# the timing-dependent paths (post-compact check, wait_for_state) run fast.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DISPATCHER="$REPO/bin/clermes"

[[ -f "$DISPATCHER" ]] || { echo "FATAL: dispatcher not found at $DISPATCHER" >&2; exit 2; }

# ─────────────────────── test bookkeeping ───────────────────────

pass=0
fail=0
fail_msgs=()

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    pass=$((pass + 1))
    printf '  PASS  %s\n' "$label"
  else
    fail=$((fail + 1))
    fail_msgs+=("FAIL  $label  expected='$expected'  actual='$actual'")
    printf '  FAIL  %s\n    expected: %s\n    actual:   %s\n' "$label" "$expected" "$actual"
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    pass=$((pass + 1))
    printf '  PASS  %s\n' "$label"
  else
    fail=$((fail + 1))
    fail_msgs+=("FAIL  $label  needle='$needle'")
    printf '  FAIL  %s\n    expected to contain: %s\n    haystack:\n%s\n' "$label" "$needle" "$haystack"
  fi
}

assert_file_exists() {
  local label="$1" path="$2"
  if [[ -f "$path" ]]; then
    pass=$((pass + 1))
    printf '  PASS  %s\n' "$label"
  else
    fail=$((fail + 1))
    fail_msgs+=("FAIL  $label  path='$path'")
    printf '  FAIL  %s\n    expected file: %s\n' "$label" "$path"
  fi
}

# ─────────────────────── isolated env ───────────────────────

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

export CLERMES_HOME="$TMP_ROOT/clermes-home"
mkdir -p "$CLERMES_HOME"/{registry,workers,logs,done,disputes,announcing,halt,locks,assigned,idle-queue,state}

# Preflight values that lib mode skips setting.
export CLAUDE_PROC="claude-stub"
export CLAUDE_BIN="/bin/true"

# Stubbed tmux on PATH ahead of any real one.
STUB_DIR="$TMP_ROOT/stubs"
mkdir -p "$STUB_DIR"
PATH_BAK="$PATH"
export PATH="$STUB_DIR:$PATH_BAK"

TMUX_STATE_FILE="$STUB_DIR/tmux-state"
TMUX_CALLS_FILE="$STUB_DIR/tmux-calls"
echo "dead" > "$TMUX_STATE_FILE"
: > "$TMUX_CALLS_FILE"

# The stub records every call and reads pane state from $TMUX_STATE_FILE so a
# single test can flip the state mid-flow.
cat > "$STUB_DIR/tmux" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$TMUX_CALLS_FILE"
state=$(cat "$TMUX_STATE_FILE" 2>/dev/null || echo dead)
case "${1:-}" in
  has-session)
    [[ "$state" != "dead" ]]
    ;;
  list-panes)
    case "$state" in
      claude) echo "claude-stub" ;;
      bash)   echo "bash" ;;
      dead)   echo "" ;;
      *)      echo "$state" ;;
    esac
    ;;
  capture-pane)
    echo ""  # no post-compact sentinel
    ;;
  *)
    : # set-hook, set-window-option, new-session, send-keys, load-buffer,
      # paste-buffer, kill-session, attach-session: no-op silently.
    ;;
esac
STUB
chmod +x "$STUB_DIR/tmux"
export TMUX_STATE_FILE TMUX_CALLS_FILE

# Source the dispatcher in library mode.
export CLERMES_LIB_MODE=1
# shellcheck source=/dev/null
source "$DISPATCHER"

# Make every sleep a no-op so wait_for_state and the post-compact check run
# without burning seconds.
sleep() { :; }
export -f sleep

# ─────────────────────── TASK_ID extraction ───────────────────────

echo "## _extract_task_id"

assert_eq "empty prompt"        ""                          "$(_extract_task_id '')"
assert_eq "whitespace only"     ""                          "$(_extract_task_id '   ')"
assert_eq "no TASK_ID present"  ""                          "$(_extract_task_id 'Do the thing.')"
assert_eq "TASK_ID at end"      "2026-05-25-id-at-end"      "$(_extract_task_id $'work line\nTASK_ID: 2026-05-25-id-at-end')"
assert_eq "TASK_ID inline"      "inline-id"                 "$(_extract_task_id 'pre TASK_ID: inline-id post')"
assert_eq "first of multiple"   "first-id"                  "$(_extract_task_id $'TASK_ID: first-id\nbody\nTASK_ID: second-id')"
assert_eq "tab after colon"     "tabbed"                    "$(_extract_task_id $'TASK_ID:\ttabbed')"
assert_eq "mixed-case slug"     "Task_001.alpha-beta"       "$(_extract_task_id 'TASK_ID: Task_001.alpha-beta')"

echo ""
echo "## pipefail safety"

# Confirm the dispatcher source still wraps the optional-match pipeline.
has_wrapper=$(grep -c 'grep -oE .TASK_ID' "$DISPATCHER")
has_or_true=$(grep -c '} || true' "$DISPATCHER")
if [[ "$has_wrapper" -ge 1 && "$has_or_true" -ge 1 ]]; then
  pass=$((pass + 1))
  echo "  PASS  dispatcher retains pipefail-safe wrapper"
else
  fail=$((fail + 1))
  fail_msgs+=("FAIL  dispatcher missing pipefail-safe wrapper")
  echo "  FAIL  dispatcher missing pipefail-safe wrapper"
fi

if grep -qE '^set -euo pipefail' "$DISPATCHER"; then
  pass=$((pass + 1))
  echo "  PASS  dispatcher uses set -euo pipefail"
else
  fail=$((fail + 1))
  fail_msgs+=("FAIL  dispatcher missing 'set -euo pipefail'")
  echo "  FAIL  dispatcher missing 'set -euo pipefail'"
fi

# ─────────────────────── pane_state ───────────────────────

echo ""
echo "## pane_state"

echo "dead" > "$TMUX_STATE_FILE"
assert_eq "state: dead"        "dead"        "$(pane_state s)"

echo "bash" > "$TMUX_STATE_FILE"
assert_eq "state: bash"        "bash"        "$(pane_state s)"

echo "claude" > "$TMUX_STATE_FILE"
assert_eq "state: claude"      "claude"      "$(pane_state s)"

echo "vim" > "$TMUX_STATE_FILE"
assert_eq "state: other:vim"   "other:vim"   "$(pane_state s)"

# ─────────────────────── registry ───────────────────────

echo ""
echo "## registry helpers"

WORKDIR="$TMP_ROOT/scratch-workdir"
mkdir -p "$WORKDIR"
cat > "$CLERMES_HOME/registry/fleet.json" <<EOF
{
  "workers": {
    "scratch": {
      "workdir": "$WORKDIR",
      "owns": "test worker",
      "tmux_session": "claude-scratch",
      "session_id": "test-sid-001"
    }
  }
}
EOF

assert_eq "worker_session lookup" "claude-scratch" "$(worker_session scratch)"
assert_eq "worker_workdir lookup" "$WORKDIR"       "$(worker_workdir scratch)"
assert_eq "worker_names lookup"   "scratch"        "$(worker_names)"

# ─────────────────────── send happy path ───────────────────────

echo ""
echo "## cmd_send (state=claude happy path)"

echo "claude" > "$TMUX_STATE_FILE"
: > "$TMUX_CALLS_FILE"

out="$(cmd_send scratch $'do the task\nTASK_ID: 2026-05-25-test-send' 2>&1)" || true

assert_contains "send: success message"   "scratch: sent" "$out"
assert_file_exists "send: assigned/ file" "$CLERMES_HOME/assigned/scratch"
assert_eq "send: TASK_ID in assigned/"    "2026-05-25-test-send" "$(cat "$CLERMES_HOME/assigned/scratch")"
assert_contains "send: load-buffer used"  "load-buffer" "$(cat "$TMUX_CALLS_FILE")"
assert_contains "send: bell hooks applied" "set-hook" "$(cat "$TMUX_CALLS_FILE")"

# ─────────────────────── send: state=dead triggers spawn ───────────────────────

echo ""
echo "## cmd_send (state=dead spawns first)"

# Flip state to dead, but arm has-session so the *second* call returns true
# (after wait_for_state polls). Simplest: just flip to claude after one read.
cat > "$STUB_DIR/tmux" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$TMUX_CALLS_FILE"
state=$(cat "$TMUX_STATE_FILE" 2>/dev/null || echo dead)
case "${1:-}" in
  has-session)
    if [[ "$state" == "dead" ]]; then
      # Arm the state flip for the next probe.
      echo "claude" > "$TMUX_STATE_FILE"
      exit 1
    fi
    exit 0
    ;;
  list-panes)
    case "$state" in
      claude) echo "claude-stub" ;;
      bash)   echo "bash" ;;
      dead)   echo "" ;;
      *)      echo "$state" ;;
    esac
    ;;
  capture-pane) echo "" ;;
  *) : ;;
esac
STUB
chmod +x "$STUB_DIR/tmux"

echo "dead" > "$TMUX_STATE_FILE"
: > "$TMUX_CALLS_FILE"

out="$(cmd_send scratch $'second task\nTASK_ID: 2026-05-25-test-spawn' 2>&1)" || true

# When state is dead, cmd_send should report it's spawning. The downstream
# tmux calls depend on whether spawn finds the session file (resume) or not
# (fresh). The user-visible "Spawning first" message is the contract that
# matters for this assertion.
assert_contains "send: spawn triggered"   "Spawning first" "$out"

# ─────────────────────── _heal_pane ───────────────────────

echo ""
echo "## _heal_pane (existing session-id)"

# Restore non-flipping stub.
cat > "$STUB_DIR/tmux" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$TMUX_CALLS_FILE"
state=$(cat "$TMUX_STATE_FILE" 2>/dev/null || echo dead)
case "${1:-}" in
  has-session) [[ "$state" != "dead" ]] ;;
  list-panes)
    case "$state" in
      claude) echo "claude-stub" ;;
      bash)   echo "bash" ;;
      dead)   echo "" ;;
      *)      echo "$state" ;;
    esac ;;
  capture-pane) echo "" ;;
  *) : ;;
esac
STUB
chmod +x "$STUB_DIR/tmux"

# Worker has session_id "test-sid-001" in registry. _heal_pane should
# send-keys "<claude-bin> -r test-sid-001" and wait for state=claude.
echo "claude" > "$TMUX_STATE_FILE"
: > "$TMUX_CALLS_FILE"

out="$(_heal_pane scratch 2>&1)" || true

assert_contains "heal: send-keys -r issued" "send-keys" "$(cat "$TMUX_CALLS_FILE")"
assert_contains "heal: session-id present"  "test-sid-001" "$(cat "$TMUX_CALLS_FILE")"
assert_contains "heal: resumed message"     "resumed" "$out"

# ─────────────────────── preamble rendering ───────────────────────

echo ""
echo "## render_preamble"

# Configure instance.name + instance.principal in config.yaml so the template
# substitution is exercised.
cat > "$CLERMES_HOME/config.yaml" <<'EOF'
instance:
  name: TestInstance
  principal: TestPrincipal
EOF

# Default template at $REPO/templates/preamble.md should be found via SCRIPT_DIR
# relative path (SCRIPT_DIR was resolved from $0, which for source is the
# DISPATCHER path).
preamble_out="$(render_preamble scratch /tmp/work 2>&1)"
assert_contains "preamble: WORKER substituted"        "claude-scratch"     "$preamble_out"
assert_contains "preamble: WORKDIR substituted"       "/tmp/work"          "$preamble_out"
assert_contains "preamble: INSTANCE_NAME substituted" "TestInstance"       "$preamble_out"
assert_contains "preamble: PRINCIPAL substituted"     "TestPrincipal"      "$preamble_out"

# Per-worker override wins.
mkdir -p "$CLERMES_HOME/workers/scratch"
cat > "$CLERMES_HOME/workers/scratch/preamble.md" <<'EOF'
OVERRIDE for claude-${WORKER} at ${WORKDIR}
EOF
preamble_out="$(render_preamble scratch /tmp/work 2>&1)"
assert_contains "preamble: per-worker override applied" "OVERRIDE for claude-scratch" "$preamble_out"

# ─────────────────────── result ───────────────────────

echo ""
echo "Results: $pass pass, $fail fail"
if (( fail > 0 )); then
  printf '\nFailures:\n'
  for m in "${fail_msgs[@]}"; do printf '  - %s\n' "$m"; done
  exit 1
fi
exit 0
