# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for clermes.history."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clermes-history-")
        self.tmp_path = Path(self.tmp)
        self._env_patch = mock.patch.dict(os.environ, {"CLERMES_HOME": self.tmp})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_append_creates_file(self):
        from clermes.history import append, history_path
        self.assertFalse(history_path().exists())
        append({"type": "done", "task_id": "t1"})
        self.assertTrue(history_path().exists())
        content = history_path().read_text(encoding="utf-8").strip()
        obj = json.loads(content)
        self.assertEqual(obj["task_id"], "t1")

    def test_append_adds_ts_field(self):
        from clermes.history import append, history_path
        append({"type": "done"})
        obj = json.loads(history_path().read_text(encoding="utf-8").strip())
        self.assertIn("ts", obj)
        self.assertIsInstance(obj["ts"], float)

    def test_append_preserves_existing_ts(self):
        from clermes.history import append, history_path
        append({"type": "done", "ts": 9999.0})
        obj = json.loads(history_path().read_text(encoding="utf-8").strip())
        self.assertEqual(obj["ts"], 9999.0)

    def test_tail_returns_last_n(self):
        from clermes.history import append, tail
        for i in range(10):
            append({"seq": i})
        result = tail(3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["seq"], 7)
        self.assertEqual(result[2]["seq"], 9)

    def test_tail_on_empty_file_returns_empty(self):
        from clermes.history import tail
        self.assertEqual(tail(10), [])

    def test_grep_filters_by_predicate(self):
        from clermes.history import append, grep
        append({"type": "done", "task_id": "a"})
        append({"type": "dispute", "task_id": "b"})
        append({"type": "done", "task_id": "c"})
        result = grep(lambda e: e.get("type") == "done")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["task_id"], "a")
        self.assertEqual(result[1]["task_id"], "c")

    def test_grep_limit_caps_results(self):
        from clermes.history import append, grep
        for i in range(5):
            append({"type": "done", "seq": i})
        result = grep(lambda e: e.get("type") == "done", limit=2)
        self.assertEqual(len(result), 2)

    def test_malformed_lines_skipped_silently(self):
        from clermes.history import history_path, tail
        history_path().parent.mkdir(parents=True, exist_ok=True)
        history_path().write_text(
            'not-json\n{"type": "done", "ts": 1.0}\nbad{{\n',
            encoding="utf-8",
        )
        result = tail(10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "done")


if __name__ == "__main__":
    unittest.main()
