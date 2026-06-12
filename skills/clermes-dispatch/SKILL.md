<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
---
name: clermes:dispatch
description: Operate the Clermes worker fleet from Hermes: pick a worker, dispatch a brief, watch the file channels, surface disputes.
platforms: [linux]
---

# Clermes Dispatch

Clermes is the orchestration framework. Workers are long-lived tmux sessions
running interactive Claude Code, one per domain. Each worker is pinned to a
workdir and holds warm project context. Coordination is file-based and lives
under `~/.clermes/`.

## Two-layer naming model

Clermes is the **framework**: generic, same on every install. Each install
picks its own **instance handle** (set in `~/.clermes/config.yaml` under
`instance.name`). The persona surface (voice, greetings, skin) lives at the
instance layer. The protocol, file channels, and dispatcher are framework
layer. Do not conflate the two when addressing the operator.

## Files of record

| Path | Purpose |
|------|---------|
| `~/.clermes/config.yaml` | Instance config (name, routing rules, outbound policy) |
| `~/.clermes/registry/fleet.json` | Worker definitions: name, workdir, tmux session, UUID |
| `~/.clermes/PROTOCOL.md` | Coordination contract workers read on spawn |
| `~/.clermes/workers/<name>/session-id` | Stable Claude session UUID per worker |
| `~/.clermes/done/<task-id>.json` | Worker writes on completion |
| `~/.clermes/disputes/<task-id>.md` | Worker writes when needing the principal's decision |
| `~/.clermes/announcing/<task-id>.txt` | Pre-action callout for irreversible external ops |
| `~/.clermes/halt/<task-id>` | Touch to abort an announced action during grace window |
| `~/.clermes/locks/claude-<name>.lock` | Worker is mid-task |
| `~/.clermes/logs/claude-<name>.log` | Append-only pane snapshots |

## Workflow

### 1. Pick the worker

Use `clermes_pick_worker` with the task description. It scores against
`routing.rules` from `config.yaml`. Branch on the result:

- `worker` set, `ambiguous=false`: dispatch.
- `ambiguous=true`: surface the candidates to the operator. Do not make assumptions.
  Two workers editing the same file is a race condition.
- `used_default=true`: no rule matched; the configured default worker is used.
  Sanity-check the routing before proceeding.

### 2. Verify the worker is alive

```bash
clermes list
```

| STATE | Meaning |
|-------|---------|
| `claude` | Worker ready to receive a task. |
| `bash` | tmux session exists but Claude exited. Heal before sending. |
| `dead` | No tmux session. Spawn from scratch. |
| `other:<proc>` | Something else is foreground. Heal before sending. |

`clermes send` auto-heals before delivery (detects the wrong front process,
re-launches Claude with `-r <session-id>` to preserve conversation context).
You can also force a pass across the whole fleet: `clermes heal`.

For a JSON view of the entire fleet (state + recent pane content + lock info):

```bash
clermes snapshot
```

This is the preferred read primitive when making a routing decision based on
what workers are currently doing.

### 3. Generate a task ID and send

Task ID format: `YYYY-MM-DD-HHMM-<short-slug>`.
Example: `2026-05-21-1437-studio-wordmark-margin`.

Every brief **must** instruct the worker to follow protocol. Include this
footer on every send:

```
TASK_ID: <task-id>
On start: acquire ~/.clermes/locks/claude-<worker>.lock with {task_id, started_at, pid}.
On completion: write ~/.clermes/done/<task-id>.json with status, result, artifacts.
If decision needed: write ~/.clermes/disputes/<task-id>.md and stop.
Before irreversible external action: write ~/.clermes/announcing/<task-id>.txt,
sleep the grace window from config, check ~/.clermes/halt/<task-id>, then proceed.
```

Dispatch:

```bash
clermes send <worker> "<full task brief including footer>"
```

Or via the plugin tool: `clermes_send(worker=..., prompt=..., slug=...)`.
The tool appends a TASK_ID footer automatically if the prompt lacks one.

### 4. Watch for completion

**Ground truth: poll the done file.**

```bash
while [ ! -f ~/.clermes/done/<task-id>.json ] && \
      [ ! -f ~/.clermes/disputes/<task-id>.md ]; do
  sleep 5
done
```

Or drain via the plugin: `clermes_drain_events(types=["done", "dispute"])`.

**Live colour: capture the pane occasionally.**

```bash
clermes capture <worker> 60
```

Use when the operator asks "what is it doing" or to spot-check progress
without spamming polls.

### 5. Handle the outcome

```bash
jq . ~/.clermes/done/<task-id>.json
```

Status branches:

- `done`: summarize the result. Cite artifacts. Stash durable state to
  memory if it matters next session.
- `disputed`: read `~/.clermes/disputes/<task-id>.md`, surface to the
  principal verbatim. Add your own framing only if it adds context. Do not
  arbitrate.
- `blocked`: read the result field. Either escalate to the principal or
  dispatch to a different worker if the block is a routing mismatch.
