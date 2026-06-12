# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for clermes.events."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


class EventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clermes-events-")
        self.tmp_path = Path(self.tmp)
        for sub in ("done", "disputes", "announcing", "idle-queue", "state"):
            (self.tmp_path / sub).mkdir(parents=True)
        self._env_patch = mock.patch.dict(os.environ, {"CLERMES_HOME": self.tmp})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_done(self, task_id: str, worker: str = "scratch", status: str = "done") -> Path:
        path = self.tmp_path / "done" / f"{task_id}.json"
        path.write_text(json.dumps({
            "task_id": task_id,
            "worker": worker,
            "status": status,
            "result": "ok",
        }), encoding="utf-8")
        return path

    def _write_dispute(self, task_id: str, body: str = "Q?") -> Path:
        path = self.tmp_path / "disputes" / f"{task_id}.md"
        path.write_text(body, encoding="utf-8")
        return path

    def _write_idle(self, ts_ns: int, worker: str, task_id: str) -> Path:
        path = self.tmp_path / "idle-queue" / f"{ts_ns}-{worker}.json"
        path.write_text(json.dumps({
            "worker": worker,
            "task_id": task_id,
            "pane_tail": "...",
        }), encoding="utf-8")
        return path

    def test_scan_returns_all_event_types_ordered_by_mtime(self):
        from clermes import events
        self._write_done("a")
        time.sleep(0.01)
        self._write_dispute("b")
        time.sleep(0.01)
        self._write_idle(int(time.time() * 1e9), "scratch", "c")
        out = events.scan()
        self.assertEqual(len(out), 3)
        self.assertEqual([e.type for e in out], ["done", "dispute", "idle"])

    def test_drain_advances_cursor(self):
        from clermes import events
        first_path = self._write_done("first")
        os.utime(first_path, (1000.0, 1000.0))
        first_drain = events.drain()
        self.assertEqual(len(first_drain), 1)
        second_drain = events.drain()
        self.assertEqual(len(second_drain), 0)
        second_path = self._write_dispute("second")
        os.utime(second_path, (2000.0, 2000.0))
        third_drain = events.drain()
        self.assertEqual(len(third_drain), 1)
        self.assertEqual(third_drain[0].type, "dispute")

    def test_peek_does_not_advance_cursor(self):
        from clermes import events
        self._write_done("first")
        peeked = events.scan()
        self.assertEqual(len(peeked), 1)
        again = events.drain(advance_cursor=False)
        self.assertEqual(len(again), 1)
        third = events.drain(advance_cursor=False)
        self.assertEqual(len(third), 1)

    def test_types_filter(self):
        from clermes import events
        self._write_done("a")
        self._write_dispute("b")
        out = events.scan(types=["done"])
        self.assertEqual([e.type for e in out], ["done"])

    def test_done_event_parses_body(self):
        from clermes import events
        self._write_done("alpha", worker="ledger", status="blocked")
        out = events.scan(types=["done"])
        self.assertEqual(out[0].task_id, "alpha")
        self.assertEqual(out[0].worker, "ledger")
        self.assertEqual(out[0].body["status"], "blocked")

    def test_file_extension_filter_ignores_non_json_in_done(self):
        from clermes import events
        # A .txt file in done/ should not surface as an event.
        stray = self.tmp_path / "done" / "stray.txt"
        stray.write_text("ignored", encoding="utf-8")
        out = events.scan(types=["done"])
        self.assertEqual(len(out), 0)

    def test_announce_event_parses_worker(self):
        from clermes import events
        # Body format: "<task_id> <worker> <action...>"
        path = self.tmp_path / "announcing" / "abc123.txt"
        path.write_text("abc123 scratch git push", encoding="utf-8")
        out = events.scan(types=["announce"])
        self.assertEqual(len(out), 1)
        ev = out[0]
        self.assertEqual(ev.type, "announce")
        self.assertEqual(ev.task_id, "abc123")
        self.assertEqual(ev.worker, "scratch")
        self.assertEqual(ev.body, "abc123 scratch git push")

    def test_announce_event_single_word_body_does_not_crash(self):
        from clermes import events
        # A file with only one word cannot yield a worker -- should return
        # an event with worker=None rather than raising.
        path = self.tmp_path / "announcing" / "xyz.txt"
        path.write_text("onlyoneword", encoding="utf-8")
        out = events.scan(types=["announce"])
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0].worker)
        self.assertEqual(out[0].task_id, "xyz")


if __name__ == "__main__":
    unittest.main()
