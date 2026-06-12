#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# clermes-on-bell.sh: invoked by tmux's alert-bell hook when a worker pane
# rings the terminal bell. The bell is produced by Claude Code itself via
# the bell-on-input-needed.sh hook (registered on Notification + Stop
# events), so a bell here means "Claude is waiting on me for something."
#
# Argv: $1 = tmux session name (e.g., "claude-scratch")
#
# Responsibility:
#   1. Bail out if the worker has no current task assignment (bell during
#      idle period is not actionable).
#   2. Bail out if the task already has a done/dispute file (worker already
#      finished; race between completion and bell). Clean up the stale
#      assignment marker so we do not keep firing.
#   3. Capture the last N lines of the pane.
#   4. Dedupe against the previous notification's event hash; suppress
#      identical repeats (rapid bell re-fires while the operator is away).
#   5. Write an idle-queue entry; the cron watchdog drains and delivers.
#
# All paths live under $CLERMES_HOME (default ~/.clermes).
# Logs to $CLERMES_HOME/logs/bell-detection.log.

set -uo pipefail

CLERMES_HOME="${CLERMES_HOME:-$HOME/.clermes}"
LOG="$CLERMES_HOME/logs/bell-detection.log"
CAPTURE_LINES_DEFAULT=40

mkdir -p "$CLERMES_HOME"/{idle-queue,state,logs,assigned}

if [[ -f "$CLERMES_HOME/idle.env" ]]; then
    # shellcheck disable=SC1091
    set -a; . "$CLERMES_HOME/idle.env"; set +a
fi
CAPTURE_LINES="${CLERMES_IDLE_PANE_LINES:-$CAPTURE_LINES_DEFAULT}"

session="${1:-}"
if [[ -z "$session" ]]; then
    printf '%s [bell-hook] missing session argument\n' "$(date -Iseconds)" >> "$LOG"
    exit 1
fi

# Worker name = session name minus the "claude-" prefix.
worker="${session#claude-}"

log() { printf '%s [%s] %s\n' "$(date -Iseconds)" "$worker" "$*" >> "$LOG"; }

assigned_file="$CLERMES_HOME/assigned/$worker"
if [[ ! -f "$assigned_file" ]]; then
    log "bell fired but worker has no assigned task. Ignoring."
    exit 0
fi

task_id="$(cat "$assigned_file" 2>/dev/null || true)"
if [[ -z "$task_id" ]]; then
    log "bell fired with empty assigned-task file. Removing."
    rm -f "$assigned_file"
    exit 0
fi

# Task already complete: clean up and bail.
if [[ -f "$CLERMES_HOME/done/$task_id.json" ]] || [[ -f "$CLERMES_HOME/disputes/$task_id.md" ]]; then
    log "bell fired but task $task_id already completed/disputed. Removing assigned marker."
    rm -f "$assigned_file"
    rm -f "$CLERMES_HOME/state/last-notify-$worker"
    exit 0
fi

# Capture the pane. If the session died between bell and now, emit the
# notification anyway. A worker disappearing mid-task should be visible.
if ! pane_content="$(tmux capture-pane -p -S "-$CAPTURE_LINES" -t "$session" 2>/dev/null)"; then
    pane_content="<pane capture failed: session may have died>"
fi

# event_hash = SHA-1 of pane content at bell time. Same hash on the next
# bell means nothing changed; suppress as a dupe.
event_hash="$(printf '%s' "$pane_content" | sha1sum | awk '{print $1}')"

last_hash_file="$CLERMES_HOME/state/last-notify-$worker"
if [[ -f "$last_hash_file" ]] && [[ "$(cat "$last_hash_file" 2>/dev/null)" == "$event_hash" ]]; then
    log "bell fired with matching last-notify hash $event_hash. Suppressing."
    exit 0
fi

detected_at="$(date -Iseconds)"
queue_file="$CLERMES_HOME/idle-queue/$(date +%s%N)-$worker.json"

if ! jq -n \
    --arg detected_at "$detected_at" \
    --arg worker "$worker" \
    --arg session "$session" \
    --arg task_id "$task_id" \
    --arg pane "$pane_content" \
    --arg event_hash "$event_hash" \
    --argjson capture_lines "$CAPTURE_LINES" \
    '{detected_at: $detected_at, worker: $worker, session: $session, task_id: $task_id, event_hash: $event_hash, capture_lines: $capture_lines, pane_tail: $pane}' \
    > "$queue_file.tmp" 2>>"$LOG"; then
    log "jq failed building notification. Leaving partial $queue_file.tmp in place"
    exit 1
fi
mv -f "$queue_file.tmp" "$queue_file"

printf '%s\n' "$event_hash" > "$last_hash_file"
log "queued notification $queue_file (task=$task_id, event_hash=$event_hash)"
