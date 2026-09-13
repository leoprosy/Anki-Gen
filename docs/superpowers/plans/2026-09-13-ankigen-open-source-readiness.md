# Ankigen Open-Source Readiness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Anki-Gen usable by someone who is neither French-speaking nor an ESH student — rename it Ankigen, add English/French UI, make the deck prefix and export folder configurable, give it a logo, and replace the embedded ESH system prompt with a help page.

**Architecture:** Two new dependency-free modules — `i18n.py` (flat JSON catalogs under `locales/`) and `settings.py` (preferences in `DATA_DIR/settings.json`). Neither imports Flask nor each other; `app.py` is the only place that wires them together, via a Jinja context processor that injects `t` and `lang`. Client-side strings travel to `static/app.js` through a `window.__I18N__` payload serialised by `base.html`, so there is exactly one translation mechanism.

**Tech Stack:** Python 3 · Flask · Jinja2 · Waitress · vanilla JS · `unittest` (stdlib) · PyInstaller · Tauri 2

## Global Constraints

Every task's requirements implicitly include this section.

- **Branch:** `feat/open-source-readiness` (already created from `main` at `b8e58c1`). Never commit to `main`.
- **Commits:** Conventional Commits, `type(scope): description`, **in English**, imperative. End every commit message with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Test command (the only one — pytest is NOT installed and must NOT be introduced):**
  `.venv/Scripts/python.exe -m unittest discover -s tests`
  Baseline on `b8e58c1`: **38 tests, OK**. This number only ever goes up.
- **The plain `python` on PATH has neither `docx` nor `flask`.** Always use `.venv/Scripts/python.exe`.
- **Tests use `unittest`**, following `tests/test_docx_media.py`: `sys.path.insert` of the repo root at the top, classes deriving from `unittest.TestCase`.
- **Default language is `"en"`.** Anything user-visible added in any task must exist in both `locales/en.json` and `locales/fr.json` — the parity test from Task 1 fails otherwise.
- **Plural forms use the `(s)` convention** (`"{n} card(s)"`, `"{n} carte(s)"`). No plural engine. This is deliberate: it keeps catalogs flat and matches the existing French copy.
- **Never rename** the Tauri identifier `ankiesh`, the `%APPDATA%/AnkiGen` data folder, the `ANKI_ESH_SIDECAR` environment variable, or `GITHUB_REPO = "leoprosy/Anki-Gen"`. Renaming any of these breaks existing installs or the update channel.
- **Spec:** `docs/superpowers/specs/2026-09-13-ankigen-open-source-design.md`. A decision is explained there once; this plan does not re-argue it.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `i18n.py` | Key → string resolution with cascading fallback. No Flask, no settings import. |
| `locales/en.json` | English catalog. Flat, keys namespaced by screen. |
| `locales/fr.json` | French catalog. Same key set, enforced by test. |
| `settings.py` | Preference persistence + download-folder resolution. Imports `paths` only. |
| `templates/settings.html` | Settings panel. |
| `templates/help.html` | "How to use" page, including the Claude Skill template. |
| `static/logo.svg` | Standalone logo, for README and future icon rasterisation. |
| `tests/test_i18n.py` | Catalog parity, fallback, interpolation. |
| `tests/test_settings.py` | Defaults, corruption tolerance, atomic save, folder resolution. |
| `tests/test_deck_prefix.py` | Empty-prefix deck paths. |

**Modified:** `app.py`, `parse_cours.py`, `project_store.py`, `updater.py`, `launcher.py`, `templates/base.html`, `templates/upload.html`, `templates/work.html`, `static/app.js`, `src-tauri/tauri.conf.json`, `scripts/generate-dist-tauri.js`, `package.json`, `flask-server.spec`, `.github/workflows/release.yml`, `README.md`.

**Task order matters.** Task 1 (i18n) and Task 2 (settings) are the foundation; Task 3 wires them into Flask. Tasks 4–9 each add their own keys to both catalogs.

---

### Task 1: i18n core

**Files:**
- Create: `i18n.py`
- Create: `locales/en.json`, `locales/fr.json`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `i18n.DEFAULT_LANG: str` = `"en"`
  - `i18n.LANGUAGES: tuple` = `("en", "fr")`
  - `i18n.translate(key: str, lang: str = "en", **params) -> str`
  - `i18n.catalog_for_js(lang: str, prefix: str = "js.") -> dict`
  - `i18n.available_languages() -> list[dict]` → `[{"code": "en", "label": "English"}, {"code": "fr", "label": "Français"}]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_i18n.py`:

```python
#!/usr/bin/env python3
"""
tests/test_i18n.py — Résolution des traductions et intégrité des catalogues.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402


class TestCatalogParity(unittest.TestCase):
    """Une clé présente d'un côté et pas de l'autre est un texte non traduit en prod."""

    def test_same_keys_in_every_language(self):
        catalogs = {lang: i18n.load_catalog(lang) for lang in i18n.LANGUAGES}
        reference = set(catalogs[i18n.DEFAULT_LANG])
        self.assertTrue(reference, "le catalogue anglais ne doit pas être vide")
        for lang, catalog in catalogs.items():
            missing = reference - set(catalog)
            extra = set(catalog) - reference
            self.assertEqual(missing, set(), f"clés absentes de {lang}.json : {sorted(missing)}")
            self.assertEqual(extra, set(), f"clés en trop dans {lang}.json : {sorted(extra)}")

    def test_catalogs_are_flat_strings(self):
        for lang in i18n.LANGUAGES:
            for key, value in i18n.load_catalog(lang).items():
                self.assertIsInstance(value, str, f"{lang}.json : {key} n'est pas une chaîne")

    def test_no_empty_translation(self):
        for lang in i18n.LANGUAGES:
            for key, value in i18n.load_catalog(lang).items():
                self.assertTrue(value.strip(), f"{lang}.json : {key} est vide")


class TestTranslate(unittest.TestCase):
    def test_returns_translation_for_known_key(self):
        self.assertEqual(i18n.translate("app.name", "en"), "Ankigen")

    def test_unknown_key_returns_the_key_itself(self):
        # Visible en développement, mais jamais une page cassée en production.
        self.assertEqual(i18n.translate("nope.not_a_key", "fr"), "nope.not_a_key")

    def test_falls_back_to_english_when_missing_in_language(self):
        i18n._CACHE["xx"] = {}
        self.assertEqual(i18n.translate("app.name", "xx"), "Ankigen")

    def test_interpolates_parameters(self):
        i18n._CACHE["xx"] = {"test.count": "{n} card(s)"}
        self.assertEqual(i18n.translate("test.count", "xx", n=3), "3 card(s)")

    def test_missing_parameter_returns_template_instead_of_raising(self):
        i18n._CACHE["xx"] = {"test.count": "{n} card(s)"}
        self.assertEqual(i18n.translate("test.count", "xx"), "{n} card(s)")

    def tearDown(self):
        i18n._CACHE.pop("xx", None)


class TestCatalogForJs(unittest.TestCase):
    def test_keeps_only_the_js_namespace(self):
        subset = i18n.catalog_for_js("en")
        self.assertTrue(subset, "le namespace js. ne doit pas être vide")
        for key in subset:
            self.assertTrue(key.startswith("js."))

    def test_falls_back_to_english_entries(self):
        i18n._CACHE["xx"] = {}
        subset = i18n.catalog_for_js("xx")
        self.assertEqual(subset, i18n.catalog_for_js("en"))
        i18n._CACHE.pop("xx", None)


class TestAvailableLanguages(unittest.TestCase):
    def test_lists_every_language_with_a_label(self):
        codes = [entry["code"] for entry in i18n.available_languages()]
        self.assertEqual(codes, list(i18n.LANGUAGES))
        for entry in i18n.available_languages():
            self.assertTrue(entry["label"].strip())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_i18n.py" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'i18n'`

- [ ] **Step 3: Write the implementation**

Create `i18n.py`:

```python
#!/usr/bin/env python3
"""
i18n.py — Résolution des chaînes traduites d'Ankigen.

Les traductions vivent dans `locales/<lang>.json` : des dictionnaires plats dont
les clés sont namespacées par écran (`upload.title`, `work.cards_detected`). Les
clés du namespace `js.` sont celles que `base.html` sérialise dans
`window.__I18N__` pour `static/app.js`.

Ce module ne dépend ni de Flask ni de `settings` : c'est `app.py` qui le relie au
reste. Il est ainsi testable seul, et utilisable hors requête HTTP.
"""

import json
from pathlib import Path

DEFAULT_LANG = "en"
LANGUAGES = ("en", "fr")
LANGUAGE_LABELS = {"en": "English", "fr": "Français"}

# En mode packagé, i18n.py vit dans APP_DIR et locales/ est copié à côté :
# résoudre relativement au module fonctionne dans les deux modes.
LOCALES_DIR = Path(__file__).parent / "locales"

_CACHE = {}


def load_catalog(lang):
    """Dictionnaire plat d'une langue. Locale absente ou illisible → {}."""
    if lang in _CACHE:
        return _CACHE[lang]
    try:
        catalog = json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        if not isinstance(catalog, dict):
            catalog = {}
    except (OSError, ValueError):
        catalog = {}
    _CACHE[lang] = catalog
    return catalog


def translate(key, lang=DEFAULT_LANG, **params):
    """
    Chaîne traduite pour `key`.

    Repli en cascade : langue demandée → anglais → la clé elle-même. Retourner la
    clé plutôt que de lever garde l'interface utilisable quand une traduction
    manque, et rend l'oubli visible pendant le développement.
    """
    text = load_catalog(lang).get(key)
    if text is None:
        text = load_catalog(DEFAULT_LANG).get(key)
    if text is None:
        return key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError):
        # Un paramètre oublié ne doit pas casser la page : on rend le gabarit brut.
        return text


def catalog_for_js(lang, prefix="js."):
    """Sous-ensemble destiné à `window.__I18N__`, anglais complété par la langue."""
    merged = dict(load_catalog(DEFAULT_LANG))
    merged.update(load_catalog(lang))
    return {k: v for k, v in merged.items() if k.startswith(prefix)}


def available_languages():
    """[{"code": "en", "label": "English"}, ...] — pour le sélecteur de langue."""
    return [{"code": code, "label": LANGUAGE_LABELS[code]} for code in LANGUAGES]
```