- `error`: read the result, decide whether to retry, escalate, or abandon.

### 6. Handle announcements

If `~/.clermes/announcing/<task-id>.txt` appears, the worker is about to
take an irreversible external action. The grace window defaults to 10s. To
abort:

```bash
touch ~/.clermes/halt/<task-id>
```

The halt file must land before the grace window expires.

### 7. Reply to a worker after a dispute

The reply is just another `clermes send` to that worker. Include the
original TASK_ID. State the authorization explicitly and scope it:

> "Option 1 authorized for this task only. Do not assume a standing rule.
> Same classifier prompts on future tasks should still file a dispute."

One-time approval, not a standing permission, unless the principal says otherwise.

Do not type replies directly into the worker pane. Route through `clermes send`
so logging and heal logic apply.

## Parallel dispatch

When a request decomposes into independent per-worker tasks, dispatch all in
one call:

```python
clermes_dispatch_parallel(jobs=[
    {"worker": "ledger",   "prompt": "...", "slug": "audit-ledger"},
    {"worker": "studio",   "prompt": "...", "slug": "audit-studio"},
    {"worker": "scratch",  "prompt": "...", "slug": "audit-scratch"},
])
```

See `docs/recipes/parallel-dispatch.md` for the full worked example with
expected event flow.

## Operating rules

**Turn-start worker check (MANDATORY).** At the start of every turn where
workers have been dispatched in this session and their completion has not
been confirmed, run `clermes capture <worker>` for each in-flight worker
BEFORE responding to the operator. The cron watchdog posts done/dispute/
announcing file drops between turns, but you still own turn-start status
checks for workers that may be sitting idle waiting on clarification (which
the watchdog cannot detect because no file is written).

**Keep it short. Delegate aggressively.** Anything a worker can do, dispatch
it. Long explanations belong in worker output, not in the orchestrator's
reply. Lead with the action or the answer.

**Workers are fully capable.** Full toolkit. The protocol is coordination,
not containment.

**Outbound to humans is orchestrator-only.** Workers stage drafts; the
orchestrator delivers. No worker should send email, SMS, or external messages.

**Disputes go to the principal verbatim.** Do not arbitrate.

**One worker per repo at a time.** If a worker is locked and a new task
touches its repo, queue or wait. Cross-repo conflicts surface.

**Crash recovery is automatic.** `clermes heal` (or `clermes spawn <name>`)
respawns with `claude -r <uuid>` from the saved session file. Conversation
history survives.

**Cron-friendly.** All operations are scriptable. Cron jobs can dispatch
into the fleet by calling `clermes send`.

## Honcho shared memory

The orchestrator and workers can share a memory substrate through a
self-hosted Honcho instance. See `docs/honcho.md` for setup, wiring, and
the cold-start and silent-tally patterns.

Key facts:

- **Two plugins, two config files, one server.** `~/.honcho/config.json`
  (Claude Code workers) and `~/.hermes/honcho.json` (Hermes/operator) must
  name the same workspace and same user peer for vectors to align.
- **Peer IDs are immutable.** No rename API. To change a peer name: clean
  slate in a new workspace.
- **Flat-file memory stays active.** `MEMORY.md` / `USER.md` is never
  replaced by Honcho. Keep hand-curating it as the zero-dependency fallback.
- **After changing `~/.honcho/config.json`, respawn the workers.**

## When NOT to use Clermes

- Trivial one-off questions the operator has the answer to locally.
- Read-only research with no durable output.
- Cron-driven jobs that do not need a long-lived agent.
- Tasks that touch multiple workers' repos at once (build the cross-cut
  on the orchestrator side first, then dispatch independent pieces).

## Pre-dispatch checklist

Before sending any non-trivial task:

1. **Task ID set?** Include `TASK_ID: YYYY-MM-DD-HHMM-<slug>` in the brief.
2. **Reversing a prior constraint?** State the supersession explicitly.
   Otherwise the auto-mode classifier may block the new approach.
3. **Interactive prompt risk?** Long briefs and tasks involving sensitive
   surfaces are more likely to trigger a multi-choice dialog the idle-detection
   hook will miss (pitfall 16). Do a manual `clermes capture <worker>` a minute
   or two after dispatch.
4. **Dispatch failed silently?** `clermes send` exit 1 with empty output
   usually means a bash pipefail issue in the dispatcher. Debug:
   ```bash
   bash -x ~/.clermes/clermes send <worker> "test ping" 2>&1 | tail -40
   ```

## Reference

- `~/.clermes/PROTOCOL.md`: full protocol contract
- `~/.clermes/config.yaml`: routing rules, outbound policy
- `docs/architecture.md`: system overview
- `docs/bell-detection.md`: bell pipeline end to end
- `docs/honcho.md`: Honcho integration
- `docs/recipes/`: worked examples
- `skills/clermes-dispatch/references/dispatcher-pitfalls.md`: full pitfall
  list with reproduction transcripts
