#!/usr/bin/env python3
"""
tests/test_updater_swap.py — Échange atomique de la mise à jour au démarrage.

`apply_staged_update` déplace le dossier applicatif de l'utilisateur. Une erreur
ici ne casse pas un affichage : elle casse l'installation. D'où des tests sur le
chemin nominal ET sur l'échec en cours de route.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import updater  # noqa: E402


class SwapTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-swap-"))
        self.live = self.tmp / "app"
        self.live.mkdir()
        (self.live / "app.py").write_text("ancienne version", encoding="utf-8")
        (self.live / "version.json").write_text('{"version": "1.1.0"}', encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stage(self):
        staged = Path(str(self.live) + "_staged")
        staged.mkdir()
        (staged / "app.py").write_text("nouvelle version", encoding="utf-8")
        (staged / "version.json").write_text('{"version": "1.2.0"}', encoding="utf-8")
        return staged


class TestApplyStagedUpdate(SwapTestCase):
    def test_no_staging_is_a_no_op(self):
        self.assertFalse(updater.apply_staged_update(str(self.live)))
        self.assertEqual((self.live / "app.py").read_text(encoding="utf-8"),
                         "ancienne version")

    def test_staged_content_becomes_live(self):
        self.stage()
        self.assertTrue(updater.apply_staged_update(str(self.live)))
        self.assertEqual((self.live / "app.py").read_text(encoding="utf-8"),
                         "nouvelle version")
        self.assertEqual((self.live / "version.json").read_text(encoding="utf-8"),
                         '{"version": "1.2.0"}')

    def test_staging_directory_is_consumed(self):
        staged = self.stage()
        updater.apply_staged_update(str(self.live))
        self.assertFalse(staged.exists(), "le staging doit disparaître après l'échange")

    def test_no_backup_left_behind_on_success(self):
        self.stage()
        updater.apply_staged_update(str(self.live))
        self.assertFalse(Path(str(self.live) + "_backup").exists())

    def test_second_call_is_a_no_op(self):
        self.stage()
        self.assertTrue(updater.apply_staged_update(str(self.live)))
        self.assertFalse(updater.apply_staged_update(str(self.live)))

    def test_a_leftover_backup_does_not_block_the_swap(self):
        """Un backup orphelin d'un échange précédent interrompu ne doit pas coincer."""
        Path(str(self.live) + "_backup").mkdir()
        (Path(str(self.live) + "_backup") / "vieux.py").write_text("x", encoding="utf-8")
        self.stage()
        self.assertTrue(updater.apply_staged_update(str(self.live)))
        self.assertEqual((self.live / "app.py").read_text(encoding="utf-8"),
                         "nouvelle version")


class TestFailureLeavesInstallIntact(SwapTestCase):
    """Le point critique : une interruption ne doit jamais laisser l'app sans code."""

    def test_live_directory_is_restored_when_the_swap_fails(self):
        self.stage()
        real_rename = updater.os.rename
        calls = {"n": 0}

        def rename_failing_on_second_call(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:      # le live est déjà écarté, le staging entre en place
                raise OSError("disque plein")
            return real_rename(src, dst)

        with mock.patch.object(updater.os, "rename", rename_failing_on_second_call):
            with self.assertRaises(OSError):
                updater.apply_staged_update(str(self.live))

        self.assertTrue(self.live.is_dir(), "le dossier applicatif a disparu")
        self.assertEqual((self.live / "app.py").read_text(encoding="utf-8"),
                         "ancienne version")

    def test_download_is_kept_when_the_swap_fails(self):
        """Un échange raté ne doit pas obliger à retélécharger la mise à jour."""
        staged = self.stage()
        real_rename = updater.os.rename
        calls = {"n": 0}

        def rename_failing_on_second_call(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disque plein")
            return real_rename(src, dst)

        with mock.patch.object(updater.os, "rename", rename_failing_on_second_call):
            with self.assertRaises(OSError):
                updater.apply_staged_update(str(self.live))

        self.assertTrue(staged.is_dir(), "le staging doit survivre à un échec")


if __name__ == "__main__":
    unittest.main()