Create `locales/en.json`:

```json
{
  "app.name": "Ankigen",
  "app.tagline": "Turn a .docx course into an Anki deck, one paragraph at a time.",
  "app.description": "Anki flashcard generator for .docx courses",
  "nav.home": "Home",
  "nav.settings": "Settings",
  "nav.help": "How to use",
  "js.saved": "Saved",
  "js.network_error": "Network error."
}
```

Create `locales/fr.json`:

```json
{
  "app.name": "Ankigen",
  "app.tagline": "Transforme un cours .docx en paquet Anki, paragraphe par paragraphe.",
  "app.description": "Générateur de flashcards Anki à partir de cours .docx",
  "nav.home": "Accueil",
  "nav.settings": "Paramètres",
  "nav.help": "Mode d'emploi",
  "js.saved": "Enregistré",
  "js.network_error": "Erreur réseau."
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -v`
Expected: PASS — 38 existing tests plus the new i18n ones, `OK`.

- [ ] **Step 5: Commit**

```bash
git add i18n.py locales tests/test_i18n.py
git commit -m "feat(i18n): add translation core with EN/FR catalogs

Flat JSON catalogs with cascading fallback (language, then English, then
the key itself) so a missing translation is visible in development but
never renders a broken page.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Settings module

**Files:**
- Create: `settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `paths.DATA_DIR`, `paths.EXPORT_DIR` (existing, from `paths.py`).
- Produces:
  - `settings.SETTINGS_FILE: Path` — module global, reassignable by tests
  - `settings.defaults() -> dict` with keys `language`, `download_dir`, `deck_prefix`
  - `settings.load_settings() -> dict`
  - `settings.save_settings(partial: dict) -> dict`
  - `settings.resolve_download_dir() -> Path | None`
  - `settings.check_dir(path: str) -> tuple[bool, str]` — the `str` is an i18n key

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_settings.py" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'settings'`

- [ ] **Step 3: Write the implementation**

Create `settings.py`:

```python
#!/usr/bin/env python3
"""
settings.py — Préférences utilisateur d'Ankigen.

Persistées dans DATA_DIR/settings.json, donc à côté de projects/ et media/, et
hors de app/ qui est remplacé à chaque mise à jour.

Ne dépend ni de Flask ni de i18n : de la lecture/écriture de fichier, testable
seule. `check_dir` retourne une *clé* de message, pas un texte — la traduction
appartient à la couche qui connaît la langue.
"""

import json
import os
import tempfile
from pathlib import Path

import paths

LANGUAGES = ("en", "fr")

# Global de module, et non constante figée à l'import : les tests le redirigent
# vers un dossier jetable pour ne jamais écrire dans %APPDATA%.
SETTINGS_FILE = paths.DATA_DIR / "settings.json"


def default_download_dir():
    """~/Downloads s'il existe, sinon le dossier d'exports de l'app."""
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else paths.EXPORT_DIR)


def defaults():
    return {
        "language": "en",
        "download_dir": default_download_dir(),
        "deck_prefix": "",
    }


def _clean(raw):
    """
    Valide clé par clé, en repartant des défauts.

    Une valeur invalide retombe sur son défaut sans emporter les autres : une
    préférence cassée ne doit coûter que celle-là. Les clés inconnues sont
    ignorées plutôt que conservées, pour que le fichier ne se remplisse pas de
    résidus d'anciennes versions.
    """
    out = defaults()
    if not isinstance(raw, dict):
        return out

    language = raw.get("language")
    if isinstance(language, str) and language in LANGUAGES:
        out["language"] = language

    deck_prefix = raw.get("deck_prefix")
    if isinstance(deck_prefix, str):
        out["deck_prefix"] = deck_prefix.strip()

    download_dir = raw.get("download_dir")
    if isinstance(download_dir, str) and download_dir.strip():
        # Conservé tel quel même s'il ne pointe nulle part : réécrire la saisie
        # de l'utilisateur en silence lui ferait perdre ce qu'il a tapé.
        out["download_dir"] = download_dir.strip()

    return out


def load_settings():
    """Préférences complètes. Fichier absent, illisible ou invalide → défauts."""
    try:
        raw = json.loads(Path(SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults()
    return _clean(raw)


def save_settings(partial):
    """
    Fusionne `partial` dans l'existant et écrit atomiquement.

    Écriture par fichier temporaire puis `os.replace` : une coupure en cours
    d'écriture laisse l'ancien fichier intact plutôt qu'un JSON tronqué, que le
    prochain démarrage traiterait comme corrompu.
    """
    merged = load_settings()
    for key in defaults():
        if isinstance(partial, dict) and key in partial:
            merged[key] = partial[key]
    merged = _clean(merged)

    target = Path(SETTINGS_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return merged


def check_dir(path):
    """
    (utilisable, clé de message) pour un dossier de téléchargement candidat.

    Utilisé par la page de réglages pour dire à l'utilisateur si sa saisie tient
    debout, sans rien enregistrer.
    """
    path = (path or "").strip()
    if not path:
        return False, "settings.dir_blank"

    candidate = Path(path)
    if candidate.exists() and not candidate.is_dir():
        return False, "settings.dir_not_a_folder"

    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False, "settings.dir_unreachable"

    if not os.access(candidate, os.W_OK):
        return False, "settings.dir_not_writable"

    return True, "settings.dir_ok"


def resolve_download_dir():
    """
    Dossier d'export utilisable, ou None.

    None n'est pas une erreur : c'est à l'appelant (l'export) de dégrader
    proprement plutôt que d'échouer sur un réglage devenu invalide.
    """
    ok, _ = check_dir(load_settings()["download_dir"])
    if not ok:
        return None
    return Path(load_settings()["download_dir"])
```

- [ ] **Step 4: Add the settings keys to both catalogs**

Add to `locales/en.json`:

```json
  "settings.dir_ok": "Folder is reachable and writable.",
  "settings.dir_blank": "Please enter a folder path.",
  "settings.dir_not_a_folder": "That path points to a file, not a folder.",
  "settings.dir_unreachable": "That folder cannot be created or reached.",
  "settings.dir_not_writable": "That folder is not writable."
```

Add to `locales/fr.json`:

```json
  "settings.dir_ok": "Dossier accessible et accessible en écriture.",
  "settings.dir_blank": "Indique un chemin de dossier.",
  "settings.dir_not_a_folder": "Ce chemin pointe vers un fichier, pas un dossier.",
  "settings.dir_unreachable": "Ce dossier ne peut être ni créé ni atteint.",
  "settings.dir_not_writable": "Ce dossier n'est pas accessible en écriture."
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -v`
Expected: PASS, `OK`. The parity test from Task 1 covers the five keys just added.

- [ ] **Step 6: Commit**

```bash
git add settings.py locales tests/test_settings.py
git commit -m "feat(settings): persist language, download folder and deck prefix

Stored in DATA_DIR/settings.json, written atomically so an interrupted
write leaves the previous file intact. A corrupt or unreadable file falls
back to defaults rather than preventing startup.

download_dir keeps whatever the user typed; resolve_download_dir() judges
usability separately, so a stale path never silently erases their input.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Wire i18n and settings into Flask

**Files:**
- Modify: `app.py` (imports at `app.py:27-45`, plus new routes near the page routes)
- Create: `templates/settings.html`
- Modify: `templates/base.html` (topbar links, `window.__I18N__`, `<html lang>`)

**Interfaces:**
- Consumes: `i18n.translate`, `i18n.catalog_for_js`, `i18n.available_languages`, `settings.load_settings`, `settings.save_settings`, `settings.check_dir`.
- Produces:
  - Jinja globals available in every template: `t(key, **params)`, `lang`, `prefs` (the settings dict), `js_i18n`
  - `app.tr(key, **params) -> str` — server-side translation outside templates
  - Routes: `GET /settings`, `GET|POST /api/settings`, `POST /api/settings/check-dir`
  - JS global: `window.__I18N__` (object), `window.T(key)` helper defined in `base.html`

- [ ] **Step 1: Add the wiring to `app.py`**

Add to the import block (after `import paths`):

```python
import settings as user_settings
from i18n import available_languages, catalog_for_js, translate
```

Add right after the `app.config["MAX_CONTENT_LENGTH"]` line:

```python
# ──────────────────────────────────────────────────────────────
# Langue et préférences
# ──────────────────────────────────────────────────────────────
def current_lang():
    return user_settings.load_settings()["language"]


def tr(key, **params):
    """Traduction hors template (messages JSON, en-têtes, contenus d'archive)."""
    return translate(key, current_lang(), **params)


