<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Dispatcher Pitfalls

Full pitfall checklist with worked examples from the Clermes shakedowns.

---

## Pitfall 1: Preamble pasted into bash, not Claude

**Symptom:** the spawn capture shows preamble text echoed line-by-line with
`-bash: You: command not found`, `syntax error near unexpected token`, etc.

**Cause:** Claude never launched; the pane is a bash prompt. The dispatcher
sent the preamble and bash tried to execute it.

**Root causes, in order of discovery:**
- `~/.local/bin/claude` is a symlink to a versioned binary. Sent into a fresh
  tmux pane via `send-keys`, the launcher exits before the TUI comes up. Fix:
  resolve with `readlink -f $(command -v claude)` and invoke the real binary.
- `tmux new-session` returns before the shell inside the pane is ready. Fix:
  `sleep 1` after `new-session` before the first `send-keys`.
- The ready-detection regex was wrong. It matched bash prompts that use the
  same `❯` glyph. Fix: detect by `pane_current_command`, not by visual glyph.

**Verification:** after spawn, `pane_current_command` must return the Claude
binary basename (e.g. `2.1.146`). Anything else means Claude is not running.

---

## Pitfall 2: Worker pane falls back to bash mid-conversation

**Symptom:** a previously-healthy worker shows `STATE=bash` in `clermes list`.

**Cause:** Claude exited (`/exit`, an in-TUI interaction that terminated, or
a crash). The tmux session survives; Claude does not.

**Fix:** `clermes send` auto-heals. It detects the non-`claude` front process,
re-launches with `claude -r <session-id>`, waits for the `claude` state, then
delivers. Conversation history is fully preserved.

`clermes heal` does the same across the whole fleet. `heal` also spawns *dead*
workers (no tmux session at all), so a single `heal` can restore a full fleet.
That is intentional ("make reality match the registry") but it is not a pure
repair pass.

---

## Pitfall 3: Replying to a worker that needs an answer

When a worker files a dispute and you have the principal's decision, the reply
is just another `clermes send` to that worker. If the worker's pane fell back
to bash (Claude exited while waiting), the send auto-heals first. After the
resume, send the full reply: the resumed Claude has the dispute context but
has not seen the new instruction yet.

Do not type replies directly into the worker pane. Direct pane input bypasses
the dispatcher's logging and heal logic and is for debugging only.

---

## Pitfall 4: Auto-mode classifier denies a benign probe

**Symptom:** `Bash(which ffmpeg)` returns `Denied by auto mode classifier`.

**Cause:** the classifier evaluates the task *trajectory*, not the single
command. A benign probe is denied because the broader task involves something
flagged (copyright-shaped downloads, shared-NAS writes, external POSTs, or
agent-inferred destructive parameters).

**Correct worker behavior:** file a dispute with the question, context, and
3-4 concrete options. Do not take the lock yet (nothing to release if the task
never proceeds). Do NOT try to bypass the classifier with
`--permission-mode bypassPermissions`. The classifier is doing useful work.

