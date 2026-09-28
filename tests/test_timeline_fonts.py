#!/usr/bin/env python3
"""
tests/test_timeline_fonts.py — Mesure du texte des frises (spec D2).

La mise en page ne connaît que des largeurs. Elles doivent être exactement celles
que Pillow dessine en moteur basique, rapides à obtenir, et ne jamais sous-estimer
un caractère absent de la police (il sera dessiné en .notdef, ou par une autre
police dans le navigateur).

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import ImageFont  # noqa: E402

import timeline_fonts as tf  # noqa: E402

SAMPLES = ["Traité Cobden-Chevalier", "Fin de la convertibilité du dollar en or",
           "v. 1750 av. J.-C.", "AVAWAToTa office «œuvre» <>&\"'", "XVIe siècle — années 1970"]


class TestFontFiles(unittest.TestCase):
    def test_files_and_licence_are_shipped(self):
        for name in ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "OFL.txt"):
            self.assertTrue((tf.FONT_DIR / name).is_file(), name)
        self.assertIn("SIL Open Font License", (tf.FONT_DIR / "OFL.txt").read_text(encoding="utf-8"))

    def test_basic_layout_is_forced(self):
        fonts = tf.FontSet()
        for weight in (400, 600):
            self.assertEqual(fonts.font(weight).layout_engine, ImageFont.Layout.BASIC)

    def test_weights_snap_to_the_two_files(self):
        self.assertEqual(tf.weight_key(400), 400)
        self.assertEqual(tf.weight_key(500), 600)
        self.assertEqual(tf.weight_key(700), 600)


class TestMeasure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = tf.FontSet()

    def test_table_equals_getlength_at_the_reference_size(self):
        for weight, name in ((400, "Inter-Regular.ttf"), (600, "Inter-SemiBold.ttf")):
            ref = ImageFont.truetype(str(tf.FONT_DIR / name), tf.REF_SIZE,
                                     layout_engine=ImageFont.Layout.BASIC)
            for text in SAMPLES:
                with self.subTest(weight=weight, text=text):
                    self.assertAlmostEqual(self.fonts.measure(text, tf.REF_SIZE, weight),
                                           ref.getlength(text), places=6)

    def test_linear_in_size(self):
        width = self.fonts.measure(SAMPLES[0], 13, 400)
        self.assertAlmostEqual(self.fonts.measure(SAMPLES[0], 26, 400), 2 * width, places=9)
        self.assertGreater(self.fonts.measure(SAMPLES[0], 13, 600), width)

    def test_advances_add_up_to_the_measure(self):
        advances = self.fonts.advances(SAMPLES[1], 12, 400)
        self.assertEqual(len(advances), len(SAMPLES[1]))
        self.assertAlmostEqual(sum(advances), self.fonts.measure(SAMPLES[1], 12, 400), places=9)

    def test_missing_glyph_counts_one_em(self):
        self.assertEqual(self.fonts.measure("漢", 12, 400), 12.0)
        self.assertEqual(self.fonts.measure("a漢", 10, 400), self.fonts.measure("a", 10, 400) + 10.0)

    def test_empty_text(self):
        self.assertEqual(self.fonts.measure("", 12, 400), 0.0)

    def test_fast_enough_for_the_layout(self):
        start = time.perf_counter()
        for i in range(1200):
            self.fonts.measure(f"{SAMPLES[i % len(SAMPLES)]} {i}", 12, 400)
        self.assertLess(time.perf_counter() - start, 0.1)


class TestCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = tf.FontSet()

    def test_latin_and_french_typography(self):
        for ch in "aéèêàùçœŒÉ«»—–’…€°":
            with self.subTest(ch=ch):
                self.assertTrue(self.fonts.covers(ch))

    def test_greek_and_cyrillic(self):
        for ch in "αΩжЯ":
            self.assertTrue(self.fonts.covers(ch))

    def test_outside_the_font(self):
        for ch in "漢字😀":
            with self.subTest(ch=ch):
                self.assertFalse(self.fonts.covers(ch))

    def test_unsupported_characters_are_listed_once_in_order(self):
        self.assertEqual(self.fonts.unsupported("Traité 漢 字 漢"), ["漢", "字"])
        self.assertEqual(self.fonts.unsupported("Traité de Rome"), [])

    def test_cmap_parser_on_a_real_table(self):
        data = (tf.FONT_DIR / "Inter-Regular.ttf").read_bytes()
        ranges = tf.read_cmap(data)
        self.assertTrue(ranges)
        self.assertEqual(ranges, sorted(ranges))
        self.assertTrue(all(a <= b for a, b in ranges))
        self.assertTrue(any(a <= ord("A") <= b for a, b in ranges))

    def test_not_a_font(self):
        with self.assertRaises(ValueError):
            tf.read_cmap(b"not a font at all")


class TestEmbedding(unittest.TestCase):
    def test_font_bytes_for_svg_embedding(self):
        data = tf.FontSet().font_bytes(600)
        self.assertEqual(data, (tf.FONT_DIR / "Inter-SemiBold.ttf").read_bytes())


if __name__ == "__main__":
    unittest.main()