@app.context_processor
def inject_i18n():
    """
    Injecte `t`, `lang` et les préférences dans tous les templates.

    Les préférences sont relues à chaque rendu : le fichier est minuscule, et un
    cache ferait diverger l'affichage juste après un changement de langue.
    """
    prefs = user_settings.load_settings()
    lang = prefs["language"]
    return {
        "t": lambda key, **params: translate(key, lang, **params),
        "lang": lang,
        "prefs": prefs,
        "js_i18n": catalog_for_js(lang),
        "languages": available_languages(),
    }
```

- [ ] **Step 2: Add the settings routes to `app.py`**

Insert after the `work()` route:

```python
@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify(user_settings.load_settings())
    data = request.get_json(silent=True) or {}
    return jsonify(ok=True, settings=user_settings.save_settings(data))


@app.route("/api/settings/check-dir", methods=["POST"])
def api_settings_check_dir():
    """Dit à l'interface si un dossier candidat tient debout, sans rien enregistrer."""
    data = request.get_json(silent=True) or {}
    ok, message_key = user_settings.check_dir(data.get("path") or "")
    return jsonify(ok=ok, message=tr(message_key))
```

- [ ] **Step 3: Update `templates/base.html`**

Replace line 2 (`<html lang="fr">`) with:

```html
<html lang="{{ lang }}">
```

Replace the `<title>` and `<meta name="description">` lines with:

```html
  <title>{% block title %}{{ t('app.name') }}{% endblock %}</title>
  <meta name="description" content="{{ t('app.description') }}">
```

Replace the `<header class="topbar">` block with:

```html
    <header class="topbar">
      <a class="brand" href="{{ url_for('index') }}" aria-label="{{ t('nav.home') }}">
        <svg width="22" height="22" aria-hidden="true"><use href="#i-logo"></use></svg>
        <span class="brand__name">{{ t('app.name') }}</span>
      </a>
      {% block topbar %}<div class="topbar__spacer"></div>{% endblock %}
      <nav class="topbar__nav">
        <a class="btn ghost sm" href="{{ url_for('help_page') }}" title="{{ t('nav.help') }}">
          <span class="lbl">{{ t('nav.help') }}</span>
        </a>
        <a class="btn ghost sm" href="{{ url_for('settings_page') }}" title="{{ t('nav.settings') }}">
          <span class="lbl">{{ t('nav.settings') }}</span>
        </a>
      </nav>
    </header>
```

> `url_for('help_page')` is created in Task 8. Until then this template raises `BuildError`. To keep every intermediate commit runnable, add the placeholder route below to `app.py` **in this task** and fill in its template in Task 8:
>
> ```python
> @app.route("/help")
> def help_page():
>     return render_template("help.html")
> ```
>
> and create a `templates/help.html` stub in this task containing only:
>
> ```html
> {% extends "base.html" %}
> {% block shell_body %}<main class="page"><h2>{{ t('nav.help') }}</h2></main>{% endblock %}
> ```

Add just before the closing `</script>` of the existing inline script block, at its very top (right after `<script>`):

```javascript
    // ── Chaînes traduites pour le JS (namespace `js.` des catalogues) ──
    window.__I18N__ = {{ js_i18n | tojson }};
    window.T = function (key, params) {
      let text = window.__I18N__[key];
      if (text === undefined) return key;
      if (params) {
        for (const name in params) text = text.split('{' + name + '}').join(params[name]);
      }
      return text;
    };
```

- [ ] **Step 4: Create `templates/settings.html`**

```html
{% extends "base.html" %}
{% block title %}{{ t('settings.title') }} — {{ t('app.name') }}{% endblock %}

{% block shell_body %}
<main class="page">
  <div class="page__head">
    <h2>{{ t('settings.title') }}</h2>
    <p>{{ t('settings.subtitle') }}</p>
  </div>

  <section class="card">
    <label class="field">
      <span>{{ t('settings.language_label') }}</span>
      <select id="set-language">
        {% for entry in languages %}
        <option value="{{ entry.code }}" {% if entry.code == prefs.language %}selected{% endif %}>{{ entry.label }}</option>
        {% endfor %}
      </select>
      <small class="muted">{{ t('settings.language_help') }}</small>
    </label>

    <label class="field">
      <span>{{ t('settings.deck_prefix_label') }}</span>
      <input type="text" id="set-deck-prefix" value="{{ prefs.deck_prefix }}"
        placeholder="{{ t('settings.deck_prefix_placeholder') }}">
      <small class="muted">{{ t('settings.deck_prefix_help') }}</small>
    </label>

    <label class="field">
      <span>{{ t('settings.download_dir_label') }}</span>
      <input type="text" id="set-download-dir" value="{{ prefs.download_dir }}" spellcheck="false">
      <small class="muted">{{ t('settings.download_dir_help') }}</small>
    </label>

    <div class="actions">
      <button type="button" class="btn" id="check-dir-btn">{{ t('settings.check_folder') }}</button>
      <button type="button" class="btn primary" id="save-settings-btn">{{ t('settings.save') }}</button>
      <span class="muted" id="settings-status"></span>
    </div>
  </section>
</main>
{% endblock %}

{% block scripts %}
<script>
  (() => {
    const status = document.getElementById('settings-status');

    document.getElementById('check-dir-btn').addEventListener('click', async () => {
      status.textContent = '…';
      try {
        const res = await fetch('/api/settings/check-dir', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: document.getElementById('set-download-dir').value }),
        });
        const data = await res.json();
        status.textContent = data.message;
        status.className = data.ok ? 'ok' : 'err';
      } catch (e) {
        status.textContent = window.T('js.network_error');
        status.className = 'err';
      }
    });

    document.getElementById('save-settings-btn').addEventListener('click', async () => {
      const payload = {
        language: document.getElementById('set-language').value,
        deck_prefix: document.getElementById('set-deck-prefix').value,
        download_dir: document.getElementById('set-download-dir').value,
      };
      try {
        const res = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error('save failed');
        // La langue ne change l'interface qu'au rendu suivant : on recharge.
        location.reload();
      } catch (e) {
        status.textContent = window.T('js.network_error');
        status.className = 'err';
      }
    });
  })();
</script>
{% endblock %}
```

- [ ] **Step 5: Add the settings-page keys to both catalogs**

`locales/en.json`:

```json
  "settings.title": "Settings",
  "settings.subtitle": "These preferences are stored on this machine only.",
  "settings.language_label": "Interface language",
  "settings.language_help": "Applied as soon as you save.",
  "settings.deck_prefix_label": "Default Anki deck prefix",
  "settings.deck_prefix_placeholder": "e.g. Economics",
  "settings.deck_prefix_help": "Prefilled when you import a course. Leave empty for no prefix.",
  "settings.download_dir_label": "Export folder",
  "settings.download_dir_help": "Exports are written here in addition to your browser download.",
  "settings.check_folder": "Check folder",
  "settings.save": "Save"
```

`locales/fr.json`:

```json
  "settings.title": "Paramètres",
  "settings.subtitle": "Ces préférences sont enregistrées sur cette machine uniquement.",
  "settings.language_label": "Langue de l'interface",
  "settings.language_help": "Appliquée dès l'enregistrement.",
  "settings.deck_prefix_label": "Préfixe de deck Anki par défaut",
  "settings.deck_prefix_placeholder": "ex. Économie",
  "settings.deck_prefix_help": "Pré-rempli à l'import d'un cours. Laisse vide pour aucun préfixe.",
  "settings.download_dir_label": "Dossier d'export",
  "settings.download_dir_help": "Les exports y sont écrits en plus du téléchargement navigateur.",
  "settings.check_folder": "Vérifier le dossier",
  "settings.save": "Enregistrer"
```

- [ ] **Step 6: Verify manually**

Run: `.venv/Scripts/python.exe app.py`
Then in a browser at `http://127.0.0.1:5000/settings`:
- The page renders with three fields; language shows `English` selected.
- "Check folder" on the prefilled path shows "Folder is reachable and writable."
- "Check folder" on `Z:\nope` shows a failure message.
- Switching language to `Français` and saving reloads the page in French.

- [ ] **Step 7: Run the suite and commit**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests`
Expected: `OK`

```bash
git add app.py templates/base.html templates/settings.html templates/help.html locales
git commit -m "feat(settings): add settings page and wire i18n into Flask

A context processor injects t/lang/prefs into every template and serialises
the js. namespace into window.__I18N__, so client and server share one
translation mechanism rather than two.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Empty default deck prefix

**Files:**
- Modify: `parse_cours.py` (`build_deck_path`, the `flush` guard inside `parse_docx`, the `--deck-prefix` CLI default)
- Modify: `project_store.py` (the two `or "ESH"` fallbacks)
- Modify: `app.py` (the `upload()` default)
- Modify: `templates/upload.html` (the deck-prefix field)
- Test: `tests/test_deck_prefix.py`

**Interfaces:**
- Consumes: `settings.load_settings` (via the `prefs` template global from Task 3).
- Produces: `project_store.DEFAULT_DECK_NAME: str` = `"Ankigen"` — the deck written to TSV rows when a project carries no deck at all.

- [ ] **Step 1: Write the failing test**

Create `tests/test_deck_prefix.py`:

