<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Recipe: Parallel Dispatch

Dispatch independent tasks to multiple workers concurrently in one tool call.

## When to use this

Any time the work decomposes into per-worker tasks with no interdependencies.
Audits are the common case: "check the state of all three repos" fans out
cleanly. Do not use this pattern when one worker's output is an input for
another worker's task.

## Tool call

```python
clermes_dispatch_parallel(jobs=[
    {
        "worker": "ledger",
        "prompt": (
            "Audit the bill-analyzer project. Review recent commits, open issues, "
            "and the current test coverage. Write a summary to "
            "~/.clermes/done/TASK_ID.json on completion.\n\n"
            "TASK_ID: 2026-05-21-1437-audit-ledger\n"
            "On start: acquire ~/.clermes/locks/claude-ledger.lock.\n"
            "On completion: write ~/.clermes/done/2026-05-21-1437-audit-ledger.json.\n"
            "If decision needed: write dispute file and stop."
        ),
        "slug": "audit-ledger"
    },
    {
        "worker": "studio",
        "prompt": (
            "Audit the canopyworkshop.com site. Review the last 5 commits, "
            "check Lighthouse scores if available, and note any broken links. "
            "Write a summary on completion.\n\n"
            "TASK_ID: 2026-05-21-1438-audit-studio\n"
            "On start: acquire ~/.clermes/locks/claude-studio.lock.\n"
            "On completion: write ~/.clermes/done/2026-05-21-1438-audit-studio.json.\n"
            "If decision needed: write dispute file and stop."
        ),
        "slug": "audit-studio"
    },
    {
        "worker": "scratch",
        "prompt": (
            "Audit the scratch workspace. List any uncommitted changes, stale "
            "branches, or open tasks. Write a summary on completion.\n\n"
            "TASK_ID: 2026-05-21-1439-audit-scratch\n"
            "On start: acquire ~/.clermes/locks/claude-scratch.lock.\n"
            "On completion: write ~/.clermes/done/2026-05-21-1439-audit-scratch.json.\n"
            "If decision needed: write dispute file and stop."
        ),
        "slug": "audit-scratch"
    }
])
```

## Expected response

```json
{
  "jobs": [
    {"ok": true, "worker": "ledger",  "task_id": "2026-05-21-1437-audit-ledger", "stdout": "..."},
    {"ok": true, "worker": "studio",  "task_id": "2026-05-21-1438-audit-studio", "stdout": "..."},
    {"ok": true, "worker": "scratch", "task_id": "2026-05-21-1439-audit-scratch", "stdout": "..."}
  ]
}
```

All three sends happen in sequence within the tool call. The workers begin
executing concurrently in their tmux sessions.

## Watching for results

After dispatch, drain events as they arrive:

```python
# Poll until all three are done.
clermes_drain_events(types=["done", "dispute"])
```

Or wait and drain once:

```python
# Check manually after some time.
clermes_drain_events(peek=True)   # inspect without consuming
clermes_drain_events()            # consume when ready to handle
```

The watchdog (cron, every minute) also drains and delivers to the
orchestrator via stdout. Both paths are independent.

## Event flow back from workers

Each worker writes its done file when finished. The event flow per worker:

```
worker acquires lock
worker runs task
worker writes ~/.clermes/done/<task-id>.json   (status: done)
worker releases lock
watchdog picks up the done file
watchdog emits notification block to stdout
orchestrator receives done event
```

If a worker needs a decision before it can proceed, it writes
`~/.clermes/disputes/<task-id>.md` instead and stops. The drain events
call surfaces both types.

## After all three complete

```python
# Query history to see all three done events.
clermes_history(n=10, filter_type="done")
```

Read each done file for the summary and artifact list:

```bash
jq . ~/.clermes/done/2026-05-21-1437-audit-ledger.json
jq . ~/.clermes/done/2026-05-21-1438-audit-studio.json
jq . ~/.clermes/done/2026-05-21-1439-audit-scratch.json
```
