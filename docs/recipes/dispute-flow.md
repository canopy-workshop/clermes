<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Recipe: Dispute Flow

A worker hits a decision point it cannot resolve on its own. It writes a
dispute file and stops. The orchestrator surfaces it to the principal. The
principal decides. The orchestrator delivers the reply.

## Step 1: The worker writes a dispute

The worker has been executing a task and encounters a choice that belongs to
the principal. It writes:

```
~/.clermes/disputes/2026-05-21-1502-choose-bank.md
```

Contents:

```markdown
---
task_id: 2026-05-21-1502-choose-bank
worker: claude-account
opened_at: 2026-05-21T15:02:11Z
priority: normal
---

## Question

Should the operating account go to Bank A or Bank B?

## Context

- Bank A: existing relationship, larger footprint.
- Bank B: local headquarters, knows state warrant procedures.

## Options

1. Bank A as primary. Matches prior preference.
2. Bank B as primary.
3. Open both; choose primary after 30 days.
```

The worker then stops. It does NOT take the task lock (nothing to release
if the task never proceeds). It does not write a done file.

## Step 2: The orchestrator drains and surfaces

On the next drain call (or cron watchdog pass), the dispute appears:

```python
events = clermes_drain_events(types=["dispute"])
# events[0].type == "dispute"
# events[0].path == "~/.clermes/disputes/2026-05-21-1502-choose-bank.md"
```

The orchestrator reads the dispute file and presents it to the principal
verbatim, without arbitrating the decision.

Timing: if the cron watchdog runs every minute, the principal sees the
dispute within one minute of it being written. The orchestrator can also
surface it immediately by draining at turn start.

## Step 3: The principal decides

The principal reads the options and tells the orchestrator: "Option 1."

## Step 4: The orchestrator delivers the reply

```python
clermes_send(
    worker="account",
    prompt=(
        "Option 1 approved for this task only. Open Bank A as primary. "
        "This authorization covers this task; do not assume a standing rule. "
        "Same decision points on future tasks should still file a dispute.\n\n"
        "TASK_ID: 2026-05-21-1502-choose-bank"
    )
)
```

Key points in the reply:
- State the authorization explicitly ("Option 1 approved").
- Scope it to this task ("for this task only").
- Tell the worker it may now proceed.
- Include the original TASK_ID so the worker can find its context.

## Step 5: The worker resumes

`clermes send` auto-heals the pane before delivering. The worker may have
exited to bash while waiting (Claude exited after a period of inactivity,
or the session was idle). The dispatcher detects the non-`claude` front
process, resumes with `claude -r <session-id>`, and delivers the reply
into a running Claude that still holds the full dispute context.

The worker reads the authorization, takes the lock, and continues:

```
~/.clermes/locks/claude-account.lock  (acquired)
... work proceeds ...
~/.clermes/done/2026-05-21-1502-choose-bank.json  (written on completion)
```

## File paths in this example

| File | Written when |
|------|-------------|
| `~/.clermes/disputes/2026-05-21-1502-choose-bank.md` | Worker stops at decision point |
| `~/.clermes/locks/claude-account.lock` | Worker resumes after authorization |
| `~/.clermes/done/2026-05-21-1502-choose-bank.json` | Worker completes |

## Timing note

The grace window and halt mechanism apply to the announce-then-act pattern,
not to disputes. A dispute is a question, not an action. The worker waits
indefinitely until the orchestrator replies. There is no automatic timeout.
