<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Bell-Based Attention Detection

How the orchestrator learns that a worker is sitting at a prompt waiting
for input. Built on the terminal bell (`\a`), produced by Claude Code
itself when it needs input, surfaced through tmux's `alert-bell` hook,
and delivered through the Hermes cron pipeline.

## The failure mode being solved

A worker receives a task, runs partway, then stops at an interactive
prompt. Common causes:

- Claude Code permission dialog ("Allow this tool to run? [y/n]").
- `AskUserQuestion` rendering a multi-option picker.
- End-of-turn question where Claude finishes a turn with a question
  rather than taking further action.

An earlier design used tmux's `monitor-silence` + `alert-silence`. It
failed for exactly these cases: while Claude is sitting at an interactive
prompt, the input cursor blinks and the TUI redraws periodically. From
tmux's point of view the pane is producing output and is not silent.
Silence-based detection only fired when Claude had fully collapsed its UI,
which is rare.

The fix inverts the signal: instead of trying to detect the absence of
activity, have Claude Code itself emit a positive signal whenever it needs
input, and key on that signal.

## The pipeline

```
Claude Code event (Notification / Stop-with-?)
         │
         ▼
bell-on-input-needed.sh
  printf '\a' > /dev/tty
         │
         ▼
  tmux sees the bell
         │
         ▼
  alert-bell hook fires
  (session-scoped, set on spawn + send)
         │
         ▼
clermes-on-bell.sh <session>
  - check assigned/<worker>
  - capture pane (last N lines)
  - SHA-1 dedupe against state/last-notify-<worker>
  - write idle-queue/<ts>-<worker>.json
         │
         ▼
~/.clermes/idle-queue/*.json
         │
         ▼
clermes-watchdog (cron, every minute)
  - drain queue
  - clean up stale assigned/ markers
  - emit notification block to stdout
         │
         ▼
orchestrator receives notification
```

## Components

| File | Role |
|------|------|
| `bin/clermes` | Dispatcher. `cmd_send` writes `assigned/<worker>` atomically. `cmd_spawn` sets `monitor-bell on` and binds the `alert-bell` hook. `apply-bell-hooks` retrofits live sessions. `install-claude-hooks` registers the bell hook in Claude Code settings.json. |
| `scripts/bell-on-input-needed.sh` | Claude Code hook (Notification + Stop events). Writes `printf '\a' > /dev/tty`. Registered in `settings.json`. |
| `scripts/clermes-on-bell.sh` | tmux `alert-bell` callback. Decides whether the bell warrants a notification; writes `idle-queue/` entries. |
| `scripts/clermes-watchdog` | Cron job. Drains idle queue, cleans stale assigned markers, emits to stdout for delivery to the orchestrator. |
| `~/.clermes/assigned/<worker>` | Single-line file: task_id of the worker's current task. Written atomically by `cmd_send`. |
| `~/.clermes/idle-queue/<ts>-<worker>.json` | One notification per file. Drained by the watchdog. |
| `~/.clermes/state/last-notify-<worker>` | SHA-1 of pane content at the last fired notification. Dedupe key. |
| `~/.clermes/logs/bell-detection.log` | Per-bell log: which worker, which task, fired or suppressed and why. |
| `~/.clermes/logs/watchdog.log` | Watchdog log (queue drains, assigned-marker cleanups). |

## Lifecycle

### One-time setup

```bash
# Register bell hook in Claude Code settings (user-level, covers all workers):
clermes install-claude-hooks --user

# Or per-worker (writes to <workdir>/.claude/settings.json):
clermes install-claude-hooks <worker>
```

The dispatcher does not auto-install Claude Code hooks on every dispatch
because that would mutate each workdir's `settings.json` on every send.
Run `install-claude-hooks` once at setup time.

### Spawn

`clermes spawn <worker>` creates the tmux session, then runs
`_apply_bell_hooks` to set `monitor-bell on` and bind the `alert-bell`
hook to `clermes-on-bell.sh #{session_name}`. Hooks are session-scoped
so they survive tmux config reloads but not tmux server restarts.

### Send

`clermes send <worker> "<prompt>"` parses `TASK_ID:` from the prompt,
writes `assigned/<worker>` atomically, clears any stale
`state/last-notify-<worker>`, then pastes the prompt. If the session
pre-existed without bell hooks, `_apply_bell_hooks` runs on every send
(idempotent).

### Bell fires

Claude Code's hook rings the bell. tmux notices, fires `alert-bell`,
which runs `clermes-on-bell.sh <session>`. The script:

1. Bails if no `assigned/<worker>` file (bell without an assigned task
   is not actionable).
2. Bails if `done/<task>.json` or `disputes/<task>.md` exists (race
   between completion and bell: the worker finished before the bell
   handler checked).
3. Captures `tmux capture-pane -p -S -N` (N from `CLERMES_IDLE_PANE_LINES`).
4. SHA-1s the capture. Suppresses if the hash matches `state/last-notify-<worker>`
   (same pane state, same bell, would be a duplicate notification).
