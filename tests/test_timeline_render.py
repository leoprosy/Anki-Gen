#!/usr/bin/env python3
"""
tests/test_timeline_render.py — Rendu des frises : SVG autonome (et raster minimal).

Le SVG sert d'aperçu ET d'export : il doit être bien formé, autonome (aucune
variable CSS de la page, couleurs en #RRGGBB), échapper tout texte venu du
document, et porter de quoi relier chaque dessin à son élément (data-ref) et le
lire sans le voir (<title>, <desc>).

Le raster complet (JPEG, WebP, PDF, plafond de surface) arrive en phase 5 ; ici,
seulement ce dont la galerie de revue a besoin.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import io
import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import timeline_render_svg as rs  # noqa: E402
import timeline_schema as ts  # noqa: E402
from timeline_layout import LayoutOptions, Rect, Text  # noqa: E402
from timeline_render_raster import render_png  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures_timeline"
SVG = "{http://www.w3.org/2000/svg}"


def load(name):
    return ts.validate(json.loads((FIXTURES / name).read_text(encoding="utf-8")))["normalized"]


class TestSvg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {path.name: load(path.name) for path in sorted(FIXTURES.glob("*.json"))}
        cls.rendered = {name: rs.render(doc) for name, doc in cls.docs.items()}

    def test_well_formed_with_title_and_desc(self):
        for name, result in self.rendered.items():
            with self.subTest(fixture=name):
                root = ET.fromstring(result.svg)
                self.assertEqual(root.tag, f"{SVG}svg")
                self.assertEqual(root.get("role"), "img")
                self.assertEqual(root.find(f"{SVG}title").text, self.docs[name]["title"])
                self.assertEqual(root.get("viewBox"), f"0 0 {result.width} {result.height}")

    def test_desc_lists_every_element(self):
        doc = self.docs["mondialisation.json"]
        desc = ET.fromstring(self.rendered["mondialisation.json"].svg).find(f"{SVG}desc").text
        for kind in ("eras", "periods", "events"):
            for element in doc[kind]:
                self.assertIn(element["label"], desc)
        self.assertIn("23 janvier 1860 — Traité Cobden-Chevalier (Commerce)", desc)

    def test_every_element_has_a_data_ref(self):
        for name, result in self.rendered.items():
            with self.subTest(fixture=name):
                root = ET.fromstring(result.svg)
                refs = set()
                for group in root.iter(f"{SVG}g"):
                    refs.update((group.get("data-ref") or "").split("+"))
                ids = {e["id"] for k in ("eras", "periods", "events") for e in self.docs[name][k]}
                self.assertLessEqual(ids, refs)

    def test_text_is_escaped(self):
        svg = self.rendered["long_labels.json"].svg
        root = ET.fromstring(svg)         # une balise non échappée casserait l'analyse
        texts = " ".join("".join(t.itertext()) for t in root.iter(f"{SVG}text"))
        self.assertIn("<b>test</b>", texts)
        self.assertIn('"guillemets"', texts)
        self.assertNotIn("<b>test", svg)

    def test_self_contained_colours(self):
        for name, result in self.rendered.items():
            with self.subTest(fixture=name):
                self.assertNotIn("var(--", result.svg)
                for value in re.findall(r'(?:fill|stroke|stop-color)="([^"]+)"', result.svg):
                    self.assertRegex(value, r"^(#[0-9A-Fa-f]{6}|none|url\(#[A-Za-z0-9_-]+\))$", name)

    def test_font_settings_match_the_measure(self):
        svg = self.rendered["mondialisation.json"].svg
        self.assertIn("font-kerning:none", svg)
        self.assertIn("font-variant-ligatures:none", svg)
        self.assertIn("'Ankigen Inter'", svg)
        self.assertNotIn("@font-face", svg)

    def test_font_embedding(self):
        result = rs.render(self.docs["single_event.json"], embed_font=True)
        self.assertEqual(result.svg.count("@font-face"), 2)      # titre en 600, libellé en 400 et 600
        self.assertIn("data:font/ttf;base64,", result.svg)
        ET.fromstring(result.svg)

    def test_malicious_colour_never_reaches_the_svg(self):
        layout = rs.render(self.docs["single_event.json"]).layout
        evil = Rect(x=0, y=0, w=10, h=10, fill='red"/><script>alert(1)</script>', role="lane-bg")
        svg = rs.render_svg(type(layout)(width=layout.width, height=layout.height, primitives=(evil,),
                                         theme=layout.theme))
        self.assertNotIn("<script", svg)
        ET.fromstring(svg)

    def test_id_prefix_is_sanitised(self):
        result = rs.render(self.docs["single_event.json"], id_prefix='x" onload="alert(1)')
        self.assertNotIn('onload="', result.svg)      # les lettres restent, sans créer d'attribut
        self.assertIsNone(ET.fromstring(result.svg).get("onload"))
        self.assertIn('id="xonloadalert1-title"', result.svg)

    def test_text_anchors_are_those_of_the_layout(self):
        result = self.rendered["mondialisation.json"]
        texts = [p for p in result.layout.primitives if isinstance(p, Text)]
        anchors = [t.get("text-anchor") for t in ET.fromstring(result.svg).iter(f"{SVG}text")]
        self.assertEqual(sorted(anchors), sorted(t.anchor for t in texts))

    def test_warnings(self):
        doc = dict(self.docs["single_event.json"])
        doc["events"] = [dict(doc["events"][0], label="Prise de la Bastille 漢字")]
        codes = [w["code"] for w in rs.render(doc).warnings]
        self.assertIn("label_unsupported_chars", codes)
        self.assertNotIn("layout_violation", codes)

    def test_dark_theme(self):
        result = rs.render(self.docs["mondialisation.json"], LayoutOptions(theme="dark"))
        self.assertIn('fill="#1C1C1E"', result.svg)


class TestRasterSmoke(unittest.TestCase):
    def test_png_matches_the_layout_size(self):
        result = rs.render(load("present.json"))
        image = Image.open(io.BytesIO(render_png(result.layout)))
        self.assertEqual(image.size, (round(result.width), round(result.height)))
        doubled = Image.open(io.BytesIO(render_png(result.layout, scale=2, supersample=1)))
        self.assertEqual(doubled.size, (round(result.width * 2), round(result.height * 2)))


if __name__ == "__main__":
    unittest.main()