```python
#!/usr/bin/env python3
"""
tests/test_deck_prefix.py — Chemins de deck avec et sans préfixe.

Le préfixe par défaut est vide depuis l'ouverture au public : un segment vide
joint naïvement produirait « ::Chapitre », que Anki refuse.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parse_cours import build_deck_path  # noqa: E402
from project_store import DEFAULT_DECK_NAME, export_rows, normalize  # noqa: E402


class TestBuildDeckPath(unittest.TestCase):
    def test_prefix_and_stack(self):
        stack = [(1, "Chapter 1"), (2, "Section A")]
        self.assertEqual(build_deck_path(stack, "Econ"), "Econ::Chapter 1::Section A")

    def test_empty_prefix_produces_no_leading_separator(self):
        stack = [(1, "Chapter 1"), (2, "Section A")]
        self.assertEqual(build_deck_path(stack, ""), "Chapter 1::Section A")

    def test_none_prefix_behaves_like_empty(self):
        self.assertEqual(build_deck_path([(1, "Chapter 1")], None), "Chapter 1")

    def test_whitespace_only_prefix_behaves_like_empty(self):
        self.assertEqual(build_deck_path([(1, "Chapter 1")], "   "), "Chapter 1")

    def test_never_starts_or_ends_with_the_separator(self):
        for prefix in ("", "   ", None, "Econ"):
            path = build_deck_path([(1, "Chapter 1")], prefix)
            self.assertFalse(path.startswith("::"), f"préfixe {prefix!r} → {path!r}")
            self.assertFalse(path.endswith("::"), f"préfixe {prefix!r} → {path!r}")

    def test_empty_stack_and_empty_prefix_is_empty(self):
        self.assertEqual(build_deck_path([], ""), "")


class TestExportDeckFallback(unittest.TestCase):
    """Une ligne TSV sans nom de deck est refusée par Anki : il faut un repli."""

    def test_prompt_without_deck_falls_back_to_the_app_name(self):
        project = normalize({
            "version": 2,
            "deck_prefix": "",
            "assets": {},
            "prompts": [{
                "id": 0, "deck": "", "blocks": [], "assets": [],
                "prompt": "", "status": "done", "response": "Q\tA",
            }],
        })
        rows, _ = export_rows(project)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], DEFAULT_DECK_NAME)

    def test_prompt_with_a_deck_keeps_it(self):
        project = normalize({
            "version": 2,
            "deck_prefix": "",
            "assets": {},
            "prompts": [{
                "id": 0, "deck": "Chapter 1", "blocks": [], "assets": [],
                "prompt": "", "status": "done", "response": "Q\tA",
            }],
        })
        rows, _ = export_rows(project)
        self.assertEqual(rows[0][0], "Chapter 1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_deck_prefix.py" -v`
Expected: FAIL — `ImportError: cannot import name 'DEFAULT_DECK_NAME'`, and `test_empty_prefix_produces_no_leading_separator` would give `'::Chapter 1::Section A'`.

- [ ] **Step 3: Fix `parse_cours.build_deck_path`**

Replace the whole function:

```python
def build_deck_path(stack, prefix):
    """
    Chemin de deck Anki depuis la pile hiérarchique.

    Le préfixe est optionnel depuis l'ouverture au public. On filtre les segments
    vides au lieu de les joindre : `"::".join(["", "Chapitre"])` donnerait
    « ::Chapitre », que Anki refuse.
    """
    segments = [(prefix or "").strip()] + [title for _, title in stack]
    return "::".join(segment for segment in segments if segment)
```

- [ ] **Step 4: Fix the `flush` guard in `parse_docx`**

In `parse_cours.parse_docx`, replace these two lines inside `flush`:

```python
        # `deck != deck_prefix` : on ignore le contenu antérieur au premier titre
        # (ligne de titre du chapitre, intro) — comportement aligné sur main.
        if has_content and deck != deck_prefix:
```

with:

```python
        # `stack` vide = on n'est pas encore entré dans une section : c'est le
        # contenu antérieur au premier titre (ligne de titre, intro), qu'on
        # ignore. L'ancienne condition `deck != deck_prefix` disait la même chose
        # de façon détournée, et devenait fausse avec un préfixe vide.
        if has_content and stack:
```

- [ ] **Step 5: Change the CLI default**

In `parse_cours.main`, replace:

```python
    parser.add_argument("--deck-prefix", default="*ESH*", help="Nom du deck racine Anki")
```

with:

```python
    parser.add_argument("--deck-prefix", default="",
                        help="Préfixe de deck Anki (vide par défaut)")
```

- [ ] **Step 6: Replace the `"ESH"` fallbacks in `project_store.py`**

Add near `PROJECT_VERSION = 2`:

```python
# Nom de deck de dernier recours pour une ligne TSV : Anki refuse un champ deck
# vide. Ce n'est pas de la copie d'interface mais un identifiant de deck, donc il
# n'est pas traduit — sinon un même projet exporté dans deux langues créerait
# deux decks différents dans Anki.
DEFAULT_DECK_NAME = "Ankigen"
```

In `list_projects`, replace:

```python
            "deck": project["prompts"][0].get("deck") or project.get("deck_prefix") or "ESH",
```

with:

```python
            "deck": project["prompts"][0].get("deck") or project.get("deck_prefix") or "",
```

In `export_rows`, replace:

```python
        deck = prompt.get("deck") or project.get("deck_prefix") or "ESH"
```

with:

```python
        deck = prompt.get("deck") or project.get("deck_prefix") or DEFAULT_DECK_NAME
```

- [ ] **Step 7: Change the upload default in `app.py`**

Replace:

```python
    deck_prefix = (request.form.get("deck_prefix") or "*ESH*").strip() or "*ESH*"
```

with:

```python
    deck_prefix = (request.form.get("deck_prefix") or "").strip()
```

- [ ] **Step 8: Update the field in `templates/upload.html`**

Replace:

```html
        <label class="field">
          <span>Préfixe de deck Anki</span>
          <input type="text" name="deck_prefix" value="*ESH*" required>
        </label>
```

with:

```html
        <label class="field">
          <span>{{ t('upload.deck_prefix_label') }}</span>
          <input type="text" name="deck_prefix" value="{{ prefs.deck_prefix }}"
            placeholder="{{ t('upload.deck_prefix_placeholder') }}">
          <small class="muted">{{ t('upload.deck_prefix_help') }}</small>
        </label>
```

And in the project list, replace `{{ proj.deck }}` with:

```html
              {{ proj.deck or t('project.no_deck') }}
```

- [ ] **Step 9: Add the keys to both catalogs**

`locales/en.json`:

```json
  "upload.deck_prefix_label": "Anki deck prefix",
  "upload.deck_prefix_placeholder": "Optional — e.g. Economics",
  "upload.deck_prefix_help": "Prepended to every deck built from the document's headings.",
  "project.no_deck": "No prefix"
```

`locales/fr.json`:

```json
  "upload.deck_prefix_label": "Préfixe de deck Anki",
  "upload.deck_prefix_placeholder": "Optionnel — ex. Économie",
  "upload.deck_prefix_help": "Placé devant chaque deck construit depuis les titres du document.",
  "project.no_deck": "Sans préfixe"
```

- [ ] **Step 10: Run the suite**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -v`
Expected: `OK`. The existing `tests/test_docx_media.py` exercises `parse_docx` — if it passes a non-empty prefix, it must still pass unchanged.

- [ ] **Step 11: Commit**

```bash
git add parse_cours.py project_store.py app.py templates/upload.html locales tests/test_deck_prefix.py
git commit -m "feat(decks): make the deck prefix optional and default to empty

Joining an empty prefix produced '::Chapter', which Anki rejects, so empty
segments are now filtered out. The flush guard said 'we are inside a
section' via 'deck != deck_prefix'; it now says so directly, which an
empty prefix no longer breaks.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Rename to Ankigen and ship the logo

**Files:**
- Modify: `templates/base.html` (the `#i-logo` symbol)
- Create: `static/logo.svg`
- Modify: `src-tauri/tauri.conf.json:3` (`productName`) and the window `title`
- Modify: `scripts/generate-dist-tauri.js` (title, heading, splash copy)
- Modify: `package.json` (`description`)
- Modify: `README.md`
- Modify: docstring headers of `app.py`, `launcher.py`, `parse_cours.py`, `updater.py`

**Interfaces:**
- Consumes: `t('app.name')` from Task 1.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Replace the `#i-logo` symbol in `templates/base.html`**

Replace:

```html
    <symbol id="i-logo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"></rect><path d="M3 9h18M9 21V9"></path>
    </symbol>
```

with:

```html
    <!-- Marque Ankigen : deux cartes décalées (recto/verso) + étincelle de génération.
         Dupliqué dans static/logo.svg, qui sert hors HTML (README, icônes) et ne peut
         pas lire les variables CSS de la page. Toute retouche va aux deux endroits. -->
    <symbol id="i-logo" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <rect x="2.5" y="6" width="12" height="15.5" rx="2.5"
        transform="rotate(-9 8.5 13.75)"></rect>
      <rect x="8.5" y="2.5" width="13" height="16" rx="2.5" fill="var(--surface)"></rect>
      <path d="M12 7.5h6M12 11h3.5"></path>
      <path d="M17.8 13.4l.85 1.95 1.95.85-1.95.85-.85 1.95-.85-1.95-1.95-.85 1.95-.85z"
        fill="var(--accent)" stroke="var(--accent)" stroke-width="1.1"></path>
    </symbol>
```

- [ ] **Step 2: Create `static/logo.svg`**

