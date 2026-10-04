#!/usr/bin/env python3
"""
timeline_gallery.py — Galerie de rendus des fixtures de frise, pour la revue visuelle.

Chaque fixture de tests/fixtures_timeline/ est rendue dans chaque thème, en SVG
(police incorporée : il s'ouvre tel quel dans un navigateur) et en PNG, dans
exports/gallery/. Une planche de vignettes (sheet-<thème>.png) les réunit pour
les PR. Les valeurs par défaut du §7.2 se règlent en regardant ces images.

    .venv/Scripts/python.exe scripts/timeline_gallery.py [--theme light] [--only mondialisation]
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

import timeline_schema  # noqa: E402
from timeline_layout import LayoutOptions  # noqa: E402
from timeline_render_raster import render_image  # noqa: E402
from timeline_render_svg import render  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures_timeline"
OUT = ROOT / "exports" / "gallery"
THEMES = ("light", "dark", "print")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--theme", choices=THEMES, action="append")
    parser.add_argument("--only", action="append", help="nom de fixture (sans .json)")
    parser.add_argument("--density", default="compact", choices=("comfortable", "compact"))
    parser.add_argument("--width", type=int, help="largeur fixe en px (sinon automatique)")
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    themes = args.theme or list(THEMES)
    problems = 0
    for theme in themes:
        thumbs = []
        for path in sorted(FIXTURES.glob("*.json")):
            if args.only and path.stem not in args.only:
                continue
            report = timeline_schema.validate(json.loads(path.read_text(encoding="utf-8")))
            options = LayoutOptions(theme=theme, density=args.density,
                                    width_mode="fixed" if args.width else "auto", width_px=args.width or 1200)
            start = time.perf_counter()
            result = render(report["normalized"], options, embed_font=True)
            image = render_image(result.layout, scale=1)
            elapsed = (time.perf_counter() - start) * 1000
            stem = f"{path.stem}-{theme}"
            (OUT / f"{stem}.svg").write_text(result.svg, encoding="utf-8")
            image.save(OUT / f"{stem}.png", optimize=True)
            codes = [w["code"] for w in result.warnings]
            if "layout_violation" in codes:
                problems += 1
            print(f"[gallery] {stem:34} {result.width:>5}×{result.height:<5} {elapsed:6.0f} ms  {codes}")
            thumbs.append((path.stem, image))
        if thumbs:
            _sheet(thumbs, OUT / f"sheet-{theme}.png", theme)
    print(f"[gallery] {OUT}")
    return 1 if problems else 0


def _sheet(thumbs, target, theme):
    """Planche : chaque rendu réduit à 960 px de large au plus, en colonne."""
    width = 960
    tiles = []
    for name, image in thumbs:
        ratio = min(1.0, width / image.width)
        tiles.append((name, image.convert("RGB").resize((max(1, int(image.width * ratio)),
                                                          max(1, int(image.height * ratio))), Image.LANCZOS)))
    height = sum(tile.height + 28 for _, tile in tiles) + 8
    background = (28, 28, 30) if theme == "dark" else (245, 245, 247)
    sheet = Image.new("RGB", (width + 16, height), background)
    draw = ImageDraw.Draw(sheet)
    y = 8
    for name, tile in tiles:
        draw.text((8, y + 4), name, fill=(134, 134, 139))
        sheet.paste(tile, (8, y + 20))
        y += tile.height + 28
    sheet.save(target, optimize=True)


if __name__ == "__main__":
    sys.exit(main())
