#!/usr/bin/env python3
"""
tests/test_settings.py — Persistance et validation des préférences.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings  # noqa: E402


class SettingsTestCase(unittest.TestCase):
    """Redirige SETTINGS_FILE vers un dossier jetable : aucun test ne touche %APPDATA%."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-settings-"))
        self._original = settings.SETTINGS_FILE
        settings.SETTINGS_FILE = self.tmp / "settings.json"

    def tearDown(self):
        settings.SETTINGS_FILE = self._original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_raw(self, content):
        settings.SETTINGS_FILE.write_text(content, encoding="utf-8")


class TestDefaults(SettingsTestCase):
    def test_missing_file_yields_defaults(self):
        self.assertFalse(settings.SETTINGS_FILE.exists())
        loaded = settings.load_settings()
        self.assertEqual(loaded["language"], "en")
        self.assertEqual(loaded["deck_prefix"], "")
        self.assertTrue(loaded["download_dir"])

    def test_default_language_is_english(self):
        self.assertEqual(settings.defaults()["language"], "en")

    def test_default_deck_prefix_is_empty(self):
        self.assertEqual(settings.defaults()["deck_prefix"], "")


class TestCorruptionTolerance(SettingsTestCase):
    """Un fichier cassé ne doit jamais empêcher l'app de démarrer."""

    def test_invalid_json_yields_defaults(self):
        self.write_raw("{ this is not json")
        self.assertEqual(settings.load_settings(), settings.defaults())

    def test_json_list_instead_of_object_yields_defaults(self):
        self.write_raw('["nope"]')
        self.assertEqual(settings.load_settings(), settings.defaults())

    def test_empty_file_yields_defaults(self):
        self.write_raw("")
        self.assertEqual(settings.load_settings(), settings.defaults())


class TestValidation(SettingsTestCase):
    def test_unknown_language_falls_back_without_touching_other_keys(self):
        self.write_raw(json.dumps({"language": "klingon", "deck_prefix": "Econ"}))
        loaded = settings.load_settings()
        self.assertEqual(loaded["language"], "en")
        self.assertEqual(loaded["deck_prefix"], "Econ")

    def test_wrong_type_falls_back_for_that_key_only(self):
        self.write_raw(json.dumps({"deck_prefix": 42, "language": "fr"}))
        loaded = settings.load_settings()
        self.assertEqual(loaded["deck_prefix"], "")
        self.assertEqual(loaded["language"], "fr")

    def test_unknown_keys_are_dropped(self):
        self.write_raw(json.dumps({"language": "fr", "sekret": "x"}))
        self.assertNotIn("sekret", settings.load_settings())

    def test_nonexistent_download_dir_is_kept_as_typed(self):
        # On ne réécrit pas silencieusement la saisie de l'utilisateur ; c'est
        # resolve_download_dir() qui juge de l'utilisabilité.
        typed = str(self.tmp / "does-not-exist-yet")
        self.write_raw(json.dumps({"download_dir": typed}))
        self.assertEqual(settings.load_settings()["download_dir"], typed)

    def test_blank_download_dir_falls_back_to_default(self):
        self.write_raw(json.dumps({"download_dir": "   "}))
        self.assertEqual(
            settings.load_settings()["download_dir"], settings.defaults()["download_dir"]
        )


class TestSave(SettingsTestCase):
    def test_round_trip(self):
        settings.save_settings({"language": "fr", "deck_prefix": "ESH"})
        loaded = settings.load_settings()
        self.assertEqual(loaded["language"], "fr")
        self.assertEqual(loaded["deck_prefix"], "ESH")

    def test_partial_save_preserves_other_keys(self):
        settings.save_settings({"language": "fr", "deck_prefix": "ESH"})
        settings.save_settings({"language": "en"})
        loaded = settings.load_settings()
        self.assertEqual(loaded["language"], "en")
        self.assertEqual(loaded["deck_prefix"], "ESH")

    def test_save_returns_the_full_state(self):
        returned = settings.save_settings({"deck_prefix": "Bio"})
        self.assertEqual(set(returned), set(settings.defaults()))
        self.assertEqual(returned["deck_prefix"], "Bio")

    def test_save_leaves_no_temporary_file_behind(self):
        settings.save_settings({"language": "fr"})
        leftovers = [p.name for p in self.tmp.iterdir() if p.name != "settings.json"]
        self.assertEqual(leftovers, [])

    def test_deck_prefix_is_stripped(self):
        settings.save_settings({"deck_prefix": "  Econ  "})
        self.assertEqual(settings.load_settings()["deck_prefix"], "Econ")


class TestResolveDownloadDir(SettingsTestCase):
    def test_returns_the_directory_when_usable(self):
        target = self.tmp / "exports"
        target.mkdir()
        settings.save_settings({"download_dir": str(target)})
        self.assertEqual(settings.resolve_download_dir(), target)

    def test_creates_a_missing_directory(self):
        target = self.tmp / "made-on-demand"
        settings.save_settings({"download_dir": str(target)})
        self.assertEqual(settings.resolve_download_dir(), target)
        self.assertTrue(target.is_dir())

    def test_returns_none_when_the_path_is_a_file(self):
        target = self.tmp / "a-file.txt"
        target.write_text("x", encoding="utf-8")
        settings.save_settings({"download_dir": str(target)})
        self.assertIsNone(settings.resolve_download_dir())


class TestCheckDir(SettingsTestCase):
    def test_existing_directory_is_ok(self):
        ok, key = settings.check_dir(str(self.tmp))
        self.assertTrue(ok)
        self.assertEqual(key, "settings.dir_ok")

    def test_blank_path_is_rejected(self):
        ok, key = settings.check_dir("   ")
        self.assertFalse(ok)
        self.assertEqual(key, "settings.dir_blank")

    def test_path_pointing_at_a_file_is_rejected(self):
        target = self.tmp / "a-file.txt"
        target.write_text("x", encoding="utf-8")
        ok, key = settings.check_dir(str(target))
        self.assertFalse(ok)
        self.assertEqual(key, "settings.dir_not_a_folder")


if __name__ == "__main__":
    unittest.main()