Standalone copy with literal colours — a file loaded outside the page cannot resolve `var(--accent)`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="256" height="256"
  fill="none" stroke="#1D1D1F" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"
  role="img" aria-label="Ankigen">
  <!-- Copie autonome du symbole #i-logo de templates/base.html.
       Les couleurs y sont littérales : hors page, var(--accent) ne résout pas. -->
  <rect x="2.5" y="6" width="12" height="15.5" rx="2.5" transform="rotate(-9 8.5 13.75)"/>
  <rect x="8.5" y="2.5" width="13" height="16" rx="2.5" fill="#FFFFFF"/>
  <path d="M12 7.5h6M12 11h3.5"/>
  <path d="M17.8 13.4l.85 1.95 1.95.85-1.95.85-.85 1.95-.85-1.95-1.95-.85 1.95-.85z"
    fill="#0071E3" stroke="#0071E3" stroke-width="1.1"/>
</svg>
```

- [ ] **Step 3: Check the logo at both sizes**

Run: `.venv/Scripts/python.exe app.py`, open `http://127.0.0.1:5000`.
Expected: the mark in the topbar at 22 px reads as two stacked cards, the spark is a distinct dot rather than a smudge. Then open `http://127.0.0.1:5000/static/logo.svg` directly — same drawing, visible at full size.
If the spark is illegible at 22 px, thicken its `stroke-width` to `1.4` in **both** files and re-check.

- [ ] **Step 4: Rename the product surfaces**

`src-tauri/tauri.conf.json` — replace `"productName": "Anki Gen"` with `"productName": "Ankigen"`, and the window `"title": "Anki Gen"` with `"title": "Ankigen"`. Leave `"identifier": "ankiesh"` untouched.

