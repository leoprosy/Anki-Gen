#!/usr/bin/env python3
"""
tests/test_build_payload.py — Contenu d'app.zip et de l'app_bundle de l'exe.

Ce payload était décrit par trois listes tenues à la main. Il est désormais
calculé depuis les imports : ces tests vérifient que le calcul retrouve tout ce
que l'app charge, y compris un import caché dans une fonction, et rien d'autre.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_app_payload import (  # noqa: E402
    DATA_DIRS, ENTRY_POINTS, build_payload, local_modules, write_zip,
)
from runtime_contract import runtime_version  # noqa: E402

# Les modules qu'énuméraient flask-server.spec et les deux workflows avant le
# calcul automatique : aucun ne doit disparaître du payload.
HISTORICAL_MODULES = {
    "app.py", "launcher.py", "parse_cours.py", "build_anki_csv.py",
    "docx_blocks.py", "media_store.py", "render.py", "paths.py",
    "project_store.py", "updater.py", "settings.py", "i18n.py",
    "telemetry.py", "analytics_config.py",
}


class TestLocalModules(unittest.TestCase):
    def test_finds_every_module_the_hand_written_lists_had(self):
        self.assertLessEqual(HISTORICAL_MODULES, set(local_modules()))

    def test_ships_the_runtime_probe(self):
        self.assertIn("runtime_probe.py", local_modules())

    def test_ships_the_timeline_modules_imported_by_routes(self):
        # Importés dans les routes (une frise cassée ne bloque pas le démarrage) :
        # ils doivent partir quand même dans app.zip et dans l'exe.
        modules = set(local_modules())
        self.assertLessEqual({"timeline_dates.py", "timeline_schema.py", "timeline_store.py",
                              "timeline_layout.py", "timeline_fonts.py", "timeline_render_svg.py",
                              "timeline_prompt.py", "timeline_extract.py", "timeline_merge.py",
                              "timeline_quotes.py"}, modules)
        # Le raster sert à la galerie ; les routes ne l'importent qu'avec les exports.
        self.assertNotIn("timeline_render_raster.py", modules)

    def test_leaves_out_scripts_notes_and_tests(self):
        modules = set(local_modules())
        # new_version.py est une note markdown : elle ne doit jamais partir chez l'utilisateur.
        self.assertNotIn("new_version.py", modules)
        self.assertFalse(any(name.startswith("test_") for name in modules))
        self.assertTrue(all("/" not in name and "\\" not in name for name in modules))


class TestDiscoveryOnAFakeRepo(unittest.TestCase):
    """Le calcul lui-même, sur un dépôt miniature entièrement maîtrisé."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ankigen-payload-"))
        for entry in ENTRY_POINTS:
            (self.root / entry).write_text("", encoding="utf-8")
        (self.root / "app.py").write_text(
            "import json\nimport eager\n\ndef route():\n    import lazy\n", encoding="utf-8")
        (self.root / "eager.py").write_text("from nested import helper\n", encoding="utf-8")
        (self.root / "nested.py").write_text("def helper():\n    pass\n", encoding="utf-8")
        (self.root / "lazy.py").write_text("import PIL.ImageFont\n", encoding="utf-8")
        (self.root / "orphan.py").write_text("", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_follows_eager_transitive_and_function_level_imports(self):
        modules = set(local_modules(self.root))
        self.assertLessEqual({"eager.py", "nested.py", "lazy.py"}, modules)

    def test_ignores_unreachable_files_and_non_local_imports(self):
        modules = set(local_modules(self.root))
        self.assertNotIn("orphan.py", modules)
        self.assertNotIn("json.py", modules)


class TestBuildPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-payload-"))
        self.dest = self.tmp / "app"
        self.manifest = build_payload(self.dest, "9.8.7", "abc123")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_manifest_carries_the_runtime_contract(self):
        on_disk = json.loads((self.dest / "version.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, self.manifest)
        self.assertEqual(on_disk["version"], "9.8.7")
        self.assertEqual(on_disk["commit"], "abc123")
        self.assertEqual(on_disk["requires_runtime"], runtime_version())
        self.assertIn("app", on_disk["modules"])

    def test_copies_modules_and_data_dirs_without_bytecode(self):
        for module in self.manifest["modules"]:
            self.assertTrue((self.dest / f"{module}.py").is_file(), module)
        for directory in DATA_DIRS:
            self.assertTrue((self.dest / directory).is_dir(), directory)
        self.assertEqual(list(self.dest.rglob("__pycache__")), [])

    def test_ships_the_timeline_prompt_templates(self):
        # Aucun import n'atteint ces gabarits : seul DATA_DIRS les fait partir.
        for lang in ("en", "fr"):
            template = self.dest / "prompt_templates" / lang / "timeline_extract.md"
            self.assertTrue(template.is_file(), template)

    def test_rebuild_starts_from_a_clean_folder(self):
        (self.dest / "stale.py").write_text("", encoding="utf-8")
        build_payload(self.dest, "9.8.7", "abc123")
        self.assertFalse((self.dest / "stale.py").exists())

    def test_analytics_config_is_generated_disabled_by_default(self):
        config = json.loads((self.dest / "analytics_config.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config), {"project_token", "region"})

    def test_analytics_config_follows_the_ci_variables(self):
        env = {"ANKIGEN_POSTHOG_TOKEN": "phc_Test123", "ANKIGEN_POSTHOG_REGION": "us"}
        with mock.patch.dict("os.environ", env):
            build_payload(self.dest, "9.8.7", "abc123")
        config = json.loads((self.dest / "analytics_config.json").read_text(encoding="utf-8"))
        self.assertEqual(config, {"project_token": "phc_Test123", "region": "us"})

    def test_an_invalid_analytics_token_fails_the_build(self):
        with mock.patch.dict("os.environ", {"ANKIGEN_POSTHOG_TOKEN": "sk_personal_key"}):
            with self.assertRaises(ValueError):
                build_payload(self.dest, "9.8.7", "abc123")

    def test_zip_has_the_app_folder_the_updater_expects(self):
        archive = self.tmp / "app.zip"
        write_zip(self.dest, archive)
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
        self.assertIn("app/app.py", names)
        self.assertIn("app/version.json", names)
        self.assertTrue(all(name.startswith("app/") for name in names))


if __name__ == "__main__":
    unittest.main()
