#!/usr/bin/env python3
"""
tests/test_timeline_render.py — Rendu des frises : SVG autonome et raster.

Le SVG sert d'aperçu ET d'export : il doit être bien formé, autonome (aucune
variable CSS de la page, couleurs en #RRGGBB), échapper tout texte venu du
document, et porter de quoi relier chaque dessin à son élément (data-ref) et le
lire sans le voir (<title>, <desc>).

Le raster sort les mêmes dessins en PNG (opaque ou transparent), JPEG, WebP et
PDF, dans la limite de 60 Mpx et des formats, et le texte ne déborde jamais de la
largeur mesurée.

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
import timeline_render_raster as raster  # noqa: E402
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

    def test_a_violation_triggers_the_next_fallback(self):
        from unittest import mock
        import timeline_layout
        from timeline_layout import Violation
        real = timeline_layout.check_layout
        calls = []

        def flaky(layout):
            calls.append(layout)
            return [Violation("I1", "simulée")] if len(calls) == 1 else real(layout)

        with mock.patch.object(rs, "check_layout", side_effect=flaky):
            result = rs.render(self.docs["mondialisation.json"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("layout_violation", [w["code"] for w in result.warnings])

    def test_a_persistent_violation_is_reported(self):
        from unittest import mock
        from timeline_layout import Violation
        with mock.patch.object(rs, "check_layout", return_value=[Violation("I1", "simulée")]),                 self.assertLogs("timeline_render_svg", level="ERROR"):
            result = rs.render(self.docs["single_event.json"])
        warning = [w for w in result.warnings if w["code"] == "layout_violation"]
        self.assertEqual(warning, [{"code": "layout_violation", "params": {"count": 1}}])

    def test_dark_theme(self):
        result = rs.render(self.docs["mondialisation.json"], LayoutOptions(theme="dark"))
        self.assertIn('fill="#1C1C1E"', result.svg)


class TestRaster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = rs.render(load("mondialisation.json")).layout
        cls.small = rs.render(load("present.json")).layout

    def open(self, exported):
        return Image.open(io.BytesIO(exported.data))

    def test_png_matches_the_layout_size(self):
        image = Image.open(io.BytesIO(render_png(self.small)))
        self.assertEqual(image.size, (round(self.small.width), round(self.small.height)))
        doubled = Image.open(io.BytesIO(render_png(self.small, scale=2, supersample=1)))
        self.assertEqual(doubled.size, (round(self.small.width * 2), round(self.small.height * 2)))

    def test_png_scales_and_stays_opaque(self):
        exported = raster.export(self.small, "png", scale=3)
        image = self.open(exported)
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.mode, "RGB")           # fond opaque : tampon RGB (E4)
        self.assertEqual(image.size, (round(self.small.width * 3), round(self.small.height * 3)))
        self.assertEqual((exported.width, exported.height), image.size)
        self.assertEqual(image.getpixel((1, 1)), (255, 255, 255))

    def test_transparent_png(self):
        image = self.open(raster.export(self.small, "png", scale=1, transparent=True))
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.getpixel((1, 1))[3], 0)
        self.assertEqual(image.getchannel("A").getextrema()[1], 255)

    def test_jpeg_has_no_alpha_even_when_asked(self):
        exported = raster.export(self.small, "jpeg", scale=1, transparent=True, quality=80)
        self.assertTrue(exported.data.startswith(b"\xff\xd8"))
        image = self.open(exported)
        self.assertEqual((image.format, image.mode), ("JPEG", "RGB"))
        self.assertEqual(exported.extension, "jpg")

    def test_webp_lossy_and_lossless(self):
        # E3 : l'encodeur WebP est garanti par le runtime (sonde) : ce test n'est jamais sauté.
        for lossless in (False, True):
            image = self.open(raster.export(self.small, "webp", scale=1, lossless=lossless))
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (round(self.small.width), round(self.small.height)))

    def test_pdf_pages_and_metadata(self):
        exported = raster.export(self.layout, "pdf", page="a4", orientation="landscape", title="Mondialisation")
        self.assertTrue(exported.data.startswith(b"%PDF"))
        box = [float(v) for v in re.search(rb"/MediaBox \[([^\]]+)\]", exported.data).group(1).split()]
        self.assertEqual((round(box[2]), round(box[3])), (842, 595))       # A4 paysage, en points
        self.assertIn(b"A\x00n\x00k\x00i\x00g\x00e\x00n", exported.data)   # auteur, en UTF-16
        self.assertEqual(exported.info["dpi"], 300)
        fit = raster.export(self.small, "pdf", page="fit", margin_mm=0)
        box = [float(v) for v in re.search(rb"/MediaBox \[([^\]]+)\]", fit.data).group(1).split()]
        self.assertAlmostEqual(box[2], self.small.width * 72 / 96, delta=1)  # taille naturelle

    def test_small_print_is_announced(self):
        plan = raster.plan_pdf(self.layout.width, self.layout.height, page="a4", orientation="portrait")
        self.assertLess(plan.fit, raster.SMALL_PRINT)
        self.assertEqual(plan.warnings[0]["code"], "pdf_small_print")
        self.assertFalse(raster.plan_pdf(self.small.width, self.small.height, page="a3").warnings)

    def test_huge_fit_page_lowers_the_resolution(self):
        plan = raster.plan_pdf(12000, 3000, page="fit")
        self.assertLessEqual(plan.page_px[0] * plan.page_px[1], raster.MAX_PIXELS * 1.001)
        self.assertLess(plan.dpi, raster.PDF_DPI)
        self.assertEqual(plan.warnings[0]["code"], "pdf_dpi_reduced")

    def test_surface_cap_reduces_supersampling_then_scale(self):
        plan = raster.plan_raster(4000, 2000, scale=2, supersample=2)      # 32 Mpx, ×4 suréchantillonné
        self.assertEqual((plan.scale, plan.supersample, plan.warnings), (2, 1, ()))
        plan = raster.plan_raster(12000, 2000, scale=4)
        self.assertLessEqual(plan.width * plan.height, raster.MAX_PIXELS * 1.001)
        self.assertEqual(plan.warnings[0]["code"], "scale_reduced_pixels")
        self.assertEqual(plan.warnings[0]["params"]["requested"], 400)

    def test_format_side_limits(self):
        plan = raster.plan_raster(12000, 700, scale=2, fmt="webp")
        self.assertEqual(max(plan.width, plan.height), raster.MAX_SIDE["webp"])
        self.assertEqual(plan.warnings[0]["code"], "scale_reduced_side")
        self.assertEqual(raster.plan_raster(12000, 700, scale=2, fmt="png").warnings, ())

    def test_estimate_announces_the_exported_size(self):
        for fmt in ("png", "jpeg", "webp", "pdf"):
            estimate = raster.estimate(self.small, fmt, scale=2)
            exported = raster.export(self.small, fmt, scale=2)
            self.assertEqual((estimate["width"], estimate["height"]), (exported.width, exported.height), fmt)
            self.assertGreater(estimate["bytes"], 0)

    def test_glyphs_stay_inside_the_measured_box(self):
        # D4 : dessinés glyphe par glyphe, les caractères ne débordent pas de la largeur mesurée.
        from timeline_fonts import default_fonts
        from timeline_layout import Layout
        fonts = default_fonts()
        line = "Traité Cobden-Chevalier — Mmmm WWW"
        text = Text(x=20, y=40, lines=(line,), size=13, weight=400, fill="#000000", anchor="start",
                    line_height=16, widths=(fonts.measure(line, 13, 400),))
        layout = Layout(width=400, height=60, primitives=(text,), theme={"bg": "#FFFFFF", "ink": "#000000"})
        for scale in (1, 2, 3):
            image = raster.render_image(layout, scale=scale, supersample=1, fonts=fonts).convert("L")
            inked = Image.eval(image, lambda v: 255 if v < 250 else 0).getbbox()
            x0, _, x1, _ = text.bbox
            self.assertGreaterEqual(inked[0], (x0 - 1) * scale, scale)
            self.assertLessEqual(inked[2], (x1 + 1) * scale, scale)

    def test_every_warning_has_a_message(self):
        import i18n
        for lang in i18n.LANGUAGES:
            catalog = i18n.load_catalog(lang)
            for code in raster.WARNING_CODES:
                self.assertTrue(f"timeline.export.{code}" in catalog, f"{lang}: {code}")

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            raster.export(self.small, "gif")


if __name__ == "__main__":
    unittest.main()
