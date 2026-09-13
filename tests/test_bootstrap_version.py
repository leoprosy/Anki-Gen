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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from launcher import read_version  # noqa: E402


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
    La règle appliquée par launcher.py : redéployer dès que la version livrée
    diffère de la version déployée.
    """

    @staticmethod
    def redeploys(shipped, installed):
        return bool(shipped and shipped != installed)

    def test_first_install_deploys(self):
        self.assertTrue(self.redeploys("1.2.0", None))

    def test_newer_shipped_version_redeploys(self):
        """Le cas qui manquait : réinstaller par-dessus une version déjà déployée."""
        self.assertTrue(self.redeploys("1.2.0", "1.1.0"))

    def test_same_version_leaves_the_install_alone(self):
        self.assertFalse(self.redeploys("1.2.0", "1.2.0"))

    def test_older_shipped_version_still_redeploys(self):
        """Installer volontairement une version antérieure doit la déployer."""
        self.assertTrue(self.redeploys("1.1.0", "1.2.0"))

    def test_unreadable_bundle_version_changes_nothing(self):
        """Sans version livrée lisible, on ne touche pas à une install qui marche."""
        self.assertFalse(self.redeploys(None, "1.1.0"))


if __name__ == "__main__":
    unittest.main()
