<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Troubleshooting

Symptoms, diagnoses, and fixes from the Clermes shakedowns.

---

## Worker pane stuck on bash

**Symptom:** `clermes list` shows `STATE=bash` for a worker. Any
`clermes send` to that worker would paste into bash, not Claude.

**Diagnose:** the pane's front process is `bash` (or `sh`, `zsh`, etc.),
not the Claude binary. Claude exited: common causes are `/exit` in the
TUI, a crash, or a long idle period.

**Fix:** `clermes_heal` or `clermes send <worker> "<next task>"`.

The dispatcher auto-heals before delivery. It detects the non-`claude` front
process, runs `claude -r <session-id>` against the saved session file
(`~/.claude/projects/<encoded-workdir>/<uuid>.jsonl`), waits for the `claude`
state, then delivers the prompt. Conversation history is fully preserved.

To heal without sending a new task: `clermes heal` or `clermes_heal()`.

---

## Pre-compact swallowed my brief

**Symptom:** `clermes send` returned success. The worker's pane shows
`✻ Conversation compacted` immediately followed by an idle `❯` prompt.
No tool calls started. The task was not received.

**Diagnose:** the prompt arrived while the worker was mid-compact. The
compacted context summary did not include the new prompt because it arrived
after the snapshot but before the new session was active.

**Fix:** resend the full brief. The post-compact worker is clean and ready.

```python
clermes_send(worker="<worker>", prompt="<full brief verbatim>")
```

The dispatcher performs a post-send capture check: 2 seconds after delivery,
it captures the pane and looks for the `Conversation compacted` sentinel.
If found, it resends automatically. If you suspect the automatic resend also
landed in a compact window, check the pane explicitly:

```python
clermes_capture(worker="<worker>", lines=20)
```

---

## Auto-mode classifier denying a benign probe

**Symptom:** a worker reports `Bash(which ffmpeg)` denied by the
auto-mode classifier, or similar. A simple read-only probe is blocked.

**Diagnose:** the classifier evaluates the task trajectory, not just the
single command. A benign probe gets denied because the broader task involves
something flagged: copyright-shaped downloads, shared-filesystem writes,
external POST calls, or agent-inferred destructive parameters.

**Fix:** the worker should file a dispute with the question, context, and
2-4 concrete options. The orchestrator surfaces it to the principal verbatim.
On approval, send an explicit one-time authorization:

> "Authorized for this task only: [action]. Do not assume a standing rule.
> Same classifier prompts on future tasks should still file a dispute."

Do NOT use `--permission-mode bypassPermissions`. The classifier is doing
useful work; bypass disables it entirely for the session.

Also applies when a mid-task correction reverses a prior constraint. Example:
initial dispatch said "do not invoke binary X from terminal," a later
correction said "use binary X at path Y." The classifier may read the
correction as conflicting instruction and block it. Workaround: state the
supersession explicitly in the follow-up: "This supersedes the earlier
instruction to avoid X."

---

## Honcho deriver failing with "empty JSON"

**Symptom:** the Honcho deriver logs show `Repair failed: empty JSON`.
No observations are being extracted from conversation batches.

**Diagnose:** the deriver model (Qwen 3.5 or similar) has an extended
thinking mode that fires unpredictably. When it fires on a deriver call,
the model emits a reasoning block rather than strict JSON output. The
deriver cannot parse a reasoning block as structured output.

**Fix:** set `think: false` in the deriver model config:

```env
# In honcho/.env
DERIVER_MODEL_CONFIG__OVERRIDES__EXTRA_BODY={"think": false}
```

Then restart the deriver:

```bash
docker compose restart deriver   # from the honcho/ directory
```

The `.env.example` ships this setting enabled. If it disappeared from your
`.env`, add it back.

---

## Bell never fires

**Symptom:** workers complete tasks (or sit waiting) but the orchestrator
never receives a bell-based notification. The idle-queue directory stays empty.

**Diagnose:** the Claude Code hook is not installed. The bell pipeline requires
a hook script registered in Claude Code's `settings.json` that fires on
Notification and Stop events. Without the hook, Claude never writes `\a` to the
terminal and tmux never fires `alert-bell`.

**Fix:** install the hook.

```bash
# User-level (covers all workers):
clermes install-claude-hooks --user

# Per-worker (writes to <workdir>/.claude/settings.json):
clermes install-claude-hooks <worker>
```

After installing, respawn any affected workers (`clermes heal` or
`clermes spawn <worker>`) so Claude reads the updated `settings.json`.

Also check that the tmux session has `monitor-bell on` and the `alert-bell`
hook bound. The dispatcher sets these on spawn and on every send, but they
are session-scoped and vanish on tmux server restart. After a tmux restart:

```bash
clermes apply-bell-hooks all
```

---

## Worker resumes into wrong project

**Symptom:** after a heal or respawn, the worker's context does not match the
expected workdir. It may be referencing a different project or starting fresh
instead of resuming.

**Diagnose:** Claude Code stores conversation history at
`~/.claude/projects/<encoded-workdir>/<uuid>.jsonl`. The encoding replaces
every non-alphanumeric character (including `.` and `/`) with `-`. A naive
`/`-only replacement misses workdirs with dots, so the session file is never
found and Claude starts fresh, producing a "Session ID already in use" or
silent fresh-start behavior.

Example: workdir `/home/user/projects/canopyworkshop.com` encodes as
`-home-user-projects-canopyworkshop-com` (dot replaced), not
`-home-user-projects-canopyworkshop.com`.

**Fix:** the dispatcher uses `sed 's|[^a-zA-Z0-9]|-|g'` to encode the
workdir, which replaces all non-alphanumeric characters. If you are computing
the encoded path manually elsewhere, use the same regex. Do not use a simple
`/`-only replacement.

Verify the correct session file exists:

```bash
encoded=$(echo "<workdir>" | sed 's|[^a-zA-Z0-9]|-|g')
ls ~/.claude/projects/$encoded/
```

If the session file is missing, the session UUID in
`~/.clermes/workers/<worker>/session-id` does not match any file in the
projects directory. Check for an encoding mismatch or a workdir change.