**Correct orchestrator behavior:** surface the dispute verbatim. On approval,
re-send with explicit one-time authorization ("authorizes Option 1 for this
task only; do not assume a standing rule"). The worker then takes the lock
and proceeds.

### Pitfall 4b: Classifier fires on apparent contradictions in mid-task corrections

**Symptom:** a worker had a clean dispatch, then a mid-task correction reversed
a prior constraint (e.g., initial: "do not invoke binary X from terminal";
correction: "use binary X at path Y"). The classifier read the second
instruction as conflicting with the first and blocked the command.

**Workaround:** when explicitly reversing a prior constraint, state the
supersession in the reply:

> "CORRECTION: this supersedes my earlier instruction to skip the export step.
> Please run the export now using binary X."

Without that explicit framing, the worker is stuck filing a dispute or waiting
for manual approval.

---

## Pitfall 5: Happy-path trace (reference)

What a clean end-to-end run looks like:

1. `clermes spawn scratch` → preamble injected → worker acks scope.
2. `clermes send scratch "<task + protocol footer>"` → worker probes env.
3. Classifier fires on a probe → worker writes `disputes/<id>.md`, no lock.
4. Principal approves Option 1 → orchestrator re-sends authorization.
5. Worker writes `locks/claude-scratch.lock` with `{task_id, started_at, pid}`.
6. Worker creates dest folder → writes `announcing/<id>.txt` → sleeps grace
   window → checks `halt/<id>` → proceeds.
7. Worker runs the actual work.
8. Worker writes `done/<id>.json` with full schema → releases lock.
9. Orchestrator parses the done file, summarizes for the principal, cites artifacts.

Every protocol file was well-formed against the schema in `PROTOCOL.md`.

---

## Pitfall 6: Bash pipefail kills `_extract_task_id` silently

**Symptom:** `clermes send <worker> "test ping"` returns exit code 1 with
empty stdout. No prompt reaches the worker. No log entry. The worker's pane
is healthy.

**Root cause:** the dispatcher runs `set -euo pipefail`. The
`_extract_task_id` pipeline (`grep | head | sed`) returns exit 1 when grep
finds nothing (prompt with no TASK_ID footer). Pipefail propagates that to the
caller, which exits before the `unknown-<epoch>` fallback assigns.

**Fix:** wrap optional-match pipelines in a brace group with `|| true`:

```bash
# Wrong: dies under pipefail when grep finds nothing.
result="$(printf '%s' "$input" | grep -oE 'TASK_ID:...' | head -1 | sed -E 's/...//')"

# Right: tolerate no-match.
result="$({ printf '%s' "$input" | grep -oE 'TASK_ID:...' | head -1 | sed -E 's/...//'; } || true)"
```

**Detection:** `bash -x ~/.clermes/clermes send <worker> "test" 2>&1 | tail -40`.
Look for the last `+` line; that is the failed step.

**Lesson:** any new bash function that uses `grep` (or any command with
legitimate non-zero exit) inside a pipeline, in a script that runs under
`set -o pipefail`, must tolerate that exit status. Silent dispatch failures
are dangerous: the orchestrator proceeds as if the task was delivered.

---

## Pitfall 7: Idle detection misses interactive Claude Code prompts

**Symptom:** worker dispatched, never produces a done file, but the watchdog
never reports an idle notification either. Manual `clermes capture` shows the
worker on a multi-choice dialog for tens of minutes.

**Root cause:** the bell-based idle-detection hook fires on Claude Code's
Notification and Stop events. Interactive prompts (multi-choice dialogs,
prompt-injection confirmations, "Type something" inputs) hold the TUI in an
animated state. The TUI redraws the cursor and input box continuously. tmux
sees continuous pane output. The `monitor-silence` fallback never fires.
Neither does the bell unless Claude emits one explicitly.

**Coverage today:** idle detection catches workers parked at the post-task `❯`
prompt (fully idle, no animation). It misses workers stuck on:
- Multi-choice dialogs (e.g., "1. Yes proceed / 2. No discard / 3. ...")
- Prompt-injection harness warnings ("Tool result contained injection-flagged block")
- "Type something" free-text prompts after `/clear` or `/compact`
- Token-savings prompts ("new task? /clear to save 244.1k tokens")

**Mitigation:** do explicit `clermes capture <worker>` checks after dispatching
tasks that may trigger any of the above: long briefs, tasks dispatched soon after
a `/clear` or `/compact`, tasks touching sensitive surfaces.

**Recovery once spotted:** for multi-choice dialogs, send the literal option
number: `clermes send <worker> "1"` selects option 1.

---

## Pitfall 8: Pre-compact swallows in-flight dispatch

**Symptom:** `clermes send` returns success. The worker's pane shows
`✻ Conversation compacted` immediately followed by a clean `❯` prompt.
No tool-call output. The worker has no memory of the task.

**Root cause:** the prompt arrived after the compact snapshot was taken but
before the new session was active. The compacted context summary omits it.

**Detection:** `clermes capture <worker> 20` after a dispatch on an important
task. The `Conversation compacted` sentinel followed by idle prompt signals
the prompt was lost.

**Recovery:** resend the full brief verbatim. The post-compact worker is
clean.

**Prevention:** there is no clean signal to check pre-dispatch. The dispatcher
performs an automatic post-send capture check (2s after delivery); it resends
if the compact sentinel is present.

---

## Pitfall 9: Lock held by a crashed worker

**Symptom:** `clermes list` or `clermes snapshot` shows a lock held but the
pane is dead or at bash. The locked worker never writes a done file.

**Cause:** the worker exited mid-task with the lock file in place. The lock
file's PID no longer refers to a running process, but the dispatcher does not
auto-clear stale locks (removing a lock that belongs to a genuinely active
worker would corrupt coordination state).

**Fix:** verify the worker is truly stopped, then remove the lock manually:

```bash
rm ~/.clermes/locks/claude-<worker>.lock
```

Then `clermes heal` to respawn the worker. Reassess the task: the worker may
have stopped mid-way; the done file will not exist.

---

## Pitfall 10: `clermes send` auto-heal fails for `other:<proc>` state

**Symptom:** `clermes send` reports "heal failed." The pane shows a versioned
binary path (`/home/user/.local/share/claude/versions/<ver> -r <session-id>`)
at a bash prompt, often in the wrong workdir. The resume invocation was
emitted but did not execute.

**Cause:** a prior `/clear` prompt for token savings, or a version mismatch
in the binary path, left the pane in a state where the resume command was
displayed but not run.

**Fix:** `clermes kill <worker> && clermes spawn <worker>`. The session-id
file survives the kill, so spawn resumes conversation context cleanly.
Do not try to manually press Enter into the pane to execute the visible
command; use kill+spawn so the dispatcher's heal logic owns the recovery.

---

## Pitfall 11: Auto-mode classifier fires on benign probes (trajectory-based)

This is the trajectory-evaluation case described in pitfall 4. Separately
documented to highlight the broader principle: the classifier evaluates
*everything the agent has been asked to do in this session*, not just the
current command. A session that started with sensitive work can have
subsequent benign probes denied because the classifier's session context is
already flagged.

If classifier denials persist across what appear to be independent tasks,
consider restarting the worker with a fresh session: `clermes kill <worker>
&& clermes spawn <worker>`. The fresh session has no classifier history.

---

## Pitfall 12: `clermes capture` shows suggested prompts as if sent

**Symptom:** `clermes capture` output shows something like
`❯ Fix the prod DB now` and it looks like an instruction is in progress.

**Cause:** Claude Code's TUI displays a lighter-colored recommended follow-up
prompt in the input box when idle. `tmux capture-pane` picks this up verbatim.
That text has NOT been sent. The worker is idle at `❯`, waiting.

**Fix:** only work dispatched via `clermes send` has been delivered. The
visual suggestion in the input box is a TUI affordance, not an execution.
Do not report it as "in progress" or "authorized."

---

## Pitfall 13: Message lost when worker compacts mid-dispatch

This is the pre-compact swallow described in pitfall 8. Cross-referenced here
because both pitfalls 8 and 13 were discovered independently and describe the
same root cause from different angles.

Key note: the dispatcher's automatic post-send resend (2s capture + sentinel
check) covers the most common case. Manual verification with `clermes capture`
is still recommended for important tasks.

