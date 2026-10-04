#!/usr/bin/env python3
"""
tests/test_runtime_contract.py — Contrat entre l'exécutable et le code livré par app.zip.

L'updater remplace le code sans toucher à l'exécutable. Trois garanties en
découlent, testées ici :

  * runtime.json suit requirements.txt : une nouvelle dépendance sans `--bump`
    fait échouer la suite, au lieu de casser les installations existantes ;
  * l'updater refuse une mise à jour que l'exécutable local ne peut pas faire
    tourner, et oriente vers l'installateur ;
  * `launcher --self-check` détecte un import ou une sonde qui échoue.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import runtime_contract  # noqa: E402
import runtime_probe  # noqa: E402
import updater  # noqa: E402
from check_runtime_compat import find_previous_exe, interpret  # noqa: E402
from launcher import read_runtime, self_check  # noqa: E402


class TestRequirementsContract(unittest.TestCase):
    def test_runtime_json_covers_requirements_txt(self):
        ok, message = runtime_contract.check_contract()
        self.assertTrue(ok, message)

    def test_packaging_tools_are_not_part_of_the_runtime(self):
        text = "Flask==3.1.3\n# commentaire\npillow==12.2.0  # images\n\n# Packaging\npyinstaller==6.20.0\n"
        self.assertEqual(runtime_contract.runtime_requirements(text),
                         ["flask==3.1.3", "pillow==12.2.0"])

    def test_adding_a_dependency_changes_the_digest(self):
        base = runtime_contract.runtime_requirements("Flask==3.1.3\n")
        more = runtime_contract.runtime_requirements("Flask==3.1.3\nrequests==2.0\n")
        self.assertNotEqual(runtime_contract.requirements_digest(base),
                            runtime_contract.requirements_digest(more))

    def test_reordering_or_comments_do_not_change_the_digest(self):
        a = runtime_contract.runtime_requirements("a==1\nb==2\n")
        b = runtime_contract.runtime_requirements("# deps\nb==2\n\na==1  # note\n")
        self.assertEqual(runtime_contract.requirements_digest(a),
                         runtime_contract.requirements_digest(b))

    def test_distribution_names_are_canonical(self):
        self.assertEqual(runtime_contract.distribution_name("python_docx==1.2.0"), "python-docx")
        self.assertEqual(runtime_contract.distribution_name("MarkupSafe>=3"), "markupsafe")
        self.assertEqual(
            runtime_contract.distribution_name('pywin32-ctypes==0.2.3; sys_platform == "win32"'),
            "pywin32-ctypes")


class TestWhatTheExecutableEmbeds(unittest.TestCase):
    def test_requirements_map_to_their_import_names(self):
        names = set(runtime_contract.runtime_import_names())
        self.assertLessEqual({"PIL", "docx", "flask", "lxml", "waitress"}, names)
        self.assertNotIn("PyInstaller", names)

    def test_stdlib_includes_submodules_a_feature_might_need(self):
        modules = set(runtime_contract.stdlib_modules())
        for name in ("difflib", "unicodedata", "xml.sax.saxutils", "email.mime.text",
                     "concurrent.futures", "importlib.metadata"):
            self.assertIn(name, modules)

    def test_stdlib_leaves_out_gui_and_test_suites(self):
        modules = runtime_contract.stdlib_modules()
        self.assertFalse(any(m == "tkinter" or m.startswith("tkinter.") for m in modules))
        self.assertFalse(any(".test." in f".{m}." or m.endswith(".tests") for m in modules))


class TestLocalRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-runtime-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_frozen_executable_reads_its_embedded_runtime(self):
        (self.tmp / "runtime.json").write_text('{"runtime": 4}', encoding="utf-8")
        with mock.patch.object(sys, "_MEIPASS", str(self.tmp), create=True):
            self.assertEqual(updater.get_local_runtime(), 4)
            self.assertEqual(read_runtime(), 4)

    def test_executable_older_than_the_contract_is_runtime_zero(self):
        with mock.patch.object(sys, "_MEIPASS", str(self.tmp), create=True):
            self.assertEqual(updater.get_local_runtime(), 0)
            self.assertEqual(read_runtime(), 0)

    def test_dev_checkout_reads_the_repository_runtime(self):
        self.assertEqual(updater.get_local_runtime(), runtime_contract.runtime_version())


class TestUpdaterHonoursTheContract(unittest.TestCase):
    def test_required_runtime_defaults_to_zero_for_old_manifests(self):
        self.assertEqual(updater.required_runtime({"version": "1.2.1"}), 0)
        self.assertEqual(updater.required_runtime(None), 0)
        self.assertEqual(updater.required_runtime(["not", "a", "dict"]), 0)
        self.assertEqual(updater.required_runtime({"requires_runtime": "bad"}), 0)

    def test_runtime_supports(self):
        self.assertTrue(updater.runtime_supports({"requires_runtime": 1}, 1))
        self.assertTrue(updater.runtime_supports({}, 0))
        self.assertFalse(updater.runtime_supports({"requires_runtime": 2}, 1))
        self.assertFalse(updater.runtime_supports({"requires_runtime": 1}, 0))

    def _check(self, manifest, local_runtime):
        release = {"tag_name": "v2.0.0", "assets": [
            {"name": "app.zip", "browser_download_url": "https://example.invalid/app.zip"}]}
        with mock.patch.object(updater, "get_staged_version", return_value=None), \
                mock.patch.object(updater, "fetch_latest_release", return_value=release), \
                mock.patch.object(updater, "fetch_remote_manifest", return_value=manifest), \
                mock.patch.object(updater, "get_local_version", return_value="1.2.1"), \
                mock.patch.object(updater, "get_local_commit", return_value="old"), \
                mock.patch.object(updater, "get_local_runtime", return_value=local_runtime), \
                mock.patch.object(updater, "download_and_apply") as download:
            return updater.check_and_update(), download

    def test_update_needing_a_newer_runtime_is_never_downloaded(self):
        result, download = self._check({"version": "2.0.0", "requires_runtime": 2}, 1)
        self.assertEqual(result["status"], "installer_required")
        self.assertEqual(result["message_key"], "update.installer_required")
        download.assert_not_called()

    def test_compatible_update_is_still_staged(self):
        result, download = self._check({"version": "2.0.0", "requires_runtime": 1}, 1)
        self.assertEqual(result["status"], "staged")
        download.assert_called_once()


class TestUpdateCheckRoute(unittest.TestCase):
    """/api/update/check : le bandeau doit proposer l'installateur, pas app.zip."""

    def check(self, manifest, local_runtime):
        from app import app
        release = {"tag_name": "v2.0.0", "assets": []}
        with mock.patch.object(updater, "get_staged_version", return_value=None), \
                mock.patch.object(updater, "fetch_latest_release", return_value=release), \
                mock.patch.object(updater, "fetch_remote_manifest", return_value=manifest), \
                mock.patch.object(updater, "get_local_version", return_value="1.2.1"), \
                mock.patch.object(updater, "get_local_commit", return_value="old"), \
                mock.patch.object(updater, "get_local_runtime", return_value=local_runtime):
            return app.test_client().get("/api/update/check").get_json()

    def test_incompatible_update_asks_for_the_installer(self):
        data = self.check({"version": "2.0.0", "commit": "new", "requires_runtime": 2}, 1)
        self.assertFalse(data["update_available"])
        self.assertTrue(data["installer_required"])
        self.assertIn("2.0.0", data["message"])

    def test_compatible_update_is_offered_as_before(self):
        data = self.check({"version": "2.0.0", "commit": "new", "requires_runtime": 1}, 1)
        self.assertTrue(data["update_available"])
        self.assertNotIn("installer_required", data)


class TestStagedUpdateGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-runtime-"))
        self.live = self.tmp / "app"
        self.live.mkdir()
        (self.live / "app.py").write_text("ancienne version", encoding="utf-8")
        self.staged = Path(str(self.live) + "_staged")
        self.staged.mkdir()
        (self.staged / "app.py").write_text("nouvelle version", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stage(self, requires_runtime):
        (self.staged / "version.json").write_text(
            json.dumps({"version": "2.0.0", "requires_runtime": requires_runtime}),
            encoding="utf-8")

    def test_incompatible_staging_is_discarded_and_live_code_kept(self):
        self.stage(3)
        with mock.patch.object(updater, "get_local_runtime", return_value=1):
            self.assertFalse(updater.apply_staged_update(str(self.live)))
        self.assertFalse(self.staged.exists())
        self.assertEqual((self.live / "app.py").read_text(encoding="utf-8"), "ancienne version")

    def test_compatible_staging_is_applied(self):
        self.stage(1)
        with mock.patch.object(updater, "get_local_runtime", return_value=1):
            self.assertTrue(updater.apply_staged_update(str(self.live)))
        self.assertEqual((self.live / "app.py").read_text(encoding="utf-8"), "nouvelle version")


class TestSelfCheck(unittest.TestCase):
    """launcher.self_check, sur un dossier applicatif miniature."""

    def setUp(self):
        self.app_dir = Path(tempfile.mkdtemp(prefix="ankigen-selfcheck-"))
        # Noms uniques : sys.modules garde les modules d'un test à l'autre.
        suffix = uuid.uuid4().hex[:8]
        self.good, self.bad = f"good_{suffix}", f"bad_{suffix}"
        (self.app_dir / f"{self.good}.py").write_text("import difflib\n", encoding="utf-8")
        (self.app_dir / f"{self.bad}.py").write_text(
            "import module_that_the_runtime_lacks\n", encoding="utf-8")
        # Un launcher.py qui lèverait s'il était importé : il doit être sauté.
        (self.app_dir / "launcher.py").write_text("raise RuntimeError('bootstrap')\n",
                                                  encoding="utf-8")

    def tearDown(self):
        if str(self.app_dir) in sys.path:
            sys.path.remove(str(self.app_dir))
        shutil.rmtree(self.app_dir, ignore_errors=True)

    def manifest(self, modules, requires_runtime=1):
        (self.app_dir / "version.json").write_text(json.dumps({
            "version": "2.0.0", "requires_runtime": requires_runtime, "modules": modules,
        }), encoding="utf-8")

    def test_passes_when_every_module_imports(self):
        self.manifest([self.good, "launcher"])
        report, code = self_check(str(self.app_dir), runtime=1)
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "ok")
        self.assertNotIn("launcher", report["modules"])

    def test_fails_and_names_the_module_that_does_not_import(self):
        self.manifest([self.good, self.bad])
        report, code = self_check(str(self.app_dir), runtime=1)
        self.assertEqual(code, 1)
        self.assertIsNone(report["modules"][self.good])
        self.assertIn("module_that_the_runtime_lacks", report["modules"][self.bad])

    def test_runtime_too_old_is_reported_without_importing(self):
        self.manifest([self.bad], requires_runtime=2)
        report, code = self_check(str(self.app_dir), runtime=1)
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "runtime_too_old")
        self.assertEqual(report["modules"], {})

    def test_the_real_payload_passes_on_this_interpreter(self):
        report, code = self_check(str(ROOT), runtime=runtime_contract.runtime_version())
        self.assertEqual(code, 0, json.dumps(report, indent=2))
        self.assertTrue(report["probes"])


