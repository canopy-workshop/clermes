# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for clermes.config."""

from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clermes-config-")
        self.tmp_path = Path(self.tmp)
        self._env_patch = mock.patch.dict(os.environ, {"CLERMES_HOME": self.tmp})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clermes_home_respects_env(self):
        from clermes.config import clermes_home
        self.assertEqual(clermes_home(), self.tmp_path)

    def test_defaults_loaded_when_no_file(self):
        from clermes.config import load_settings
        settings = load_settings()
        self.assertEqual(settings.dispatch.tmux_width, 200)
        self.assertEqual(settings.dispatch.tmux_height, 50)
        self.assertEqual(settings.dispatch.announce_grace_seconds, 10)
        self.assertAlmostEqual(settings.dispatch.context_compact_threshold, 0.70)

    def test_values_from_file_overlay_defaults(self):
        config = self.tmp_path / "config.yaml"
        config.write_text(textwrap.dedent("""\
            instance:
              name: test-instance
              principal: Tester
            dispatch:
              tmux_width: 240
              tmux_height: 60
              announce_grace_seconds: 15
              context_compact_threshold: 0.85
        """), encoding="utf-8")
        from clermes import config as cfg_module
        import importlib
        importlib.reload(cfg_module)
        settings = cfg_module.load_settings()
        self.assertEqual(settings.instance.name, "test-instance")
        self.assertEqual(settings.instance.principal, "Tester")
        self.assertEqual(settings.dispatch.tmux_width, 240)
        self.assertEqual(settings.dispatch.tmux_height, 60)
        self.assertEqual(settings.dispatch.announce_grace_seconds, 15)
        self.assertAlmostEqual(settings.dispatch.context_compact_threshold, 0.85)

    def test_env_var_override_dispatch_width(self):
        with mock.patch.dict(os.environ, {"CLERMES_DISPATCH_TMUX_WIDTH": "300"}):
            from clermes import config as cfg_module
            import importlib
            importlib.reload(cfg_module)
            settings = cfg_module.load_settings()
            self.assertEqual(settings.dispatch.tmux_width, 300)

    def test_env_var_override_instance_principal(self):
        with mock.patch.dict(os.environ, {"CLERMES_INSTANCE_PRINCIPAL": "operator"}):
            from clermes import config as cfg_module
            import importlib
            importlib.reload(cfg_module)
            settings = cfg_module.load_settings()
            self.assertEqual(settings.instance.principal, "operator")

    def test_routing_rules_loaded_from_file(self):
        config = self.tmp_path / "config.yaml"
        config.write_text(textwrap.dedent("""\
            routing:
              default_worker: scratch
              rules:
                studio: [wordmark, astro]
                ledger: [scraper, rag]
        """), encoding="utf-8")
        from clermes import config as cfg_module
        import importlib
        importlib.reload(cfg_module)
        settings = cfg_module.load_settings()
        self.assertEqual(settings.routing.default_worker, "scratch")
        self.assertIn("studio", settings.routing.rules)
        self.assertIn("wordmark", settings.routing.rules["studio"])


if __name__ == "__main__":
    unittest.main()
