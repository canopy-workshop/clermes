# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the hermes plugin tools module (handlers, schema, helpers)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clermes-tools-")
        self.tmp_path = Path(self.tmp)
        self._env_patch = mock.patch.dict(os.environ, {"CLERMES_HOME": self.tmp})
        self._env_patch.start()
        # Re-import after env is set so clermes_home() resolves to tmp
        import importlib
        import clermes.config
        import clermes.events
        import clermes.history
        import clermes.routing
        importlib.reload(clermes.config)
        importlib.reload(clermes.events)
        importlib.reload(clermes.history)
        importlib.reload(clermes.routing)
        from plugins.hermes import dispatcher, tools
        importlib.reload(dispatcher)
        importlib.reload(tools)
        self.tools = tools
        self.dispatcher = dispatcher

    def tearDown(self):
        self._env_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # Helper tests
    # ------------------------------------------------------------------

    def test_ensure_task_id_appends_when_missing(self):
        """_ensure_task_id appends TASK_ID when the prompt lacks one."""
        out = self.tools._ensure_task_id("Do the thing", "slug-here")
        self.assertIn("TASK_ID:", out)
        self.assertIn("slug-here", out)

    def test_ensure_task_id_preserves_existing(self):
        """_ensure_task_id leaves prompt unchanged when TASK_ID already present."""
        prompt = "Do the thing\nTASK_ID: pre-existing-id"
        out = self.tools._ensure_task_id(prompt, "ignored")
        self.assertEqual(out, prompt)
        self.assertNotIn("ignored", out)

    def test_slugify_cleans_text(self):
        """_slugify lowercases, strips punctuation, falls back to 'task'."""
        self.assertEqual(self.tools._slugify("Hello World! 2026"), "hello-world-2026")
        self.assertEqual(self.tools._slugify(""), "task")

    # ------------------------------------------------------------------
    # handle_send validation
    # ------------------------------------------------------------------

    def test_handle_send_requires_worker(self):
        """handle_send returns ok=False when worker is missing."""
        result = json.loads(self.tools.handle_send({"prompt": "test"}))
        self.assertFalse(result["ok"])
        self.assertIn("worker", result["error"])

    def test_handle_send_requires_prompt(self):
        """handle_send returns ok=False when prompt is missing."""
        result = json.loads(self.tools.handle_send({"worker": "scratch"}))
        self.assertFalse(result["ok"])
        self.assertIn("prompt", result["error"])

    def test_handle_send_invokes_dispatcher(self):
        """handle_send calls dispatcher.send and returns ok=True with a task_id."""
        fake_result = self.dispatcher.DispatcherResult(
            ok=True, stdout="scratch: sent (123 chars)", stderr="", returncode=0
        )
        with mock.patch.object(self.dispatcher, "send", return_value=fake_result) as m:
            raw = self.tools.handle_send(
                {"worker": "scratch", "prompt": "do work", "slug": "do-work"}
            )
        parsed = json.loads(raw)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["worker"], "scratch")
        self.assertIn("do-work", parsed["task_id"])
        m.assert_called_once()
        called_prompt = m.call_args[0][1]
        self.assertIn("TASK_ID:", called_prompt)
        self.assertIn("do-work", called_prompt)

    # ------------------------------------------------------------------
    # handle_dispatch_parallel
    # ------------------------------------------------------------------

    def test_dispatch_parallel_handles_multiple(self):
        """handle_dispatch_parallel sends all jobs and returns per-worker results."""
        fake = self.dispatcher.DispatcherResult(ok=True, stdout="ok", stderr="", returncode=0)
        with mock.patch.object(self.dispatcher, "send", return_value=fake):
            raw = self.tools.handle_dispatch_parallel(
                {
                    "jobs": [
                        {"worker": "a", "prompt": "p1", "slug": "j1"},
                        {"worker": "b", "prompt": "p2", "slug": "j2"},
                    ]
                }
            )
        parsed = json.loads(raw)
        self.assertEqual(len(parsed["jobs"]), 2)
        self.assertTrue(all(j["ok"] for j in parsed["jobs"]))

    # ------------------------------------------------------------------
    # handle_pick_worker
    # ------------------------------------------------------------------

    def test_handle_pick_worker_returns_correct_worker(self):
        """handle_pick_worker routes correctly given config.yaml routing rules."""
        (self.tmp_path / "config.yaml").write_text(
            textwrap.dedent("""\
            routing:
              default_worker: scratch
              rules:
                studio: [wordmark, astro, brand]
                ledger: [scraper, rag, fastapi]
            """),
            encoding="utf-8",
        )
        import importlib
        import clermes.config
        import clermes.routing
        importlib.reload(clermes.config)
        importlib.reload(clermes.routing)
        importlib.reload(self.tools)

        raw = self.tools.handle_pick_worker({"task": "Tweak the wordmark margin for the brand site"})
        parsed = json.loads(raw)
        self.assertEqual(parsed["worker"], "studio")
        self.assertFalse(parsed["ambiguous"])

    # ------------------------------------------------------------------
    # handle_drain_events
    # ------------------------------------------------------------------

    def test_handle_drain_events_advances_cursor(self):
        """handle_drain_events advances cursor when peek=false."""
        done_dir = self.tmp_path / "done"
        done_dir.mkdir(parents=True)
        ev_path = done_dir / "task-abc.json"
        ev_path.write_text(
            json.dumps({"task_id": "task-abc", "worker": "studio"}), encoding="utf-8"
        )
        # Pin mtime to a known value so the cursor comparison is deterministic
        # under coarse-resolution filesystems.
        os.utime(ev_path, (1000.0, 1000.0))
        # First drain: should find the event and advance cursor
        raw = self.tools.handle_drain_events({"peek": False})
        parsed = json.loads(raw)
        self.assertTrue(parsed["cursor_advanced"])
        self.assertGreater(parsed["count"], 0)

        # Second drain without peek: cursor advanced, no new events
        raw2 = self.tools.handle_drain_events({"peek": False})
        parsed2 = json.loads(raw2)
        self.assertEqual(parsed2["count"], 0)
        self.assertFalse(parsed2["cursor_advanced"])

    # ------------------------------------------------------------------
    # handle_history
    # ------------------------------------------------------------------

    def _write_events(self, entries):
        """Write entries to events.jsonl in the temp home."""
        log_path = self.tmp_path / "events.jsonl"
        with log_path.open("a", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry) + "\n")

    def test_handle_history_returns_last_n(self):
        """handle_history returns up to n recent events from events.jsonl."""
        self._write_events([
            {"ts": 1.0, "event": "task_done", "worker": "studio", "task_id": "t1"},
            {"ts": 2.0, "event": "task_done", "worker": "ledger",  "task_id": "t2"},
            {"ts": 3.0, "event": "dispute",   "worker": "studio", "task_id": "t3"},
        ])
        import importlib
        import clermes.history
        importlib.reload(clermes.history)
        importlib.reload(self.tools)

        raw = self.tools.handle_history({"n": 2})
        parsed = json.loads(raw)
        self.assertEqual(parsed["count"], 2)
        self.assertEqual(len(parsed["events"]), 2)
        # tail(2) returns the last 2 entries (ts 2.0 and ts 3.0)
        task_ids = [e["task_id"] for e in parsed["events"]]
        self.assertIn("t2", task_ids)
        self.assertIn("t3", task_ids)

    def test_handle_history_type_filter(self):
        """handle_history filters by the 'event' field when filter_type is given."""
        self._write_events([
            {"ts": 1.0, "event": "task_done", "worker": "studio", "task_id": "t1"},
            {"ts": 2.0, "event": "dispute",   "worker": "studio", "task_id": "t2"},
            {"ts": 3.0, "event": "task_done", "worker": "ledger",  "task_id": "t3"},
        ])
        import importlib
        import clermes.history
        importlib.reload(clermes.history)
        importlib.reload(self.tools)

        raw = self.tools.handle_history({"n": 20, "filter_type": "dispute"})
        parsed = json.loads(raw)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["events"][0]["event"], "dispute")

    def test_handle_history_worker_filter(self):
        """handle_history filters by the 'worker' field when filter_worker is given."""
        self._write_events([
            {"ts": 1.0, "event": "task_done", "worker": "studio", "task_id": "t1"},
            {"ts": 2.0, "event": "task_done", "worker": "ledger",  "task_id": "t2"},
            {"ts": 3.0, "event": "task_done", "worker": "studio", "task_id": "t3"},
        ])
        import importlib
        import clermes.history
        importlib.reload(clermes.history)
        importlib.reload(self.tools)

        raw = self.tools.handle_history({"n": 20, "filter_worker": "studio"})
        parsed = json.loads(raw)
        self.assertEqual(parsed["count"], 2)
        for ev in parsed["events"]:
            self.assertEqual(ev["worker"], "studio")

    def test_handle_history_type_and_worker_filters_compose(self):
        """Both filters together: only events matching event AND worker pass."""
        self._write_events([
            {"ts": 1.0, "event": "task_done", "worker": "studio", "task_id": "t1"},
            {"ts": 2.0, "event": "dispute",   "worker": "studio", "task_id": "t2"},
            {"ts": 3.0, "event": "task_done", "worker": "ledger",  "task_id": "t3"},
        ])
        import importlib
        import clermes.history
        importlib.reload(clermes.history)
        importlib.reload(self.tools)

        raw = self.tools.handle_history(
            {"n": 20, "filter_type": "task_done", "filter_worker": "studio"}
        )
        parsed = json.loads(raw)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["events"][0]["task_id"], "t1")

    # ------------------------------------------------------------------
    # TOOLS tuple coverage
    # ------------------------------------------------------------------

    def test_tools_tuple_contains_all_ten(self):
        """TOOLS tuple must contain all 10 locked tool names."""
        expected = {
            "clermes_list",
            "clermes_snapshot",
            "clermes_send",
            "clermes_capture",
            "clermes_spawn",
            "clermes_heal",
            "clermes_pick_worker",
            "clermes_dispatch_parallel",
            "clermes_drain_events",
            "clermes_history",
        }
        names = {entry[0] for entry in self.tools.TOOLS}
        self.assertEqual(names, expected)


if __name__ == "__main__":
    unittest.main()
