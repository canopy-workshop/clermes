# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for clermes.registry."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clermes-registry-")
        self.tmp_path = Path(self.tmp)
        self._env_patch = mock.patch.dict(os.environ, {"CLERMES_HOME": self.tmp})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_worker(self, name: str = "scratch") -> dict:
        return {
            "workdir": f"/tmp/{name}",
            "owns": f"Domain for {name}",
            "tmux_session": f"claude-{name}",
            "session_id": None,
        }

    def test_empty_registry_on_missing_file(self):
        from clermes.registry import read_registry
        data = read_registry()
        self.assertEqual(data, {"workers": {}})

    def test_round_trip_read_write(self):
        from clermes.registry import read_registry, write_registry
        payload = {
            "workers": {
                "scratch": self._make_worker("scratch"),
            }
        }
        write_registry(payload)
        result = read_registry()
        self.assertEqual(result["workers"]["scratch"]["tmux_session"], "claude-scratch")

    def test_jsonschema_rejects_bad_shape(self):
        from clermes.registry import write_registry
        bad = {"workers": {"oops": {"workdir": "/tmp"}}}
        with self.assertRaises(jsonschema.ValidationError):
            write_registry(bad)

    def test_update_worker_mutates_one_entry(self):
        from clermes.registry import read_registry, update_worker, write_registry
        initial = {
            "workers": {
                "scratch": self._make_worker("scratch"),
                "ledger": self._make_worker("ledger"),
            }
        }
        write_registry(initial)
        update_worker("scratch", session_id="abc-123")
        result = read_registry()
        self.assertEqual(result["workers"]["scratch"]["session_id"], "abc-123")
        # ledger entry must be untouched
        self.assertIsNone(result["workers"]["ledger"]["session_id"])

    def test_worker_names_sorted(self):
        from clermes.registry import worker_names, write_registry
        payload = {
            "workers": {
                "zebra": self._make_worker("zebra"),
                "alpha": self._make_worker("alpha"),
                "middle": self._make_worker("middle"),
            }
        }
        write_registry(payload)
        self.assertEqual(worker_names(), ["alpha", "middle", "zebra"])

    def test_atomic_write_uses_tmp_then_replace(self):
        """Write should leave no .tmp file behind."""
        from clermes.registry import registry_path, write_registry
        payload = {"workers": {"scratch": self._make_worker()}}
        write_registry(payload)
        tmp_file = registry_path().with_suffix(".json.tmp")
        self.assertFalse(tmp_file.exists())
        self.assertTrue(registry_path().exists())


if __name__ == "__main__":
    unittest.main()
