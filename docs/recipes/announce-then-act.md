<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Recipe: Announce-Then-Act

A worker is about to do something irreversible: push to a remote, deploy to
production, call an external API that writes. Before taking the action, it
writes an announcement, sleeps the grace window, checks for a halt file,
then proceeds. This gives the orchestrator and the principal a window to
abort.

## When to announce

**Announce before:**
- `git push` to a remote
- Deploying (any target: Cloudflare, Docker registry, cloud provider)
- Posting a webhook or calling an external API that writes
- Sending an email or SMS

**No announcement needed for:**
- Local file reads, writes, edits
- Local commits
- Scraping or fetching read-only data
- Builds that do not push output anywhere external
- Tests

## Step 1: Worker writes the announcement

```
~/.clermes/announcing/2026-05-21-1514-push-site.txt
```

Contents (single line):

```
2026-05-21T15:14:22Z claude-studio git push origin main grace=10s
```

Format: `<ISO timestamp> <worker> <action description> grace=<window>`.

The grace window defaults to the value in `~/.clermes/config.yaml`. Workers
should use that value; the `grace=` in the file is informational.

## Step 2: Worker sleeps the grace window

```bash
sleep 10
```

The exact duration comes from the config. 10 seconds is the default.
During this window, the orchestrator can abort.

## Step 3: Worker checks for a halt file

```bash
if [[ -f ~/.clermes/halt/2026-05-21-1514-push-site ]]; then
  echo "Action aborted by halt file."
  # Write done file with status=blocked, then stop.
  exit 0
fi
```

If no halt file exists, proceed.

## Step 4: Worker executes the action

```bash
git push origin main
```

Then writes the done file as normal.

## Orchestrator role during the grace window

The orchestrator learns about the announcement either from the next
`clermes_drain_events` call or from the cron watchdog:

```python
events = clermes_drain_events(types=["announce"])
# event.path == "~/.clermes/announcing/2026-05-21-1514-push-site.txt"
# event.content == "2026-05-21T15:14:22Z claude-studio git push origin main grace=10s"
```

If the principal says "abort":

```bash
touch ~/.clermes/halt/2026-05-21-1514-push-site
```

Or via the orchestrator:

```python
# The dispatcher does not expose a halt tool directly;
# use the Bash tool to write the halt file.
Bash(f"touch ~/.clermes/halt/2026-05-21-1514-push-site")
```

The halt file must be written before the grace window expires. With a 10-second
window, this requires the orchestrator to respond to the announcement within
the same cron minute it was written. For time-sensitive actions, lower the
watchdog cron interval or monitor the announcing directory directly.

## File paths in this example

| File | Written when |
|------|-------------|
| `~/.clermes/announcing/2026-05-21-1514-push-site.txt` | Worker before acting |
| `~/.clermes/halt/2026-05-21-1514-push-site` | Orchestrator / operator to abort |
| `~/.clermes/done/2026-05-21-1514-push-site.json` | Worker after action completes |

## Dispatcher behavior

`bin/clermes` does not enforce the announce-then-act pattern on behalf of
workers. The pattern is a protocol rule workers follow based on their startup
preamble and the task brief. The dispatcher writes to `assigned/<worker>` on
send and checks for halt files only when you use the `halt` subcommand.

Verification: if you want to confirm a worker followed the protocol, check
`events.jsonl` for the sequence `announce` followed by `done` for the same
task_id with timestamps separated by at least the grace window.
