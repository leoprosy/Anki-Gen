<img src="static/logo.svg" alt="" width="72" align="left" hspace="12">

# Ankigen

**Turn a `.docx` course into an Anki deck, one paragraph at a time.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/leoprosy/Anki-Gen)](https://github.com/leoprosy/Anki-Gen/releases/latest)
[![Windows installer](https://img.shields.io/badge/Windows-installer-0078D4)](https://github.com/leoprosy/Anki-Gen/releases/latest)

[**Download for Windows**](https://github.com/leoprosy/Anki-Gen/releases/latest) · [Contributing](CONTRIBUTING.md) · [Discussions](https://github.com/leoprosy/Anki-Gen/discussions) · [🇫🇷 Lire en français](README.fr.md)

![Ankigen: the source paragraph on the left, the generated cards on the right](docs/images/cards.png)

---

## Why

Making flashcards is the slowest part of studying, and pasting a whole chapter into a chatbot does not fix it: the model skims, the cards come out shallow, and every image and table in the document is lost on the way.

Ankigen keeps the document's structure instead of flattening it. It splits the course along its heading styles, hands you **one paragraph at a time** — with the images and tables that belong to it — and turns each heading path into an Anki deck path. You send that paragraph to Claude (or any assistant you like), paste the answer back, and Ankigen takes care of the plumbing: placeholders for media, HTML tables, the `#separator:tab` header, the media files copied into your Anki collection.

Course processing runs entirely on your machine. There is **no API key and no account** required — the cards are written in the chat you already pay for, and course contents stay on your computer except the paragraph you choose to paste.

Optional usage statistics are **off until you agree** in the first-launch prompt
or in Settings. You can decline and change your choice later. Agreeing shares
basic activity and export counts with the developer through PostHog.
Documents, filenames and card contents are never included.
See [privacy and owner dashboard setup](docs/analytics.md) for the exact fields
and metric definitions.

---

## Install

**Windows (recommended).** Download the latest `Ankigen_x.y.z_x64-setup.exe` from the
[releases page](https://github.com/leoprosy/Anki-Gen/releases/latest) and run it.
Python is not required — the installer ships everything.

**From source (Windows, macOS, Linux).** See [Run from source](#run-from-source) below.

---

## How it works

<img src="docs/images/work.png" alt="The work view: chunk list, source paragraph with its table, answer pane">

1. **Import** a `.docx` whose headings use real heading styles (`Heading 1`, `Heading 2`, … or their
   French equivalents). The split relies on those styles, not on the numbering you typed.
2. **Parse.** Ankigen cuts the course into chunks, one per section, extracts the images and tables,
   and saves a project locally. The deck path of each chunk mirrors the heading hierarchy
   (`Economics::Growth and Productivity::Sources of growth`).
3. **Generate.** Copy the current chunk, send it to Claude, and let it answer in TSV
   (`question <tab> answer`). Ankigen ships no system prompt — the **How to use** page in the app
   explains how to write your own [Claude Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)
   for card writing, and there is a template to copy.
4. **Check and save.** Paste the answer back, switch to the **Cards** tab to see the cards rendered,
   then *Save & next*.
5. **Export.** TSV alone, a ZIP with the images, or a direct copy of the media into your
   `collection.media`. Import the TSV in Anki with *File > Import* — separator, HTML and deck column
   are already declared in the file header.

Projects are persistent: close the app, come back, pick up where you left off.

---

## What it does with images and tables

**Images** are extracted to `media/<project>/` under a name derived from their SHA-1 and prefixed
with the project id (`ag_<project>_<sha1>.png`), because Anki's `collection.media` is a flat, global
namespace. A repeated image is written once. Formats Anki cannot display (emf, wmf, tiff, bmp…) are
converted to PNG, and anything wider than 1200 px is downscaled. The document's **alternative text**
travels with the paragraph; when it is missing, the interface highlights the image and lets you type
a description, and the prompt is rebuilt immediately.

**Tables** are rebuilt with their merges (`colspan` / `rowspan`), their nested tables and the images
inside their cells. They are sent to Claude as **markdown** (cheap in tokens) and re-injected into
the cards as **self-contained HTML** (inline CSS, horizontal scrolling on mobile).

**Placeholders.** The model never writes an `<img>` tag or a file name. It writes markers, which
Ankigen resolves at export time:

| Marker | Becomes |
|---|---|
| `{{IMG:1}}` | `<img src="ag_project_xxx.png">` |
| `{{TABLE:1}}` | the full table, as HTML |

Numbering is **local to the chunk**. A marker the model invented is dropped at export and reported;
buttons in the interface insert a forgotten one, and the **Cards** tab shows the final rendering
before you import anything.

---

## Run from source

```bash
git clone https://github.com/leoprosy/Anki-Gen.git
cd Anki-Gen
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux
.venv/Scripts/python.exe app.py
```

Then open <http://127.0.0.1:5000>. Change the port with `ANKI_GEN_PORT` (handy when the installed
app already holds 5000):

```bash
ANKI_GEN_PORT=5051 .venv/Scripts/python.exe app.py
```

To run the desktop shell in dev mode, start the Flask server first, then:

```bash
npm install
npm run tauri dev
```

---

## Build the Windows app

The desktop app is a [Tauri](https://tauri.app) shell around the Flask server, which is compiled
into a standalone "sidecar" binary with PyInstaller.

```powershell
# 1. Sidecar — the versioned flask-server.spec already lists the hidden imports
.venv\Scripts\pyinstaller.exe --noconfirm flask-server.spec

# 2. Hand it to Tauri under its target triple (-gnu if you use the GNU toolchain)
Copy-Item dist\flask-server.exe src-tauri\binaries\flask-server-x86_64-pc-windows-msvc.exe -Force

# 3. Bundle
npm run build
```

The installers land in `src-tauri/target/release/bundle/`. Pushing a `v*` tag runs the same steps in
CI ([`.github/workflows/release.yml`](.github/workflows/release.yml)) and attaches the `.exe` and
`.msi` to the release.

---

## Where the data lives

- **From source** (`python app.py`): in the project folder — `projects/`, `uploads/`, `media/`,
  `exports/`.
- **In the packaged app**: in `%APPDATA%\AnkiGen\` (`settings.json`, `projects/`, `uploads/`,
  `media/`, `exports/`). This matters — a PyInstaller *onefile* executable is unpacked into a
  temporary folder, and anything written there disappears when the app closes.

---

## Tests

```bash
.venv/Scripts/python.exe -m unittest discover -s tests
```

The `.docx` fixtures (images with and without alt text, a lone image in a paragraph, a repeated
image, horizontal and vertical merges, a nested table, an image inside a cell) are generated on the
fly by `tests/make_fixtures.py` — no binary file is versioned.

---

## Contributing

Issues labelled [`good first issue`](https://github.com/leoprosy/Anki-Gen/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
are the best place to start, and [CONTRIBUTING.md](CONTRIBUTING.md) has the setup, the conventions
and the layout of the code. Card-writing Skills, deck conventions and workflow ideas belong in
[Discussions](https://github.com/leoprosy/Anki-Gen/discussions).

## License

Ankigen is free software, released under the **GNU General Public License v3.0 or later**.
See [LICENSE](LICENSE). Copyright (C) 2026 leoprosy.
