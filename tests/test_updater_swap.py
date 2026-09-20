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


class TestVersionComparison(unittest.TestCase):
    def test_newer_release_is_available(self):
        self.assertTrue(updater.is_newer_version("1.2.0", "1.1.0"))

    def test_equal_release_is_not_available(self):
        self.assertFalse(updater.is_newer_version("1.2.0", "1.2.0"))

    def test_older_release_is_not_available(self):
        self.assertFalse(updater.is_newer_version("1.1.0", "1.2.0"))

    def test_numeric_components_are_compared_numerically(self):
        self.assertTrue(updater.is_newer_version("1.10.0", "1.9.0"))

    def test_missing_local_version_does_not_offer_an_update(self):
        self.assertFalse(updater.is_newer_version("1.2.0", "0.0.0"))

    def test_malformed_versions_do_not_offer_an_update(self):
        for remote, local in (
            ("", "1.1.0"),
            ("1.2.0-beta", "1.1.0"),
            ("v1.2.0-beta", "1.1.0"),
            ("1.2.0", ""),
        ):
            with self.subTest(remote=remote, local=local):
                self.assertFalse(updater.is_newer_version(remote, local))


class TestUpdateAvailable(unittest.TestCase):
    """is_update_available() couvre le cas que is_newer_version() seul ratait :
    build-latest.yml republie app.zip sur chaque push vers main SANS changer
    le tag/la version, donc un utilisateur déjà sur cette version ne verrait
    jamais la mise à jour si on ne comparait que des numéros de version."""

    def test_no_manifest_means_no_update(self):
        """Release publié avant l'introduction du manifeste version.json."""
        self.assertFalse(updater.is_update_available(None, "1.2.0", "abc123"))

    def test_higher_version_is_an_update_even_without_commit(self):
        manifest = {"version": "1.3.0", "commit": ""}
        self.assertTrue(updater.is_update_available(manifest, "1.2.0", "abc123"))

    def test_same_version_same_commit_is_up_to_date(self):
        manifest = {"version": "1.2.0", "commit": "abc123"}
        self.assertFalse(updater.is_update_available(manifest, "1.2.0", "abc123"))

    def test_same_version_different_commit_is_an_update(self):
        """Le coeur du fix : un rebuild de main sur la même version doit notifier."""
        manifest = {"version": "1.2.0", "commit": "def456"}
        self.assertTrue(updater.is_update_available(manifest, "1.2.0", "abc123"))

    def test_same_version_unknown_local_commit_is_an_update(self):
        """Installation antérieure au champ 'commit' : un rattrapage ponctuel est correct."""
        manifest = {"version": "1.2.0", "commit": "def456"}
        self.assertTrue(updater.is_update_available(manifest, "1.2.0", ""))

    def test_older_version_is_never_an_update_even_with_different_commit(self):
        manifest = {"version": "1.1.0", "commit": "def456"}
        self.assertFalse(updater.is_update_available(manifest, "1.2.0", "abc123"))


class TestApplyStagedUpdate(SwapTestCase):
    def test_pending_update_does_not_download_again(self):
        self.stage()
        with mock.patch.object(updater, '_get_app_dir', return_value=str(self.live)), \
                mock.patch.object(updater, 'fetch_latest_release') as fetch:
            self.assertEqual(updater.check_and_update()['status'], 'staged')
            fetch.assert_not_called()

    def test_check_offers_restart_for_pending_update_even_offline(self):
        from app import app
        self.stage()
        with mock.patch.object(updater, '_get_app_dir', return_value=str(self.live)), \
                mock.patch.object(updater, 'fetch_latest_release') as fetch:
            result = app.test_client().get('/api/update/check').get_json()
            self.assertTrue(result['restart_required'])
            self.assertFalse(result['update_available'])
            fetch.assert_not_called()

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