5. Writes `idle-queue/<timestamp>-<worker>.json` with
   `{detected_at, worker, session, task_id, event_hash, pane_tail}`.
6. Stores the new hash in `state/last-notify-<worker>`.

### Drain

`clermes-watchdog` (cron, every minute) drains the queue and emits one
block per notification to stdout. Cron delivers stdout to the orchestrator.

When Claude makes further progress (pane content changes), the next bell
produces a different `event_hash` and queues a fresh notification.

### Cleanup

The watchdog walks `assigned/` and removes any marker whose task already
has a `done/*.json` or `disputes/*.md`. The matching
`state/last-notify-<worker>` is removed at the same time.

## Configuration

`~/.clermes/idle.env`:

```env
# Capture depth (lines) when a bell fires.
CLERMES_IDLE_PANE_LINES=40
```

`CLERMES_IDLE_THRESHOLD` is parsed for backward compatibility but is no
longer used. The bell is instantaneous, not threshold-based.

## Cron registration (Hermes side)

```python
CronCreate(
    name="Clermes worker watchdog (bell detection)",
    schedule="*/1 * * * *",
    script_path="/home/$USER/.hermes/scripts/clermes-watchdog",
    no_agent=True,
    deliver_to="origin",
)
```

The watchdog is silent when nothing is queued, so the per-minute schedule
is cheap.

## Edge cases

| Case | Handling |
|------|---------|
| Worker working hard, no input needed | Claude never fires Notification or Stop-with-question; no bell; no notification. |
| Worker hit permission dialog | Notification fires, bell rings, notification queued within seconds. |
| Worker hit AskUserQuestion | Same path as permission dialog. |
| Worker finishes turn with a question | Stop fires, last message ends with `?`, bell rings, notification queued. |
| Worker finishes turn cleanly | Stop fires; last message does not end with `?`; no bell. Watchdog still emits the matching `done/*.json` on its next cron pass. |
| Worker without Claude Code hook installed | No bell, no notification. Run `clermes install-claude-hooks <worker>`. |
| Done file exists when bell fires | Script re-checks immediately before queueing. Stale assigned marker cleaned up on next watchdog pass. |
| Same idle state lingers | SHA-1 dedupe collapses identical pane states to one notification. Pane change re-arms. |
| Two sends to same worker in quick succession | Atomic `mv` for assigned marker; second write wins. Dedupe state cleared on each send. |
| Send without TASK_ID footer | Marker written as `unknown-<epoch>`. Watchdog cannot auto-match a done file but bell detection still works. Warning logged. |
| tmux server restart | Session-scoped hooks vanish. Run `clermes apply-bell-hooks all` after restart, or `clermes heal` to respawn. The dispatcher calls `_apply_bell_hooks` on every send, so the first send after restart re-installs the hook. |
| Worker pane capture fails (session died) | Notification queued with a `<pane capture failed>` body. A dead worker mid-task is worth surfacing. |
| Malformed idle-queue JSON | Watchdog logs the parse failure and leaves the file in place rather than dropping it. |

## Testing the pipeline without waiting

```bash
# 1. Fake an assignment.
echo "test-bell-1" > ~/.clermes/assigned/scratch

# 2. Invoke the bell handler directly.
~/.hermes/scripts/clermes-on-bell.sh claude-scratch

# 3. Verify the queue file landed.
ls -la ~/.clermes/idle-queue/

# 4. Run the watchdog. Should emit a notification block and drain.
~/.hermes/scripts/clermes-watchdog

# 5. Simulate completion.
echo '{"task_id":"test-bell-1","status":"done"}' \
  > ~/.clermes/done/test-bell-1.json
~/.hermes/scripts/clermes-watchdog

# Assigned marker should now be gone.
ls ~/.clermes/assigned/scratch
```

## What the bell pipeline does not cover

**Pitfall 16:** bell detection misses workers stuck in long compute steps
that fire neither a Notification nor a Stop event. If a worker is in the
middle of a multi-minute tool call (large file analysis, slow shell command),
Claude Code does not emit any hook event during that time. The pane is not
idle in the silence-detection sense either. The bell never fires. The only
way to observe these is to call `clermes capture <worker>` explicitly after
an unexpectedly long quiet period.

The bell pipeline also does not:
- Detect workers stuck on interactive Claude Code dialogs (multi-choice
  pickers, prompt-injection warnings). The TUI redraws continuously,
  so silence detection does not fire. See `docs/recipes/troubleshooting.md`.
- Retry a missed notification. If the queue-write fails, that fire is logged
  and dropped. The next bell produces a fresh attempt.
- Introspect Claude's internal state. The only signals are the bell and the
  visible pane content at bell time.

## Why the bell wins over silence detection

`monitor-silence` measures the absence of pane changes. In a Claude Code
session that absence almost never happens: the cursor blinks, the input
box redraws, the status footer updates with elapsed time. So silence
detection fires either never (for active prompts) or rarely (only when
Claude has fully collapsed its UI). Bell detection inverts the mechanism:
Claude Code itself emits the signal at exactly the moments worth surfacing,
and the pipeline plumbs that signal to the orchestrator. Precise events,
not timing heuristics.
