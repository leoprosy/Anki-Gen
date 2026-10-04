# Motion Design Studio

A Claude Code plugin that designs, builds, critiques and exports motion designs in code: launch videos, UI animations, showreels, loops, SaaS teasers, HTML-to-MP4.

It renders deterministically: the composition exposes `window.seek(t)`, and every frame is captured through Chromium and encoded with FFmpeg.

## Install

```text
/plugin marketplace add leoprosy/Anki-Gen
/plugin install motion-design-studio@ankigen-plugins
```

The skill activates on its own when you ask for a motion design, or you can call it with `/motion-design-studio`.

## Contents

```text
skills/motion-design-studio/
├── SKILL.md              the full workflow (French)
└── templates/
    ├── CLAUDE.md         project invariants
    ├── index.html        seek(t) composition + preview player
    └── render.py         probes, contact sheet, draft, master, motion blur, loop check
```

## Requirements (Route A)

- Python 3 with `playwright`, `pillow` and `numpy`, plus `python -m playwright install chromium`
- FFmpeg on `PATH`
- Set `CHROMIUM_PATH` to use an existing Chromium build instead of the one Playwright downloads.

Routes B (HyperFrames) and C (Remotion) install their own tooling when the skill picks them.