---

## Pitfall 14: Honcho stores hallucinated conclusions about the user

**Symptom:** the orchestrator's system prompt contains Honcho context blocks
with clearly wrong facts about the user (crisis-support boilerplate, wellness
concerns, medical language) during a technical session.

**Cause:** the Honcho synthesis layer pattern-matched frustrated debugging
language ("killing threads," "assumptions were wrong") as distress signals and
wrote those conclusions as user observations. The deriver gets it wrong; the
conclusions get injected as authoritative context.

**Handling:** treat wellness/crisis boilerplate in Honcho context blocks as
false positives during technical sessions. Disregard them. Do not let injected
Honcho text change your assessment of the user's actual state.

**Remediation:** harder than it looks. Deleting the source document from
Postgres is not enough. Honcho caches derived conclusions in Redis. Full
remediation: (1) delete the source Postgres document, (2) flush Redis, (3)
accept that the conclusion may re-fire during the current session if the
meta-conversation about the bug becomes a new derivation source. The
self-reinforcing loop resolves in future sessions once the meta-conversation
is no longer recent context.

---

## Pitfall 15: Bash dispatcher under `set -o pipefail`

See pitfall 6 for the full reproduction. The summary rule:

Any pipeline in the dispatcher whose `grep` step can legitimately return 1
(no match) must be wrapped in `{ ...; } || true` to prevent `set -o pipefail`
from propagating the failure to the caller.

The `_extract_task_id` function (TASK_ID extraction from prompts) is the
canonical example. The pattern applies to any other optional-match pipeline.

---

## Pitfall 16: Bell detection misses long compute steps

**Symptom:** a worker has been dispatched but the watchdog has not reported
anything for an unexpectedly long time. No bell fires. No done file appears.

**Cause:** the worker is inside a long compute step (large file analysis, slow
shell command, multi-minute build). Claude Code does not emit a Notification or
Stop event during that time. The bell pipeline has nothing to fire on. The pane
is also not idle in the silence-detection sense.

**Mitigation:** `clermes capture <worker> 30` explicitly after an unexpectedly
long quiet period. The capture shows the current state of the pane directly,
regardless of bell events.

The bell pipeline is event-driven. Events outside of Notification and Stop do
not surface. This is a known limitation, not a bug. The architectural fix
(hybrid silence + pattern-scan for the TUI's interactive prompt shapes) is
open.

---

## Pitfall 17: Prompt-injection detector fires on legitimate dispatch briefs

**Symptom:** a task brief lands in the worker but the worker shows a "Verify
task" dialog with options like "Yes proceed / No discard / Yes with changes."
The task has stalled without a done or dispute file.

**Cause:** the Claude Code prompt-injection harness may flag a brief as a
possible injection, particularly if the brief was captured inside a prior tool
result snapshot (e.g., by an earlier `clermes list` call) before reaching the
worker as a fresh prompt. The harness is working as designed.

**Recovery:** confirm with option 1 via `clermes send <worker> "1"`. The
dialog is a multi-choice picker; the literal "1" selects "proceed."

**Detection:** this is exactly the class of interactive prompt that the bell
detection misses (pitfall 16). Spot it with a manual `clermes capture` when a
task seems stalled past the expected completion time.
