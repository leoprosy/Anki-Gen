#!/usr/bin/env python3
"""
tests/test_timeline_cards.py — Cartes Anki tirées d'une frise (§10).

Chaque type de carte, les regroupements par date, le mélange déterministe, les
champs sûrs pour le TSV (ni tabulation ni saut de ligne, HTML échappé), les ids
stables, le deck et les images (noms à hash, variante masquée tirée de la display
list sans l'étiquette cachée).

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import timeline_cards as tc  # noqa: E402
import timeline_schema  # noqa: E402
from timeline_render_svg import render  # noqa: E402

SAFE_MEDIA_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def doc(**changes):
    raw = {
        "schema": "ankigen.timeline/1", "title": "Commerce <XIXe>", "lang": "fr",
        "tracks": [{"id": "commerce", "label": "Commerce"}, {"id": "monnaie", "label": "Monnaie"}],
        "periods": [
            {"id": "etalon_or", "track": "monnaie", "label": "Étalon-or classique", "start": "1873", "end": "1914",
             "description": "Changes fixes.\nSur l'or."},
            {"id": "ajout", "track": "monnaie", "label": "Ajout du modèle", "start": "1920", "end": "1925",
             "origin": "model"},
        ],
        "events": [
            {"id": "corn_laws", "track": "commerce", "date": "1846", "label": "Abrogation des Corn Laws", "importance": 3},
            {"id": "cobden", "track": "commerce", "date": "1860-01-23", "label": "Traité <Cobden>\tChevalier",
             "description": "Libre-échange\tfranco-britannique."},
            {"id": "suez", "track": "commerce", "date": "1869-11", "label": "Canal de Suez"},
            {"id": "meline", "track": "commerce", "date": "1892", "label": "Tarif Méline"},
            {"id": "mckinley", "track": "commerce", "date": "1892", "label": "Tarif McKinley"},
            {"id": "annees_folles", "track": "commerce", "date": "1920", "precision": "decade", "label": "Années folles"},
            {"id": "renaissance", "track": "commerce", "date": "1501", "precision": "century", "label": "Renaissance"},
            {"id": "gold_1900", "track": "monnaie", "date": "1900", "label": "Gold Standard Act"},
            {"id": "invention", "track": "monnaie", "date": "1901", "label": "Ajout", "origin": "model"},
        ],
    }
    raw.update(changes)
    report = timeline_schema.validate(raw, default_lang="fr")
    assert report["ok"], report["errors"]
    return report["normalized"]


def by_type(cards, kind):
    return [card for card in cards if card.type == kind]


class TestTextCards(unittest.TestCase):
    def setUp(self):
        self.doc = doc()
        self.cards = tc.generate(self.doc, types=tc.CARD_TYPES)

    def test_event_to_date_asks_by_precision_and_skips_model_additions(self):
        cards = {card.ref: card for card in by_type(self.cards, "event_to_date")}
        self.assertNotIn("invention", cards)
        self.assertEqual(cards["corn_laws"].front, "En quelle année : Abrogation des Corn Laws ?")
        self.assertTrue(cards["cobden"].front.startswith("À quelle date :"))
        self.assertTrue(cards["suez"].front.startswith("En quel mois :"))
        self.assertTrue(cards["annees_folles"].front.startswith("Dans quelle décennie :"))
        self.assertTrue(cards["renaissance"].front.startswith("Au cours de quel siècle :"))
        self.assertIn(f'<span style="{tc.DATE_STYLE}">23 janvier 1860</span>', cards["cobden"].back)

    def test_date_to_event_groups_same_date_and_track(self):
        cards = by_type(self.cards, "date_to_event")
        grouped = next(card for card in cards if card.ref == "meline+mckinley")
        self.assertIn("Tarif Méline", grouped.back)
        self.assertIn("Tarif McKinley", grouped.back)
        self.assertIn("— Commerce : que se passe-t-il ?", grouped.front)
        # Précision au siècle ou plus large : la question serait trop vague.
        self.assertNotIn("renaissance", [card.ref for card in cards])
        self.assertIn("gold_1900", [card.ref for card in cards])

    def test_period_bounds(self):
        cards = by_type(self.cards, "period_bounds")
        self.assertEqual([card.ref for card in cards], ["etalon_or"])
        self.assertEqual(cards[0].front, "Bornes de la période : Étalon-or classique ?")
        self.assertIn("1873–1914", cards[0].back)
        self.assertIn("Changes fixes.<br>Sur l'or.", cards[0].back)

    def test_group_sizes_cover_everything_in_threes_to_fives(self):
        for n in range(3, 30):
            sizes = tc._group_sizes(n)
            self.assertEqual(sum(sizes), n, n)
            self.assertTrue(all(3 <= size <= 5 for size in sizes), (n, sizes))
        self.assertEqual(tc._group_sizes(2), [])

    def test_ordering_is_shuffled_deterministically_and_never_in_order(self):
        cards = by_type(self.cards, "ordering")
        # Commerce : 6 dates distinctes (Méline et McKinley partagent 1892) → 3 + 3.
        refs = [card.ref.split("+") for card in cards]
        self.assertEqual([len(r) for r in refs], [3, 3])
        self.assertFalse({"meline", "mckinley"} <= set(refs[0] + refs[1]))
        again = by_type(tc.generate(self.doc, types=["ordering"]), "ordering")
        self.assertEqual([c.front for c in cards], [c.front for c in again])
        for card in cards:
            shown = card.front.split(" : ", 1)[1].split(" · ")
            answer = re.findall(r"</span> — ([^<]+)</li>", card.back)
            self.assertEqual(sorted(shown), sorted(answer))
            self.assertNotEqual(shown, answer)

    def test_neighbors(self):
        cards = {card.ref: card for card in by_type(self.cards, "neighbors")}
        first = cards["renaissance"]            # le plus ancien de sa piste
        self.assertIn("Après :", first.back)
        self.assertNotIn("Avant :", first.back)
        self.assertIn("Avant :", cards["suez"].back)
        self.assertIn("Après :", cards["suez"].back)
        self.assertTrue(cards["suez"].front.startswith("Dans Commerce, qu'est-ce qui précède et qui suit"))
        self.assertNotIn("gold_1900", cards)    # seul évènement du cours dans sa piste

    def test_fields_are_safe_for_tsv_and_escaped(self):
        for card in self.cards:
            for text in (card.front, card.back):
                self.assertNotIn("\t", text)
                self.assertNotIn("\n", text)
                self.assertNotIn("<Cobden>", text)
        cobden = next(c for c in self.cards if c.type == "event_to_date" and c.ref == "cobden")
        self.assertIn("Traité &lt;Cobden&gt; Chevalier", cobden.front)
        self.assertIn("Libre-échange franco-britannique.", cobden.back)

    def test_ids_are_stable_and_follow_the_question(self):
        again = tc.generate(self.doc, types=tc.CARD_TYPES)
        self.assertEqual([c.id for c in self.cards], [c.id for c in again])
        self.assertEqual(len({c.id for c in self.cards}), len(self.cards))
        renamed = json.loads(json.dumps(self.doc))
        renamed["events"][2]["label"] = "Ouverture du canal de Suez"
        changed = {c.id for c in tc.generate(renamed, types=["event_to_date"])}
        before = {c.id for c in by_type(self.cards, "event_to_date")}
        self.assertEqual(len(before - changed), 1)

    def test_default_types(self):
        cards = tc.generate(self.doc)
        self.assertEqual({card.type for card in cards}, set(tc.DEFAULT_TYPES))

    def test_english_document(self):
        english = doc(lang="en")
        card = next(c for c in tc.generate(english, types=["event_to_date"]) if c.ref == "corn_laws")
        self.assertEqual(card.front, "In which year: Abrogation des Corn Laws?")

    def test_deck(self):
        self.assertEqual(tc.default_deck("ESH::CH1", "fr"), "ESH::CH1::Chronologie")
        self.assertEqual(tc.default_deck("ESH::CH1", "en"), "ESH::CH1::Timeline")
        self.assertEqual(tc.default_deck("", "fr"), "Chronologie")


class TestImageCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = timeline_schema.validate(json.loads(
            (ROOT / "tests" / "fixtures_timeline" / "mondialisation.json").read_text(encoding="utf-8")))["normalized"]
        cls.layout = render(cls.doc, tc.card_layout_options()).layout
        cls.prefix = tc.media_prefix("mondialisation-3f9a", "CH1 La mondialisation")
        cls.cards = tc.generate(cls.doc, types=["whole_image", "masked_image"], layout=cls.layout,
                                media_prefix=cls.prefix)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-cards-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_media_names(self):
        self.assertEqual(self.prefix, "ag_ch1_la_mondialisation_tl_mondialisation_3f9a")
        self.assertEqual(tc.media_prefix("frise-0001"), "ag_tl_frise_0001")
        for card in self.cards:
            for name in card.media:
                self.assertRegex(name, rf"^{self.prefix}_[a-z0-9_-]+_(full|q|a)_[0-9a-f]{{10}}\.png$")
                self.assertRegex(name, SAFE_MEDIA_NAME)

    def test_names_change_with_the_content(self):
        edited = json.loads(json.dumps(self.doc))
        edited["events"][0]["label"] = "Abrogation des lois sur le blé"
        layout = render(edited, tc.card_layout_options()).layout
        other = tc.generate(edited, types=["whole_image"], layout=layout, media_prefix=self.prefix)
        again = tc.generate(self.doc, types=["whole_image"], layout=self.layout, media_prefix=self.prefix)
        self.assertEqual(again[0].media, by_type(self.cards, "whole_image")[0].media)
        self.assertNotEqual(other[0].media, again[0].media)

    def test_names_change_when_the_renderer_changes(self):
        from unittest.mock import patch
        current = tc.generate(self.doc, types=["whole_image"], layout=self.layout, media_prefix=self.prefix)
        with patch.object(tc, "RENDER_VERSION", tc.RENDER_VERSION - 1):
            previous = tc.generate(self.doc, types=["whole_image"], layout=self.layout, media_prefix=self.prefix)
        self.assertNotEqual(current[0].media, previous[0].media)

    def test_masked_cards_are_important_labeled_and_capped(self):
        masked = by_type(self.cards, "masked_image")
        labeled = {p.ref for p in self.layout.primitives if p.role == "event-label"}
        events = {e["id"]: e for e in self.doc["events"]}
        self.assertTrue(masked)
        self.assertLessEqual(len(masked), tc.MAX_MASKED)
        for card in masked:
            self.assertIn(card.ref, labeled)
            self.assertGreaterEqual(events[card.ref]["importance"], 2)
            front, back = card.media
            self.assertIn(f'<img src="{front}">', card.front)
            self.assertIn(f'<img src="{back}">', card.back)
            self.assertTrue(front.split("_")[-2] == "q" and back.split("_")[-2] == "a")

    def test_masked_variant_hides_only_that_label(self):
        ref = by_type(self.cards, "masked_image")[0].ref
        measure = lambda text, size, weight: 7.0 * len(text)  # noqa: E731
        hidden, _ = tc._masked_primitives(self.layout, ref, "q", measure)
        revealed, _ = tc._masked_primitives(self.layout, ref, "a", measure)
        own = [p for p in self.layout.primitives if p.ref == ref and p.role in ("event-label", "event-date")]
        self.assertTrue(own)
        self.assertFalse([p for p in hidden if p.ref == ref and p.role in ("event-label", "event-date")])
        self.assertEqual([p for p in hidden if p.role == "highlight" and getattr(p, "lines", None)][0].lines, ("?",))
        for prim in own:
            self.assertIn(prim, revealed)
        # Rien d'autre ne bouge : la mise en page est celle de la frise.
        others = [p for p in self.layout.primitives if p not in own]
        self.assertEqual([p for p in hidden if p.role != "highlight"], others)

    def test_rendered_crop(self):
        card = by_type(self.cards, "masked_image")[0]
        data = tc.render_media(self.layout, "q", card.ref)
        image = Image.open(io.BytesIO(data))
        gutter = self.layout.scale.segments[0][2]
        self.assertEqual(image.size[0], round(gutter) + tc.CROP_GAP + 2 * tc.MASK_WINDOW)
        highlight = tuple(int(tc.HIGHLIGHT[i:i + 2], 16) for i in (1, 3, 5))
        self.assertIn(highlight, {color for _, color in image.getcolors(1 << 20)})

    def test_ensure_media_renders_once(self):
        cards = self.cards[:2]
        written = tc.ensure_media(cards, self.layout, self.tmp)
        self.assertEqual(sorted(written), sorted(name for card in cards for name in card.media))
        for name in written:
            with Image.open(self.tmp / name) as image:
                self.assertGreater(image.size[0], 0)
        self.assertEqual(tc.ensure_media(cards, self.layout, self.tmp), [])
        only = tc.ensure_media(self.cards, self.layout, self.tmp / "sub", names={self.cards[0].media[0]})
        self.assertEqual(only, [self.cards[0].media[0]])

    def test_no_image_cards_without_a_layout(self):
        self.assertEqual(tc.generate(self.doc, types=["whole_image", "masked_image"]), [])


if __name__ == "__main__":
    unittest.main()
