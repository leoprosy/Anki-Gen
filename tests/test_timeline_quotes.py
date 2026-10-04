#!/usr/bin/env python3
"""
tests/test_timeline_quotes.py — Vérification des citations source (§6.5).

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import random
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402
import timeline_quotes as tq  # noqa: E402

SOURCE = """## CH1 › B) Une première mondialisation

Le traité **Cobden-Chevalier** de 1860 ouvre l’ère du libre-échange en Europe : c’est « le modèle de la clause de la nation la plus favorisée ».
Après 1879, le tarif Bismarck marque le retour du protectionnisme en Allemagne, puis le tarif Méline en France (1892).

| Année | Évènement |
|---|---|
| 1869 | Ouverture du canal de Suez |
| 1914 | Ouverture du canal de Panama |

> Bairoch étudie le TCAM entre 1815 et 1914, au niveau mondial.
"""


class TestNormalize(unittest.TestCase):
    def test_typography_is_unified(self):
        self.assertEqual(tq.normalize("L’ère du « libre–échange »"), "l'ère du libre-échange")
        self.assertEqual(tq.normalize("L'ère du \"libre-échange\""), "l'ère du libre-échange")
        self.assertEqual(tq.normalize("  Plusieurs\n\n  espaces\t"), "plusieurs espaces")

    def test_markdown_is_removed(self):
        self.assertEqual(tq.normalize("## Titre\n**gras** et `code`\n> citation"), "titre gras et code citation")
        self.assertEqual(tq.normalize("| 1869 | Suez |\n|---|---|\n| 1914 | Panama |"), "1869 suez 1914 panama")

    def test_nfkc(self):
        self.assertEqual(tq.normalize("ﬁn…"), "fin...")


class TestFind(unittest.TestCase):
    def setUp(self):
        self.index = tq.SourceIndex(SOURCE)

    def test_exact_match_despite_typography(self):
        self.assertEqual(self.index.find("Le traité Cobden-Chevalier de 1860 ouvre l'ère du libre-échange"), "verified")
        self.assertEqual(self.index.find("c'est \"le modèle de la clause de la nation la plus favorisée\""), "verified")
        self.assertEqual(self.index.find("1869 | Ouverture du canal de Suez"), "verified")
        self.assertEqual(self.index.find("Bairoch étudie le TCAM entre 1815 et 1914"), "verified")

    def test_fuzzy_match_tolerates_a_small_slip(self):
        # Un mot changé et un accord oublié : la citation n'est pas littérale.
        quote = "Après 1879, le tarif Bismarck marque le retour au protectionnisme en Allemagne"
        self.assertEqual(self.index.find(quote), "fuzzy")
        self.assertGreaterEqual(self.index.best_ratio(tq.normalize(quote)), tq.FUZZY_RATIO)

    def test_elided_quote_is_found_piece_by_piece(self):
        quote = "Le traité Cobden-Chevalier de 1860 […] le modèle de la clause de la nation"
        self.assertEqual(self.index.find(quote), "fuzzy")
        # Les morceaux doivent venir dans l'ordre du texte.
        self.assertEqual(self.index.find("le modèle de la clause […] Le traité Cobden-Chevalier"), "not_found")

    def test_invented_quote_is_not_found(self):
        self.assertEqual(self.index.find("Le traité de Versailles de 1919 redessine la carte de l'Europe"), "not_found")
        self.assertEqual(self.index.find("le tarif Méline en Belgique (1895)"), "not_found")

    def test_short_quotes_must_match_exactly(self):
        self.assertEqual(self.index.find("tarif Méline"), "verified")
        self.assertEqual(self.index.find("tarif Mélina"), "not_found")

    def test_empty_quote_has_no_status(self):
        self.assertIsNone(self.index.find("  « »  "))


class TestDocument(unittest.TestCase):
    DOC = {
        "schema": "ankigen.timeline/1", "title": "T", "lang": "fr", "tracks": [],
        "eras": [{"id": "premiere", "label": "Première mondialisation", "start": "1860", "end": "1914",
                  "source_quote": "Bairoch étudie le TCAM entre 1815 et 1914"}],
        "periods": [],
        "events": [
            {"id": "cobden", "label": "Traité", "date": "1860", "source_quote": "Le traité Cobden-Chevalier de 1860"},
            {"id": "versailles", "label": "Versailles", "date": "1919",
             "source_quote": "Le traité de Versailles redessine la carte de l'Europe en 1919"},
            {"id": "ajout", "label": "Ajout", "date": "1920", "origin": "model"},
            {"id": "main", "label": "Saisi à la main", "date": "1921"},
        ],
        "links": [],
    }

    def test_statuses_and_warnings(self):
        statuses, warnings = tq.check_document(self.DOC, SOURCE)
        self.assertEqual(statuses, {"premiere": "verified", "cobden": "verified", "versailles": "not_found"})
        self.assertEqual(warnings, [{"path": "/events/1/source_quote", "code": "quote_not_found", "params": {}}])

    def test_no_source_text_means_nothing_to_check(self):
        self.assertEqual(tq.check_document(self.DOC, ""), ({}, []))

    def test_annotate_only_touches_valid_reports(self):
        report = {"ok": True, "errors": [], "warnings": [{"path": "", "code": "x", "params": {}}],
                  "normalized": self.DOC}
        annotated = tq.annotate(report, SOURCE)
        self.assertEqual(annotated["quotes"]["versailles"], "not_found")
        self.assertEqual([w["code"] for w in annotated["warnings"]], ["x", "quote_not_found"])
        self.assertEqual(len(report["warnings"]), 1)          # le rapport d'origine est intact
        refused = {"ok": False, "errors": [{}], "warnings": [], "normalized": None}
        self.assertIs(tq.annotate(refused, SOURCE), refused)

    def test_every_warning_code_is_translated(self):
        for lang in i18n.LANGUAGES:
            catalog = i18n.load_catalog(lang)
            for code in tq.WARNING_CODES:
                self.assertTrue(f"timeline.warn.{code}" in catalog, f"{lang}: {code}")


class TestPerformance(unittest.TestCase):
    def test_a_course_and_fifty_quotes_stay_fast(self):
        rng = random.Random(7)
        words = ["commerce", "tarif", "libre-échange", "protectionnisme", "traité", "crise", "monnaie",
                 "or", "change", "empire", "colonies", "croissance", "industrie", "banque", "dette"]
        sentences = []
        for i in range(700):
            sentence = " ".join(rng.choice(words) for _ in range(12))
            sentences.append(f"En {1800 + i % 220}, {sentence}.")
        source = " ".join(sentences)
        self.assertGreater(len(source), 60_000)
        quotes = []
        for i in range(50):
            quote = sentences[rng.randrange(len(sentences))].split()
            if i % 2:
                quote[rng.randrange(len(quote))] = "inventé"
            quotes.append(" ".join(quote))
        start = time.perf_counter()
        index = tq.SourceIndex(source)
        statuses = [index.find(q) for q in quotes]
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0, f"{elapsed:.2f} s")
        self.assertEqual(statuses[0::2], ["verified"] * 25)
        self.assertTrue(all(s in ("fuzzy", "not_found") for s in statuses[1::2]))


if __name__ == "__main__":
    unittest.main()
