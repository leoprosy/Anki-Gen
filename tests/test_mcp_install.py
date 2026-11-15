#!/usr/bin/env python3
"""
tests/test_mcp_install.py — Enregistrement du serveur MCP dans la config de Claude Desktop.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mcp_install  # noqa: E402


class Sandbox(unittest.TestCase):
    """APPDATA/LOCALAPPDATA redirigés, app « packagée », pas de CLI Claude Code."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-mcp-"))
        patches = [
            mock.patch.object(mcp_install, "APPDATA", self.tmp / "roaming"),
            mock.patch.object(mcp_install, "LOCALAPPDATA", self.tmp / "local"),
            mock.patch.object(mcp_install, "CLAUDE_CODE_CONFIG", self.tmp / ".claude.json"),
            mock.patch.object(mcp_install.paths, "is_frozen", return_value=True),
            mock.patch.object(mcp_install, "claude_cli", return_value=None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = self.tmp / "roaming" / "Claude" / "claude_desktop_config.json"


class McpInstallTest(Sandbox):

    def test_no_client_means_nothing_to_offer(self):
        self.assertEqual(mcp_install.status()["available"], False)

    def test_install_merges_and_status_follows(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
        self.assertEqual(mcp_install.status(), {"available": True, "installed": False,
                                                "clients": ["claude_desktop"]})

        result = mcp_install.install()

        self.assertEqual(result, {"installed": ["claude_desktop"], "errors": {}})
        data = json.loads(self.config.read_text())
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["mcpServers"]["other"], {"command": "x"})
        self.assertEqual(data["mcpServers"]["ankigen"], {"command": sys.executable, "args": ["--mcp"]})
        self.assertTrue(mcp_install.status()["installed"])

    def test_store_install_is_found(self):
        store = self.tmp / "local" / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
        store.mkdir(parents=True)
        mcp_install.install()
        self.assertTrue((store / "claude_desktop_config.json").is_file())

    def test_unreadable_config_is_left_untouched(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text("{ broken")
        result = mcp_install.install()
        self.assertEqual(result["installed"], [])
        self.assertIn("claude_desktop", result["errors"])
        self.assertEqual(self.config.read_text(), "{ broken")

    def test_source_checkout_never_offers(self):
        self.config.parent.mkdir(parents=True)
        with mock.patch.object(mcp_install.paths, "is_frozen", return_value=False):
            self.assertFalse(mcp_install.status()["available"])


class McpOfferPageTest(Sandbox):
    """Le panneau d'accueil : après le choix analytics, tant que rien n'est installé ni refusé."""

    def setUp(self):
        super().setUp()
        import app as web
        import settings
        for p in (mock.patch.object(settings, "SETTINGS_FILE", self.tmp / "settings.json"),
                  mock.patch.object(web, "analytics", mock.Mock(save_preferences=settings.save_settings))):
            p.start()
            self.addCleanup(p.stop)
        self.settings = settings
        self.client = web.app.test_client()
        self.config.parent.mkdir(parents=True)

    def page_offers(self):
        return 'id="mcp-offer"' in self.client.get("/").get_data(as_text=True)

    def test_offer_lifecycle(self):
        self.assertFalse(self.page_offers())            # le panneau analytics passe d'abord
        self.settings.save_settings({"analytics_decided": True})
        self.assertTrue(self.page_offers())
        self.assertTrue(self.client.post("/api/mcp").get_json()["installed"])
        self.assertFalse(self.page_offers())

    def test_decline_is_remembered(self):
        self.settings.save_settings({"analytics_decided": True})
        self.client.post("/api/settings", json={"mcp_prompt_dismissed": True})
        self.assertFalse(self.page_offers())


if __name__ == "__main__":
    unittest.main()