`scripts/generate-dist-tauri.js` — replace `<title>Anki Gen</title>` with `<title>Ankigen</title>`, `<h1>Anki Gen</h1>` with `<h1>Ankigen</h1>`, and translate the two splash paragraphs to English (this page is shown before Flask answers, so it cannot read the user's language setting):

```html
  <p>Starting the local server…</p>
  <p>If the interface does not appear, make sure the application is allowed through your firewall and try again.</p>
```

`package.json` — set `"description": "Turn a .docx course into an Anki deck, with Claude in the loop."`

- [ ] **Step 5: Update the docstring headers**

In `app.py`, `launcher.py`, `parse_cours.py`, `updater.py`, replace every occurrence of `Anki ESH` with `Ankigen` in the module docstrings only. Do **not** touch `ANKI_ESH_SIDECAR` in `launcher.py` — it is the contract with `src-tauri/src/lib.rs`.

Verify nothing else moved:

Run: `git diff --stat` then `grep -rn "ANKI_ESH_SIDECAR" launcher.py src-tauri/src/lib.rs`
Expected: two matches, both unchanged.

- [ ] **Step 6: Update `README.md`**

Rewrite the title and intro around the name Ankigen, reference the logo (`static/logo.svg`), and state the two commands that actually work:

```markdown
Run the app: `.venv/Scripts/python.exe app.py`
Run the tests: `.venv/Scripts/python.exe -m unittest discover -s tests`
```

Do not document any command you have not executed.

- [ ] **Step 7: Run the suite and commit**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests`
Expected: `OK`

```bash
git add templates/base.html static/logo.svg src-tauri/tauri.conf.json scripts/generate-dist-tauri.js package.json README.md app.py launcher.py parse_cours.py updater.py
git commit -m "feat(brand): rename the product to Ankigen and add a logo

Visible surfaces only. The Tauri identifier, the %APPDATA%/AnkiGen data
folder and ANKI_ESH_SIDECAR keep their names: renaming them would create
a second install instead of updating the existing one.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Translate the remaining UI

**Files:**
- Modify: `templates/upload.html` (all remaining copy)
- Modify: `templates/work.html` (all remaining copy)
- Modify: `templates/base.html` (update-banner script strings)
- Modify: `static/app.js` (all hardcoded strings, via `window.T`)
- Modify: `app.py` (the JSON error strings and `render_template` error messages)
- Modify: `updater.py` (French messages become keys)
- Modify: `locales/en.json`, `locales/fr.json`

**Interfaces:**
- Consumes: `t()` in templates, `window.T()` in JS, `tr()` in `app.py`, all from Task 3.
- Produces: `updater.check_and_update()` now returns `{"status", "version", "message_key", "message_params"}` instead of `{"status", "version", "message"}`. `app.py` translates it before serialising.

- [ ] **Step 1: Convert `updater.py` messages to keys**

In `check_and_update`, replace each returned `"message"` with a key plus params:

```python
        if remote_version == local_version:
            return {
                "status": "up_to_date",
                "version": local_version,
                "message_key": "update.up_to_date",
                "message_params": {},
            }
```

```python
            return {
                "status": "error",
                "version": local_version,
                "message_key": "update.asset_missing",
                "message_params": {},
            }
```

```python
        return {
            "status": "staged",
            "version": remote_version,
            "message_key": "update.staged",
            "message_params": {"version": remote_version},
        }
```

```python
    except URLError:
        return {
            "status": "error",
            "version": get_local_version(),
            "message_key": "update.offline",
            "message_params": {},
        }
    except Exception as e:
        return {
            "status": "error",
            "version": get_local_version(),
            "message_key": "update.failed",
            "message_params": {"error": str(e)},
        }
```

Update the function docstring accordingly: it now documents `message_key` / `message_params`, and states that translation belongs to the caller so this module stays i18n-free.

- [ ] **Step 2: Translate in `app.py` at the boundary**

Replace the body of `api_update_apply`:

```python
@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    """Applique la mise à jour depuis GitHub Releases."""
    from updater import check_and_update
    result = check_and_update()
    result["message"] = tr(result.pop("message_key"), **result.pop("message_params"))
    status_code = 200 if result["status"] != "error" else 500
    return jsonify(result), status_code
```

Replace the three hardcoded French strings in `upload()`:

```python
        return render_template(
            "upload.html", error=tr("upload.error_not_docx"), projects=list_projects()
        ), 400
```

```python
        return render_template(
            "upload.html", error=tr("upload.error_parsing", error=e), projects=list_projects()
        ), 500
```

```python
                error=tr("upload.error_no_chunks"),
```

Replace the JSON error strings:

| Location | Was | Becomes |
|---|---|---|
| `api_save` | `error="Projet introuvable."` | `error=tr("api.project_not_found")` |
| `api_save`, `api_preview` | `error="id manquant ou invalide"` | `error=tr("api.bad_id")` |
| `api_save`, `api_preview` | `error=f"chunk {chunk_id} introuvable"` | `error=tr("api.chunk_not_found", id=chunk_id)` |
| `api_asset` | `error=f"asset {asset_id} introuvable"` | `error=tr("api.asset_not_found", id=asset_id)` |
| `api_export_anki_media` | `error="Dossier collection.media inconnu ou introuvable."` | `error=tr("api.unknown_media_dir")` |
| `api_export_anki_media` | `message="Aucune image utilisée par les cartes."` | `message=tr("api.no_media_used")` |

- [ ] **Step 3: Translate the ZIP archive's readme**

In `export_zip`, replace the `zf.writestr("LISEZ-MOI.txt", ...)` call with:

```python
        # Le nom du fichier suit la langue : un francophone ne cherche pas README.txt.
        zf.writestr(
            tr("export.readme_filename"),
            "\r\n".join([
                tr("export.readme_title", project=project_id),
                "",
                tr("export.readme_counts", cards=report["cards"], images=len(report["media"])),
                "",
                tr("export.readme_step_media"),
                tr("export.readme_step_media_path"),
                tr("export.readme_step_import"),
                "",
                tr("export.readme_tip"),
            ]),
        )
```

- [ ] **Step 4: Translate `templates/upload.html` and `templates/work.html`**

Replace every remaining literal French string with `{{ t('...') }}`, using these key names:

`upload.html`: `upload.page_title`, `upload.page_subtitle`, `upload.new_course`, `upload.new_course_help`, `upload.file_label`, `upload.drop_hint`, `upload.submit`, `upload.resume`, `upload.projects_count`, `upload.empty_state`, `project.continue`, `project.delete`, `project.delete_confirm`.

`work.html`: `work.chunk_list`, `work.close_list`, `work.progress_title`, `work.export`, `work.export_computing`, `work.export_tsv`, `work.export_tsv_help`, `work.export_zip`, `work.export_zip_help`, `work.copy_media`, `work.copy_media_help`, `work.tab_source`, `work.tab_answer`, `work.view_preview`, `work.view_text`, `work.answer_label`, `work.answer_format`, `work.answer_edit`, `work.answer_cards`, `work.response_placeholder`, `work.drop_tsv`, `work.prev`, `work.next`, `work.copy`, `work.paste`, `work.preview`, `work.save`, `work.save_next`.

The `{% block title %}` of `work.html` becomes:

```html
{% block title %}{{ project_id }} — {{ t('app.name') }}{% endblock %}
```

The JS string inside the delete confirmation must go through `window.T`:

```html
              onsubmit="return confirm(window.T('js.delete_confirm'));"
```

- [ ] **Step 5: Translate `static/app.js`**

Replace each hardcoded string with a `window.T` call. This is the **complete** list, produced by the extraction script in Step 8 — work through it line by line:

| Line (current) | String | Key | Params |
|---|---|---|---|
| 101 | `image du {{TABLE:n}}` | `js.image_in_table` | `n` |
| 103 | `Décris cette image pour Claude…` | `js.alt_placeholder` | — |
| 120 | `Insérer :` | `js.insert` | — |
| 177 | `${cards.length} carte(s)` | `js.cards_count` | `n` |
| 177 | `· ${media} média(s)` | `js.media_count` | `n` |
| 195 | `Aucune carte à prévisualiser — colle d'abord…` | `js.no_cards_to_preview` | — |
| 222 | `Éditer` / `Aperçu` | `js.edit` / `js.preview` | — |
| 248 | `✓ Chunk #${p.id} enregistré — ${n} carte(s)` | `js.chunk_saved` | `id`, `n` |
| 255 | `Dernier chunk : tout est enregistré.` | `js.all_saved` | — |
| 293 | `✓ ${n} chunk(s)` | `js.alt_saved` | `n` |
| 336 | `Texte sélectionné — appuie sur Ctrl+C` | `js.selected_press_ctrl_c` | — |
| 338 | `✗ Copie impossible` | `js.copy_failed` | — |
| 348 | `Presse-papier vide` | `js.clipboard_empty` | — |
| 352 | `✓ Réponse collée` | `js.response_pasted` | — |
| 355 | `Autorise le presse-papier, ou colle avec Ctrl+V` | `js.clipboard_denied` | — |
| 367 | `Calcul du rapport…` | `js.computing_report` | — |
| 372 | `${data.cards} carte(s)` | `js.cards_count` | `n` |
| 372 | `${n} image(s) utilisée(s)` | `js.images_used` | `n` |
| 373 | `${n} image(s) non exploitée(s)` | `js.images_unused` | `n` |
| 374 | `${n} placeholder(s) orphelin(s)` | `js.orphan_placeholders` | `n` |
| 377 | `Rapport indisponible.` | `js.report_unavailable` | — |
| 386 | `Aucun profil Anki détecté…` | `js.no_anki_profile` | — |
| 390 | `Anki doit être fermé. Choisis le profil :` | `js.choose_profile` | — |
| 398 | `Copie en cours…` | `js.copying` | — |
| 409 | `${n} copiée(s)` | `js.copied_count` | `n` |
| 410 | `${n} déjà à jour` | `js.already_current` | `n` |
| 411 | `⚠️ ${n} conflit(s) : ${names}` | `js.conflicts` | `n`, `names` |
| 412 | `⚠️ ${n} introuvable(s)` | `js.missing_count` | `n` |
| 462 | `✓ Paragraphe copié` | `js.paragraph_copied` | — |
| 540 | `✓ ${file.name} chargé` | `js.file_loaded` | `name` |
| 577 | `${n} image(s) sans description` | `js.missing_alt` | `n` |

Lines 259, 301 and 417 interpolate `${e.message}` — an exception string, not translatable copy. Leave the `✗ ` prefix and the interpolation alone.

Example of the transformation, for line 248:

```javascript
      toast(window.T('js.chunk_saved', { id: p.id, n: data.cards_detected }), "ok");
```

Delete the `copy-system-btn` handler at lines 428–429 — Task 8 removes the button it targets.

- [ ] **Step 6: Translate the update banner in `templates/base.html`**

Replace the three literals in the inline script:

```javascript
            window.T('js.update_available', { version: data.remote_version });
```
```javascript
      updBtn.textContent = window.T('js.updating');
```
```javascript
          updBtn.textContent = window.T('js.restart');
```
```javascript
          updBtn.textContent = window.T('js.retry');
```
```javascript
        document.getElementById('update-message').textContent = window.T('js.network_error');
```

And the static button label:

```html
      <button id="update-btn" type="button" class="update-apply">{{ t('update.button') }}</button>
```

- [ ] **Step 7: Fill both catalogs**

Add every key named in Steps 1–6 to `locales/en.json` and `locales/fr.json`. The French value is the string that was previously hardcoded; the English value is its translation. For the `(s)` plural strings, keep the convention: `"js.cards_count": "{n} card(s)"` / `"{n} carte(s)"`.

The parity test from Task 1 is what proves nothing was missed on one side.

- [ ] **Step 8: Prove no French string was left hardcoded**

**Do not use an accent-based grep for this.** It silently misses accent-free French — `"Presse-papier vide"` and `"Autorise le presse-papier, ou colle avec Ctrl+V"` both slip through one, and both are user-facing. Extract every string literal instead and read the list:

```bash
.venv/Scripts/python.exe - <<'PY'
import io, re
for path in ("static/app.js", "templates/base.html"):
    lines = io.open(path, encoding="utf-8").read().split("\n")
    pattern = re.compile(r'''["'`]([^"'`\n]{8,})["'`]''')
    found = []
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("//"):
            continue
        for match in pattern.findall(line):
            if "<" in match or ">" in match or match.startswith(".") or "max-width" in match:
                continue
            if " " not in match or re.match(r"^[a-z0-9\- ]+$", match):
                continue
            found.append(f"{i} :: {match}")
    io.open("strings-audit.txt", "a", encoding="utf-8").write(
        f"\n=== {path} ===\n" + "\n".join(found) + "\n")
PY
```

Then read `strings-audit.txt` (it is UTF-8; `type` in a cp1252 console will mangle it — open it in an editor). Every remaining entry must be either a `window.T(...)` call, a template-literal of interpolated values only (`${a}/${b}`), or an `${e.message}` exception passthrough. Delete `strings-audit.txt` before committing.

For the Python and Jinja sides, an accent grep is enough since those files have no accent-free French copy, but verify by eye:

```bash
grep -n "error=\|message=" app.py
grep -n ">[A-ZÀ-Ý]" templates/upload.html templates/work.html
```

- [ ] **Step 9: Verify manually in both languages**

Run: `.venv/Scripts/python.exe app.py`
- In English: upload a `.docx`, save a chunk, open the export menu, export a ZIP. Every label, toast and the archive's `README.txt` are English.
- Switch to French in `/settings`, repeat. Everything is French and the archive is named `LISEZ-MOI.txt`.
- Confirm no `key.like.this` text appears anywhere — that is the signature of a key missing from both catalogs.

- [ ] **Step 10: Run the suite and commit**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests`
Expected: `OK`

```bash
git add templates static/app.js app.py updater.py locales
git commit -m "feat(i18n): translate every UI surface into EN and FR

updater.py now returns message keys instead of French text, so it stays
free of any i18n dependency and the translation happens in app.py, which
is the layer that knows the user's language.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Export to the configured folder

**Files:**
- Modify: `app.py` (`export_tsv`, `export_zip`, plus a new `_write_export_copy` helper)
- Modify: `templates/work.html` (the two export `<a>` become `<button>`)
- Modify: `static/app.js` (fetch-based download)
- Modify: `locales/en.json`, `locales/fr.json`

**Interfaces:**
- Consumes: `settings.resolve_download_dir()` from Task 2, `tr()` from Task 3.
- Produces: both export responses carry `X-Export-Path` (percent-encoded, possibly empty) and, on failure, `X-Export-Error` (translated, ASCII-safe).

- [ ] **Step 1: Add the helper to `app.py`**

Add `from urllib.parse import quote` to the imports, then insert next to `tsv_bytes`:

```python
def _write_export_copy(filename, data):
    """
    Écrit une copie de l'export dans le dossier choisi par l'utilisateur.

    Retourne (chemin, None) ou (None, clé de message). Un réglage devenu invalide
    doit dégrader l'export en simple téléchargement, jamais le faire échouer :
    l'utilisateur veut son fichier, pas un message d'erreur sur un réglage.
    """
    directory = user_settings.resolve_download_dir()
    if directory is None:
        return None, "export.dir_unavailable"
    try:
        target = directory / filename
        target.write_bytes(data)
        return str(target), None
    except OSError:
        return None, "export.write_failed"


def _with_export_headers(response, filename, data):
    """
    Ajoute X-Export-Path / X-Export-Error à une réponse d'export.

    Le chemin est percent-encodé : les en-têtes HTTP sont encodés en latin-1 par
    WSGI, et un dossier utilisateur peut contenir n'importe quel caractère. Le JS
    le repasse par decodeURIComponent.
    """
    path, error = _write_export_copy(filename, data)
    response.headers["X-Export-Path"] = quote(path or "")
    if error:
        response.headers["X-Export-Error"] = quote(tr(error))
    return response
```

- [ ] **Step 2: Use it in both export routes**

Replace the tail of `export_tsv`:

```python
    rows, report = export_rows(project, only_done=only_done)
    data = tsv_bytes(rows)
    filename = f"{project_id}_export.tsv"

    response = send_file(
        io.BytesIO(data),
        mimetype="text/tab-separated-values; charset=utf-8",
        as_attachment=True,
        download_name=filename,
    )
    return _with_export_headers(response, filename, data)
```

> The previous unconditional write to `EXPORT_DIR` is gone — the user's chosen folder replaces it. `paths.EXPORT_DIR` stays as the default value of the setting, so out of the box the behaviour is the same as before.

At the end of `export_zip`, replace the final `send_file` with:

```python
    buf.seek(0)
    data = buf.getvalue()
    filename = f"{project_id}_export.zip"
    response = send_file(
        io.BytesIO(data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )
    return _with_export_headers(response, filename, data)
```

- [ ] **Step 3: Turn the export links into buttons in `templates/work.html`**

Replace the two `<a class="export-item" href="...">` elements with:

```html
      <button type="button" class="export-item" id="export-tsv-btn"
        data-export-url="{{ url_for('export_tsv', project_id=project_id) }}">
        <strong>{{ t('work.export_tsv') }}</strong>
        <span class="muted">{{ t('work.export_tsv_help') }}</span>
      </button>
      <button type="button" class="export-item" id="export-zip-btn"
        data-export-url="{{ url_for('export_zip', project_id=project_id) }}">
        <strong>{{ t('work.export_zip') }}</strong>
        <span class="muted">{{ t('work.export_zip_help') }}</span>
      </button>
```

- [ ] **Step 4: Add the download handler to `static/app.js`**

Add near the other export handlers:

```javascript
  // ── Export : télécharge ET écrit dans le dossier configuré ───
  async function runExport(url) {
    exportStatus.textContent = window.T('js.exporting');
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error('export failed');

      const blob = await res.blob();
      const name = (res.headers.get('Content-Disposition') || '')
        .split('filename=').pop().replace(/["';]/g, '') || 'export';

      // Le sandbox ne bloque pas un download local : on passe par un lien objet.
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(href);

      const error = res.headers.get('X-Export-Error');
      const path = res.headers.get('X-Export-Path');
      if (error) {
        toast(decodeURIComponent(error), 'err', 5000);
        exportStatus.textContent = '';
      } else if (path) {
        const decoded = decodeURIComponent(path);
        toast(window.T('js.exported_to', { path: decoded }), 'ok', 4000);
        exportStatus.textContent = decoded;
      }
    } catch (e) {
      toast(window.T('js.export_failed'), 'err');
      exportStatus.textContent = '';
    }
  }

  ["export-tsv-btn", "export-zip-btn"].forEach((id) => {
    const btn = $(id);
    if (btn) btn.addEventListener("click", () => runExport(btn.dataset.exportUrl));
  });
```

- [ ] **Step 5: Add the keys to both catalogs**

`locales/en.json`:

```json
  "export.dir_unavailable": "Export folder unavailable — check it in Settings. The download still worked.",
  "export.write_failed": "Could not write to the export folder. The download still worked.",
  "js.exporting": "Exporting…",
  "js.exported_to": "Exported to {path}",
  "js.export_failed": "Export failed."
```

`locales/fr.json`:

```json
  "export.dir_unavailable": "Dossier d'export indisponible — vérifie-le dans les paramètres. Le téléchargement a bien eu lieu.",
  "export.write_failed": "Écriture impossible dans le dossier d'export. Le téléchargement a bien eu lieu.",
  "js.exporting": "Export en cours…",
  "js.exported_to": "Exporté vers {path}",
  "js.export_failed": "Échec de l'export."
```

- [ ] **Step 6: Verify manually, including the degraded path**

Run: `.venv/Scripts/python.exe app.py`
1. With a valid export folder: click "TSV only". The browser downloads the file **and** a toast shows the absolute path. Confirm the file is actually on disk at that path.
2. Same for ZIP.
3. In `/settings`, set the export folder to `Z:\nope` (a drive that does not exist) and save. Export again: the download still happens, and a warning toast explains the folder is unavailable. **The export must not fail.**
4. Set the folder to a path containing a non-ASCII character (e.g. `…\Téléchargements test\`). Export: the toast shows the correct path, with no `UnicodeEncodeError` in the server console.

- [ ] **Step 7: Run the suite and commit**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests`
Expected: `OK`

```bash
git add app.py templates/work.html static/app.js locales
git commit -m "feat(export): write exports to the configured folder

Both exports now write into the user's folder and report the absolute
path via X-Export-Path, percent-encoded because WSGI encodes headers as
latin-1 and a home folder can contain anything.

An unusable folder degrades to a plain download with a warning rather
than failing the export: the user wants the file, not a settings error.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Remove the system prompt, build the help page

**Files:**
- Modify: `parse_cours.py` (delete `SYSTEM_PROMPT`, drop `"system"` from `build_prompts`)
- Modify: `app.py` (drop the import and the `system_prompt` template argument)
- Modify: `templates/work.html` (delete `#copy-system-btn` and `window.__SYSTEM_PROMPT__`)
- Modify: `project_store.py` (docstring: `system` is now a legacy field)
- Rewrite: `templates/help.html` (the stub from Task 3)
- Modify: `locales/en.json`, `locales/fr.json`

**Interfaces:**
- Consumes: `t()` from Task 3.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Delete `SYSTEM_PROMPT` from `parse_cours.py`**

Remove the entire `SYSTEM_PROMPT = """..."""` assignment (currently `parse_cours.py:33-59`) and the `"system": SYSTEM_PROMPT,` line inside `build_prompts`.

- [ ] **Step 2: Remove its uses in `app.py`**

Change the import:

```python
from parse_cours import build_prompts, parse_docx
```

And in `work()`, delete this line:

```python
        system_prompt=project["prompts"][0].get("system") or SYSTEM_PROMPT,
```

- [ ] **Step 3: Remove the button in `templates/work.html`**

Delete the whole `<button type="button" class="export-item" id="copy-system-btn">…</button>` element, and the line:

```html
  window.__SYSTEM_PROMPT__ = {{ system_prompt | tojson }};
```

(The JS handler was already removed in Task 6, Step 5.)

- [ ] **Step 4: Note the legacy field in `project_store.py`**

In the module docstring, change the prompt field list to mark `system` as legacy:

```
  "prompts": [{"id", "deck", "blocks", "assets", "prompt",
               "status", "response"}]
}

Les projets créés avant l'ouverture au public portent un champ `system` (l'ancien
prompt ESH embarqué). Il est conservé tel quel sur disque et simplement ignoré :
le flux repose désormais sur un Skill Claude côté utilisateur, décrit dans /help.
```

- [ ] **Step 5: Write `templates/help.html`**

```html
{% extends "base.html" %}
{% block title %}{{ t('nav.help') }} — {{ t('app.name') }}{% endblock %}

{% block shell_body %}
<main class="page">
  <div class="page__head">
    <h2>{{ t('help.title') }}</h2>
    <p>{{ t('help.intro') }}</p>
  </div>

  <section class="card">
    <h3>{{ t('help.workflow_title') }}</h3>
    <ol class="help-steps">
      <li>{{ t('help.step_upload') }}</li>
      <li>{{ t('help.step_chunks') }}</li>
      <li>{{ t('help.step_claude') }}</li>
      <li>{{ t('help.step_paste') }}</li>
      <li>{{ t('help.step_export') }}</li>
      <li>{{ t('help.step_import') }}</li>
    </ol>
  </section>

  <section class="card">
    <h3>{{ t('help.skill_title') }}</h3>
    <p class="muted">{{ t('help.skill_intro') }}</p>
    <p class="muted">{{ t('help.skill_location') }}</p>

    <div class="block-head">
      <h4>{{ t('help.skill_template_title') }}</h4>
      <button type="button" class="btn sm" id="copy-skill-btn">{{ t('help.copy') }}</button>
    </div>
    <pre id="skill-template" class="prompt-text">{% raw %}---
name: course-to-anki
description: Use when turning a paragraph of course material into Anki
  flashcards. Outputs tab-separated QUESTION/ANSWER rows, nothing else.
---

# Course paragraph to Anki cards

You convert one paragraph of course material into Anki flashcards.

## Output format — this is the contract

Return ONLY tab-separated rows. One row per card:

    QUESTION<TAB>ANSWER

No preamble, no confirmation, no closing remark, no markdown fences.
Anything else breaks the import.

## Card content

- Exhaustive: every fact, mechanism, figure and concept in the paragraph
  becomes a card. Nothing is dropped as "minor".
- One idea per card. A card that needs "and" in its answer is two cards.
- The question must be answerable without seeing the paragraph.

## Formatting

Cards are raw HTML. Use inline styles to make key elements stand out, and
keep the same convention across a whole deck so cards look consistent:

- Dates: <span style="color: red; font-weight: bold;">1929</span>
- Quotes: <span style="background-color: plum; font-style: italic;">"…"</span>
- Works and authors: <span style="background-color: yellow;">Title (Year)</span>
- Key terms: <span style="color: red; font-weight: bold;">term</span>
- Lists: <ul><li>…</li></ul>
- Maths: [latex]$x = y$[/latex]

## Images and tables — required convention

The paragraph may contain [IMAGE n] markers (with a description) and
[TABLE n] markers (with markdown content).

- To show an image, write exactly {{IMG:n}} where it belongs.
- To reuse a table, write exactly {{TABLE:n}}.
- NEVER write an <img> tag and NEVER invent a filename. The application
  substitutes these placeholders with the real file at export time; a
  hand-written tag points at nothing.
- A chart or diagram usually deserves its own card: question on the front,
  {{IMG:n}} plus the interpretation on the back.
- A data table deserves one recall card ({{TABLE:n}} on the back) plus
  targeted cards on the striking values.
- If an image has no description, do not guess what it shows.
{% endraw %}</pre>
  </section>

  <section class="card">
    <h3>{{ t('help.anki_title') }}</h3>
    <ol class="help-steps">
      <li>{{ t('help.anki_media') }}</li>
      <li>{{ t('help.anki_import') }}</li>
      <li>{{ t('help.anki_header') }}</li>
    </ol>
  </section>
</main>
{% endblock %}

{% block scripts %}
<script>
  document.getElementById('copy-skill-btn').addEventListener('click', async () => {
    const btn = document.getElementById('copy-skill-btn');
    try {
      await navigator.clipboard.writeText(document.getElementById('skill-template').textContent);
      btn.textContent = window.T('js.copied');
      setTimeout(() => { btn.textContent = window.T('js.copy'); }, 1400);
    } catch (e) {
      btn.textContent = window.T('js.copy_failed');
    }
  });
</script>
{% endblock %}
```

> **The `{% raw %}` wrapper is mandatory.** The template contains `{{IMG:n}}` and `{{TABLE:n}}`, which Jinja would otherwise try to evaluate as expressions and render as empty strings — silently destroying the very convention the page is teaching.

- [ ] **Step 6: Add the help keys to both catalogs**

Add `help.title`, `help.intro`, `help.workflow_title`, `help.step_upload`, `help.step_chunks`, `help.step_claude`, `help.step_paste`, `help.step_export`, `help.step_import`, `help.skill_title`, `help.skill_intro`, `help.skill_location`, `help.skill_template_title`, `help.copy`, `help.anki_title`, `help.anki_media`, `help.anki_import`, `help.anki_header`, `js.copied`, `js.copy`, `js.copy_failed` to both files.

English values, for reference:

```json
  "help.title": "How Ankigen works",
  "help.intro": "Ankigen turns a structured .docx course into an Anki deck, with you and Claude in the loop — it never invents cards on its own.",
  "help.workflow_title": "The workflow",
  "help.step_upload": "Import a .docx whose headings use real heading styles — that is what the splitting relies on.",
  "help.step_chunks": "Ankigen splits the document into chunks, one per section, and derives an Anki deck path from the heading hierarchy.",
  "help.step_claude": "Copy a chunk and send it to Claude, which has your card-writing skill loaded.",
  "help.step_paste": "Paste Claude's tab-separated answer back, check the card preview, save, move to the next chunk.",
  "help.step_export": "Export as TSV, or as ZIP when your cards use images.",
  "help.step_import": "Import into Anki.",
  "help.skill_title": "Create your Claude Skill",
  "help.skill_intro": "A skill is a folder holding a SKILL.md file: YAML frontmatter with a name and a description saying when to use it, then the instructions in Markdown. Claude loads it when the task matches, so you never paste the same instructions twice.",
  "help.skill_location": "Put it in your Claude skills folder, one folder per skill, then start a conversation and send it a chunk.",
  "help.skill_template_title": "Starter template",
  "help.copy": "Copy",
  "help.anki_title": "Importing into Anki",
  "help.anki_media": "If your cards use images, copy everything in the export's media/ folder into your Anki profile's collection.media folder, with Anki closed. The \"Copy media into Anki\" button does this for you.",
  "help.anki_import": "In Anki: File > Import, pick the .tsv file.",
  "help.anki_header": "The separator, the HTML flag and the deck column are already declared in the file header — you should not have to change the import settings.",
  "js.copied": "Copied",
  "js.copy": "Copy",
  "js.copy_failed": "Copy failed"
```

Write the French values as the natural equivalents.

- [ ] **Step 7: Confirm the ESH prompt is gone**

Run:

```bash
grep -rn "SYSTEM_PROMPT\|ESH" app.py parse_cours.py project_store.py templates static
```

Expected: no match in `app.py`, `parse_cours.py`, `templates/`, `static/`. Matches are acceptable only in `project_store.py`'s docstring, where the legacy field is explained.

- [ ] **Step 8: Verify manually**

Run: `.venv/Scripts/python.exe app.py`
- `/help` renders in both languages, and the template block shows `{{IMG:n}}` **literally** — if it shows an empty gap, the `{% raw %}` wrapper is missing.
- "Copy" puts the whole template on the clipboard.
- Open an existing project created before this change: it still loads, and the export menu no longer offers "copy the system prompt".

- [ ] **Step 9: Run the suite and commit**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests`
Expected: `OK`

```bash
git add parse_cours.py app.py project_store.py templates locales
git commit -m "feat(help): replace the embedded ESH prompt with a how-to page

The system prompt was hardcoded French ESH instructions shipped inside the
parser and surfaced by a 'copy the system prompt' button — the single thing
that made the app unusable for anyone else. The workflow now relies on the
user's own Claude Skill, and /help explains how to write one, including the
{{IMG:n}} / {{TABLE:n}} convention the exporter depends on.

Projects carrying the old 'system' field still load; the field is ignored.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Fix the packaging manifests

**Files:**
- Modify: `flask-server.spec`
- Modify: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: every module created in Tasks 1–8.
- Produces: nothing.

**Context:** Both manifests are already stale on `main`, before this branch touched anything. `flask-server.spec` bundles only `templates` and `static` — nothing under `app_bundle/`, which `launcher.py` reads from `sys._MEIPASS/app_bundle` at first run. `release.yml` copies five of the ten application modules. This task brings both in line and adds the new files.

- [ ] **Step 1: Fix `flask-server.spec`**

Replace the `datas=[...]` line with:

```python
    datas=[
        ('app.py', 'app_bundle'),
        ('launcher.py', 'app_bundle'),
        ('parse_cours.py', 'app_bundle'),
        ('build_anki_csv.py', 'app_bundle'),
        ('docx_blocks.py', 'app_bundle'),
        ('media_store.py', 'app_bundle'),
        ('render.py', 'app_bundle'),
        ('paths.py', 'app_bundle'),
        ('project_store.py', 'app_bundle'),
        ('updater.py', 'app_bundle'),
        ('settings.py', 'app_bundle'),
        ('i18n.py', 'app_bundle'),
        ('version.json', 'app_bundle'),
        ('templates', 'app_bundle/templates'),
        ('static', 'app_bundle/static'),
        ('locales', 'app_bundle/locales'),
    ],
```

- [ ] **Step 2: Fix `.github/workflows/release.yml`**

Replace the two `cp` lines with:

```yaml
          cp app.py launcher.py parse_cours.py build_anki_csv.py \
             docx_blocks.py media_store.py render.py paths.py \
             project_store.py updater.py settings.py i18n.py release/app/
          cp -r templates static locales release/app/
```

- [ ] **Step 3: Prove the two lists agree with the repository**

Run:

```bash
ls *.py | grep -v new_version.py | grep -v decouper_cours.py | grep -v rassembler_cours.py
```

Compare against both manifests: every module listed must appear in each, and nothing may be missing. `new_version.py`, `decouper_cours.py` and `rassembler_cours.py` are developer scripts, not shipped.

- [ ] **Step 4: Commit**

```bash
git add flask-server.spec .github/workflows/release.yml
git commit -m "fix(build): ship every application module in both manifests

flask-server.spec bundled no Python module under app_bundle/, which
launcher.py reads at first run, and release.yml copied five of ten modules
into app.zip. Both were already stale before this branch; an update shipped
through that channel would have broken the install.

Refs #4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Final review and pull request

- [ ] **Step 1: Run the full suite one last time**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -v`
Expected: `OK`, with strictly more than the 38 baseline tests.

- [ ] **Step 2: Read the whole diff**

Run: `git diff main...HEAD`

Look for: leftover debugging code, `TODO` comments, stray `print`, committed `settings.json`, anything under `projects/` or `uploads/`, and any documentation sentence that now describes a state that no longer exists.

- [ ] **Step 3: Confirm no stale documentation**

Run:

```bash
grep -rn "Anki ESH\|\*ESH\*" README.md docs app.py parse_cours.py templates static
```

Expected: matches only in `docs/superpowers/specs/` and `docs/superpowers/plans/`, where they describe the state before this work — which is correct and must stay.

- [ ] **Step 4: Verify the spec's acceptance criteria**

Walk the checklist in [issue #4](https://github.com/leoprosy/Anki-Gen/issues/4) and tick each box only after observing it in the running app.

- [ ] **Step 5: Push and open the PR**

```bash
git push -u origin feat/open-source-readiness
gh pr create --title "feat(app): make Ankigen usable by the public" --body "$(cat <<'EOF'
## Summary

Closes #4.

Anki-Gen was built for one user: French-only UI, an `*ESH*` deck prefix hardcoded in four
places, and an ESH-specific system prompt shipped inside the parser. This makes it usable by
someone who is neither French-speaking nor an ESH student.

The app is renamed Ankigen on visible surfaces only — the Tauri identifier, the
`%APPDATA%/AnkiGen` data folder and `ANKI_ESH_SIDECAR` keep their names, because renaming
them would create a second install rather than updating the existing one. Translation is
server-side through Jinja, with the `js.` namespace serialised into `window.__I18N__` so
client and server share one mechanism. Settings live in `DATA_DIR/settings.json`, written
atomically and tolerant of corruption.

The embedded system prompt is gone, along with its "copy the system prompt" button; the
workflow now relies on the user's own Claude Skill, and the new `/help` page explains how to
write one — including the `{{IMG:n}}` / `{{TABLE:n}}` convention the exporter depends on.

**Out of scope, but fixed here:** both packaging manifests were already stale on `main`.
`flask-server.spec` bundled no Python module under `app_bundle/`, which `launcher.py` reads
at first run, and `release.yml` copied five of ten modules into `app.zip`. An update shipped
through that channel would have broken the install. Since the new files had to be added to
both anyway, they are brought fully in line.

Design: `docs/superpowers/specs/2026-09-13-ankigen-open-source-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Do not merge**

Leave the PR open for Leo's review. Never merge without an explicit go-ahead.
