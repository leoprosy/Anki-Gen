#!/usr/bin/env python3
"""
tests/test_mcp_server.py — Serveur MCP stdio : protocole et outils frise, dans un dossier jetable.

    .venv/Scripts/python.exe -m unittest tests.test_mcp_server
"""

import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mcp_server  # noqa: E402
import settings  # noqa: E402
import timeline_store  # noqa: E402

FIXTURE = (ROOT / "tests" / "fixtures_timeline" / "mondialisation.json").read_text(encoding="utf-8")


class TestMcpServer(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="ankigen-mcp-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "timelines").mkdir()
        for target, name, value in ((timeline_store, "TIMELINES_DIR", tmp / "timelines"),
                                    (settings, "SETTINGS_FILE", tmp / "settings.json")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        settings.save_settings({"language": "fr", "analytics_decided": True})

    def rpc(self, *messages):
        out = io.BytesIO()
        mcp_server.serve(io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in messages)), out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def call(self, name, **arguments):
        reply, = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}})
        return reply["result"]

    def test_handshake_skips_notifications(self):
        replies = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                           {"jsonrpc": "2.0", "method": "notifications/initialized"},
                           {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual([r["id"] for r in replies], [1, 2])
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "ankigen")
        self.assertIn("create_timeline", {t["name"] for t in replies[1]["result"]["tools"]})

    def test_create_timeline_then_list(self):
        created = self.call("create_timeline", json_document=FIXTURE)
        self.assertFalse(created["isError"], created)
        tid = json.loads(created["content"][0]["text"])["id"]
        self.assertIn(tid, self.call("list_timelines")["content"][0]["text"])

    def test_invalid_timeline_is_an_error_with_report(self):
        result = self.call("create_timeline", json_document="{not json")
        self.assertTrue(result["isError"])
        self.assertTrue(result["content"][0]["text"])

    def test_set_deck_prefix_rewrites_every_deck(self):
        import project_store
        tmp = Path(tempfile.mkdtemp(prefix="ankigen-mcp-proj-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        patcher = mock.patch.object(project_store, "project_path", lambda pid: tmp / f"{pid}.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        project_store.save_project("p", {"deck_prefix": "ESH", "prompts": [
            {"id": 0, "deck": "ESH::CH1::I"}, {"id": 1, "deck": "ESH::CH1::II"}]})

        result = self.call("set_deck_prefix", project_id="p", deck_prefix="Éco::Prépa")
        self.assertFalse(result["isError"], result)
        self.assertEqual([p["deck"] for p in project_store.load_project("p")["prompts"]],
                         ["Éco::Prépa::CH1::I", "Éco::Prépa::CH1::II"])

        self.call("set_deck_prefix", project_id="p", deck_prefix="")
        project = project_store.load_project("p")
        self.assertEqual((project["deck_prefix"], project["prompts"][0]["deck"]), ("", "CH1::I"))
        self.assertTrue(self.call("set_deck_prefix", project_id="nope", deck_prefix="x")["isError"])

    def test_unknown_tool_and_bad_arguments(self):
        reply, = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope"}})
        self.assertIn("error", reply)
        self.assertTrue(self.call("save_cards", wrong=1)["isError"])


if __name__ == "__main__":
    unittest.main()
