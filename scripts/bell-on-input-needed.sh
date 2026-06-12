#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Claude Code hook handler: rings the terminal bell on Notification and on Stop when last message ends with '?'.

set +e

input="$(cat)"

event="$(printf '%s' "$input" | jq -r '.hook_event_name // "unknown"' 2>/dev/null)"
if [ -z "$event" ]; then
    event="unknown"
fi

ring_bell() {
    { printf '\a' >/dev/tty; } 2>/dev/null || true
}

case "$event" in
    Notification)
        ring_bell
        ;;
    Stop)
        msg="$(printf '%s' "$input" | jq -r '.last_assistant_message // ""' 2>/dev/null)"
        # Strip trailing whitespace (spaces, tabs, newlines, carriage returns).
        trimmed="${msg%"${msg##*[![:space:]]}"}"
        case "$trimmed" in
            *\?)
                ring_bell
                ;;
        esac
        ;;
    *)
        :
        ;;
esac

exit 0
