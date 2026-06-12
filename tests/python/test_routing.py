# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for clermes.routing."""

from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


def _stub_config(tmpdir: Path, body: str) -> None:
    (tmpdir / "config.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clermes-routing-")
        self.tmp_path = Path(self.tmp)
        self._env_patch = mock.patch.dict(os.environ, {"CLERMES_HOME": self.tmp})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pick_best_unique_keyword(self):
        from clermes import routing
        _stub_config(self.tmp_path, """
        routing:
          default_worker: scratch
          rules:
            studio: [wordmark, astro, brand]
            ledger: [scraper, rag, fastapi]
        """)
        result = routing.pick("Tweak the wordmark margin for the brand site")
        self.assertEqual(result.worker, "studio")
        self.assertFalse(result.ambiguous)
        self.assertFalse(result.used_default)
        self.assertEqual(result.score, 2)

    def test_pick_ambiguous_tie(self):
        from clermes import routing
        _stub_config(self.tmp_path, """
        routing:
          default_worker: scratch
          rules:
            studio: [astro, brand]
            site: [astro, brand]
        """)
        result = routing.pick("Update the astro brand pages")
        self.assertTrue(result.ambiguous)
        self.assertIsNone(result.worker)
        self.assertEqual(set(result.candidates.keys()), {"studio", "site"})

    def test_pick_falls_back_to_default(self):
        from clermes import routing
        _stub_config(self.tmp_path, """
        routing:
          default_worker: scratch
          rules:
            studio: [wordmark]
        """)
        result = routing.pick("Take some random unrelated chore")
        self.assertEqual(result.worker, "scratch")
        self.assertTrue(result.used_default)
        self.assertEqual(result.score, 0)

    def test_pick_no_match_no_default(self):
        from clermes import routing
        _stub_config(self.tmp_path, """
        routing:
          rules:
            studio: [wordmark]
        """)
        result = routing.pick("Take some random unrelated chore")
        self.assertIsNone(result.worker)
        self.assertFalse(result.ambiguous)
        self.assertFalse(result.used_default)

    def test_routing_rules_lowercases_keywords(self):
        from clermes import routing
        _stub_config(self.tmp_path, """
        routing:
          rules:
            studio: [Wordmark, ASTRO]
        """)
        rules = routing.routing_rules()
        self.assertEqual(rules["studio"], ["wordmark", "astro"])

    def test_route_result_as_dict(self):
        from clermes.routing import RouteResult
        r = RouteResult(worker="studio", score=2, ambiguous=False,
                        candidates={"studio": 2}, used_default=False)
        d = r.as_dict()
        self.assertEqual(d["worker"], "studio")
        self.assertEqual(d["score"], 2)
        self.assertFalse(d["ambiguous"])


if __name__ == "__main__":
    unittest.main()
