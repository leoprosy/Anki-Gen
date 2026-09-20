#!/usr/bin/env python3
"""
tests/test_bootstrap_version.py — Lecture de version pour le déploiement APPDATA.

`launcher.read_version` décide si les fichiers embarqués dans l'exécutable
remplacent ceux déjà déployés. Quand elle se trompe, l'utilisateur installe la
dernière version et relance l'ancienne — sans aucun signe de ce qui se passe.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from launcher import read_version, deploy_bundle  # noqa: E402
import updater
import paths


class TestReadVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-bootstrap-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, content):
        path = self.tmp / "version.json"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_reads_a_declared_version(self):
        self.assertEqual(read_version(self.write('{"version": "1.2.0"}')), "1.2.0")

    def test_missing_file_is_none(self):
        self.assertIsNone(read_version(str(self.tmp / "nope.json")))

    def test_invalid_json_is_none(self):
        self.assertIsNone(read_version(self.write("{ not json")))

    def test_missing_key_is_none(self):
        self.assertIsNone(read_version(self.write('{"other": "1.2.0"}')))

    def test_json_list_is_none(self):
        """Un JSON valide mais non-objet ne doit pas lever, juste répondre None."""
        self.assertIsNone(read_version(self.write('["1.2.0"]')))


class TestRedeployDecision(unittest.TestCase):
    """
    Exercise the actual bootstrap on disk, including repeated launches.
    """
    setUp = TestReadVersion.setUp
    tearDown = TestReadVersion.tearDown

    def redeploys(self, shipped, installed):
        bundle = self.tmp / 'bundle'
        live = self.tmp / 'app'
        bundle.mkdir()
        live.mkdir()
        (bundle / 'version.json').write_text(json.dumps({'version': shipped}))
        (live / 'version.json').write_text(json.dumps({'version': installed}))
        return deploy_bundle(str(bundle), str(live))

    def test_first_install_deploys(self):
        self.assertTrue(self.redeploys("1.2.0", None))

    def test_newer_shipped_version_redeploys(self):
        """Le cas qui manquait : réinstaller par-dessus une version déjà déployée."""
        self.assertTrue(self.redeploys("1.2.0", "1.1.0"))

    def test_same_version_leaves_the_install_alone(self):
        self.assertFalse(self.redeploys("1.2.0", "1.2.0"))

    def test_older_shipped_version_preserves_downloaded_update(self):
        self.assertFalse(self.redeploys("1.1.0", "1.2.0"))

    def test_update_stays_installed_across_relaunches(self):
        self.redeploys('1.1.0', '1.1.0')
        live = self.tmp / 'app'
        staged = self.tmp / 'app_staged'
        staged.mkdir()
        manifest = {'version': '1.2.0', 'commit': 'new-commit'}
        (staged / 'version.json').write_text(json.dumps(manifest))
        updater.apply_staged_update(str(live))
        for _ in range(3):
            self.assertFalse(deploy_bundle(str(self.tmp / 'bundle'), str(live)))
            installed = json.loads((live / 'version.json').read_text())
            self.assertFalse(updater.is_update_available(
                manifest, installed['version'], installed['commit']))

    def test_unreadable_bundle_version_changes_nothing(self):
        """Sans version livrée lisible, on ne touche pas à une install qui marche."""
        self.assertFalse(self.redeploys(None, "1.1.0"))


class TestPathResolution(unittest.TestCase):
    def test_path_reads_never_import_launcher(self):
        import builtins
        original_import = builtins.__import__
        imports = []

        def track_import(name, *args, **kwargs):
            imports.append(name)
            return original_import(name, *args, **kwargs)

        with mock.patch('builtins.__import__', side_effect=track_import), \
                mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.dict(paths.os.environ, {'APPDATA': str(ROOT / 'test-appdata')}):
            app_dir, data_dir = paths._resolve_base_dirs()
            self.assertEqual(data_dir, ROOT / 'test-appdata' / 'AnkiGen')
            self.assertEqual(app_dir, data_dir / 'app')
            updater._get_app_dir()
        self.assertNotIn('launcher', imports)


if __name__ == "__main__":
    unittest.main()
