# Contributing to Ankigen

Thanks for looking. Ankigen is a small, dependency-light app maintained in spare time between
exams — clear, self-contained contributions are the ones that get merged fastest.

*Le projet est bilingue : ouvrez vos issues et vos PR en anglais ou en français, comme vous préférez.
La seule règle est que les **messages de commit** soient en anglais.*

---

## Ways to help

| You want to… | Go to |
|---|---|
| Fix or build something | the [issues](https://github.com/leoprosy/Anki-Gen/issues), starting with [`good first issue`](https://github.com/leoprosy/Anki-Gen/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) |
| Report a bug | [open an issue](https://github.com/leoprosy/Anki-Gen/issues/new/choose) with the `.docx` structure that triggers it |
| Share a card-writing Claude Skill, a deck convention, a workflow | [Discussions](https://github.com/leoprosy/Anki-Gen/discussions) |
| Translate the interface | `locales/` — see [Adding a language](#adding-a-language) |

Before starting anything larger than a bug fix, comment on the issue (or open one). It costs a
minute and avoids two people writing the same patch.

---

## Setup

Python 3.11+ and, only if you touch the desktop shell, Node 18+ and the
[Tauri prerequisites](https://tauri.app/start/prerequisites/).

```bash
git clone https://github.com/leoprosy/Anki-Gen.git
cd Anki-Gen
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux
.venv/Scripts/python.exe app.py
```

The app is then on <http://127.0.0.1:5000>. `ANKI_GEN_PORT=5051` moves it elsewhere when the
installed app already holds port 5000.

The parser, the stores and the exporters are plain Python and need neither Tauri nor an installed
Anki to work on.

---

## Tests

```bash
.venv/Scripts/python.exe -m unittest discover -s tests
```

- **`unittest` only.** `pytest` is deliberately not a dependency; please do not introduce it.
- The suite is green on `main` and must stay green. The count only ever goes up.
- `.docx` fixtures are generated on the fly by `tests/make_fixtures.py` — never commit binary
  fixtures.
- Anything touching parsing, export or placeholder resolution needs a test. UI-only changes do not.

---

## Conventions

**Commits.** [Conventional Commits](https://www.conventionalcommits.org/), in English, imperative:

```
feat(export): copy media into the Anki collection
fix(parser): keep the alt text of images inside table cells
docs(readme): add the Windows install section
```

**Dependencies.** The runtime set is small on purpose — Flask, Waitress, python-docx, lxml, Pillow.
Adding one is a discussion, not a detail of a PR. The standard library is preferred everywhere else.

**User-facing strings go through i18n.** No literal text in templates, `app.py` or `static/app.js`:
add the key to **both** `locales/en.json` and `locales/fr.json` and use `t("namespace.key")` in
Jinja, `tr(...)` in Python, `window.T("js.key")` in JavaScript. `tests/test_i18n.py` checks that the
two catalogs have the same keys.

**Code style.** Follow the file you are editing: 4 spaces, snake_case, a module docstring that says
*why* the module exists, comments that explain decisions rather than restate the code. Existing
comments and docstrings are in French — keep writing them in the language of the file you are in.

**Scope.** One subject per PR. A refactor and a feature in the same diff is two PRs.

---

## Project layout

| Path | What it holds |
|---|---|
| `app.py` | Flask routes and the glue between every module |
| `launcher.py` | packaged entry point; resolves `APP_DIR` / `DATA_DIR` under `%APPDATA%` |
| `paths.py` | where projects, uploads, media and exports live |
| `parse_cours.py` | `.docx` → chunks, one per section |
| `docx_blocks.py` | low-level block walking: headings, images, tables, alt text |
| `media_store.py` | image extraction, conversion, deduplication by SHA-1 |
| `render.py` | prompt text, placeholder resolution, HTML for tables |
| `build_anki_csv.py` | TSV/CSV assembly with the Anki header |
| `project_store.py` | the project JSON format and its migrations |
| `settings.py`, `i18n.py` | preferences and translations, both Flask-free |
| `updater.py` | GitHub Releases check and the atomic swap of `app/` |
| `templates/`, `static/` | Jinja templates, vanilla JS, native CSS — no framework, no build step |
| `locales/` | flat JSON translation catalogs |
| `skill_templates/` | the Claude Skill template offered on the *How to use* page |
| `src-tauri/` | the Rust/Tauri desktop shell and its sidecar configuration |

---

## Adding a language

1. Copy `locales/en.json` to `locales/<code>.json` and translate the values, keys untouched.
2. Add the code to `LANGUAGES` and a label to `LANGUAGE_LABELS` in `i18n.py`.
3. Copy `skill_templates/en.md` to `skill_templates/<code>.md` if you can translate it too.
4. Run the tests: `test_i18n.py` verifies that no key is missing on either side.

---

## Pull requests

- Branch off `main`, name it `feat/…`, `fix/…`, `docs/…` or `chore/…`.
- Say what the change does and, for anything user-visible, add a screenshot.
- Keep the diff to the subject at hand; note any deliberate follow-up in the description.
- Tests green, and new behaviour covered.

By contributing, you agree that your work is licensed under the
[GNU GPL v3.0 or later](LICENSE), like the rest of Ankigen.
