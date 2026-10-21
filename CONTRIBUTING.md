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
node --test "tests/*.js"
```

- **`unittest` only.** `pytest` is deliberately not a dependency; please do not introduce it.
- The JavaScript tests use Node's built-in runner (Node 22+): no `npm install`, no test framework.
  They cover the pure logic of the pages (`static/timeline-core.js`, the updater), not the DOM.
- The suite is green on `main` and must stay green. The count only ever goes up.
- `.docx` fixtures are generated on the fly by `tests/make_fixtures.py` — never commit binary
  fixtures. Timeline fixtures are small JSON documents in `tests/fixtures_timeline/`, one per
  layout situation or per validation error.
- Anything touching parsing, export or placeholder resolution needs a test. UI-only changes do not.
- A change to the timeline layout or renderers is reviewed by eye too: run
  `scripts/timeline_gallery.py` and look at the PNGs it writes to `exports/gallery/`.

---

## Conventions

**Commits.** [Conventional Commits](https://www.conventionalcommits.org/), in English, imperative:

```
feat(export): copy media into the Anki collection
fix(parser): keep the alt text of images inside table cells
docs(readme): add the Windows install section
```

**Dependencies.** The runtime set is small on purpose — Flask, Waitress, python-docx, lxml, Pillow,
and llama-cpp-python (with numpy) for the local model. Its CPU wheel comes from the extra index
named at the top of `requirements.txt`, because PyPI has no Windows wheel.
Adding one is a discussion, not a detail of a PR. The standard library is preferred everywhere else.
A new runtime dependency also means a new installer for every user, because updates only replace
the app's code: run `python scripts/runtime_contract.py --bump` in the same PR, or the tests fail.

**Packaging lists nothing by hand.** `app.zip` and the executable's bundle are built by
`scripts/build_app_payload.py`, which follows the imports from `app.py` and `launcher.py`. A new
module is shipped as soon as something imports it; a new *data folder* goes in `DATA_DIRS` there.
When a feature needs a runtime capability that an import alone does not prove (a Pillow codec,
FreeType…), add a probe to `runtime_probe.py`: CI runs it on the new executable and on the one
users already have.

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
| `paths.py` | where projects, uploads, media, exports and timelines live |
| `parse_cours.py` | `.docx` → chunks, one per section |
| `docx_blocks.py` | low-level block walking: headings, images, tables, alt text |
| `media_store.py` | image extraction, conversion, deduplication by SHA-1 |
| `render.py` | prompt text, placeholder resolution, HTML for tables |
| `build_anki_csv.py` | TSV/CSV assembly with the Anki header |
| `project_store.py` | the project JSON format and its migrations |
| `timeline_dates.py`, `timeline_schema.py` | timeline dates (astronomical years, precisions, fr/en formatting) and the `ankigen.timeline/1` contract with its error report |
| `timeline_store.py` | timeline JSON files, their source snapshot and extraction state |
| `timeline_prompt.py`, `timeline_extract.py` | scopes (paragraph, chapter, course), extraction and correction prompts, pasted answers |
| `local_llm.py` | the embedded model: verified on-demand download into `models/`, schema-constrained generation, unload when idle |
| `timeline_quotes.py`, `timeline_merge.py` | quotations checked against the course; per-paragraph answers merged into one timeline |
| `timeline_fonts.py`, `timeline_layout.py` | text measurement with the embedded Inter, and the collision-free layout as a display list |
| `timeline_render_svg.py`, `timeline_render_raster.py` | the two renderers of that display list: SVG, and PNG/JPEG/WebP/PDF with Pillow |
| `timeline_cards.py` | Anki cards and their pictures generated from a timeline |
| `prompt_templates/` | the timeline prompts, as named blocks per language; the timeline Skill is built from the same blocks |
| `settings.py`, `i18n.py` | preferences and translations, both Flask-free |
| `telemetry.py`, `analytics_config.py` | optional usage events, persistent outbox and public build configuration |
| `scripts/setup_analytics_dashboard.py`, `scripts/release_downloads.py` | owner tooling; never bundled in the app |
| `updater.py` | GitHub Releases check and the atomic swap of `app/` |
| `runtime_probe.py`, `runtime.json` | what the code needs from the executable, and which runtime the executable is |
| `scripts/` | payload build, runtime contract and compatibility check, used by the spec and CI |
| `scripts/timeline_gallery.py` | renders every timeline fixture, in every theme, for visual review |
| `templates/`, `static/` | Jinja templates, vanilla JS, native CSS — no framework, no build step |
| `static/fonts/`, `static/schemas/` | Inter (OFL), used by every timeline renderer; the timeline JSON Schema, generated by `python timeline_schema.py --write-schema` |
| `locales/` | flat JSON translation catalogs |
| `skill_templates/` | the Claude Skill template offered on the *How to use* page |
| `src-tauri/` | the Rust/Tauri desktop shell and its sidecar configuration |

---

## Analytics

Analytics changes must preserve explicit consent, the payload allowlist and
failure isolation. See [analytics setup and metric definitions](docs/analytics.md).
The analytics tests use a substituted transport; never use production tokens in
tests. The public token is supplied through Actions variables during builds.

## Adding a language

1. Copy `locales/en.json` to `locales/<code>.json` and translate the values, keys untouched.
2. Add the code to `LANGUAGES` and a label to `LANGUAGE_LABELS` in `i18n.py`.
3. Copy `skill_templates/en.md` to `skill_templates/<code>.md` if you can translate it too.
4. Likewise, `prompt_templates/en/` can be copied to `prompt_templates/<code>/`: translate the
   text, keep the `<!-- @block -->` markers and the `{{placeholders}}`. Until then, timelines in that
   language get the English prompt.
5. Run the tests: `test_i18n.py` verifies that no key is missing on either side.

---

## Pull requests

- Branch off `main`, name it `feat/…`, `fix/…`, `docs/…` or `chore/…`.
- Say what the change does and, for anything user-visible, add a screenshot.
- Keep the diff to the subject at hand; note any deliberate follow-up in the description.
- Tests green, and new behaviour covered.

By contributing, you agree that your work is licensed under the
[GNU GPL v3.0 or later](LICENSE), like the rest of Ankigen.