class TestRuntimeProbe(unittest.TestCase):
    def test_every_probe_passes_in_the_development_environment(self):
        self.assertEqual({k: v for k, v in runtime_probe.run().items() if v}, {})

    def test_a_failing_probe_is_reported_not_raised(self):
        def broken():
            raise ImportError("no freetype")
        with mock.patch.dict(runtime_probe.PROBES, {"broken": broken}):
            self.assertEqual(runtime_probe.run()["broken"], "ImportError: no freetype")


class TestCompatCheckDecisions(unittest.TestCase):
    def test_picks_the_newest_published_release_that_ships_the_exe(self):
        releases = [
            {"tag_name": "v1.4.0", "draft": True,
             "assets": [{"name": "flask-server.exe", "url": "draft"}]},
            {"tag_name": "v1.3.0", "assets": [{"name": "app.zip"}]},
            {"tag_name": "v1.2.9",
             "assets": [{"name": "flask-server.exe", "url": "u129"}]},
            {"tag_name": "v1.2.8",
             "assets": [{"name": "flask-server.exe", "url": "u128"}]},
        ]
        self.assertEqual(find_previous_exe(releases), ("v1.2.9", "u129"))
        self.assertEqual(find_previous_exe(releases, exclude_tag="v1.2.9"), ("v1.2.8", "u128"))
        self.assertIsNone(find_previous_exe(releases[:2]))

    def test_exit_codes(self):
        self.assertTrue(interpret(0)[0])
        self.assertTrue(interpret(3)[0])   # installateur requis : voulu
        self.assertFalse(interpret(1)[0])
        self.assertFalse(interpret(-1)[0])


if __name__ == "__main__":
    unittest.main()
