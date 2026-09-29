#!/usr/bin/env python3
"""
tests/test_timeline_prompt.py — Texte source par portée, prompts d'extraction et de correction.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402
import timeline_prompt as tp  # noqa: E402
import timeline_quotes  # noqa: E402
import timeline_schema  # noqa: E402

HINT = "(écris {{IMG:1}} dans une carte pour y afficher cette image)"


def project(extra_chars=0):
    return {
        "deck_prefix": "ESH",
        "source": "CH1_ La mondialisation.docx",
        "prompts": [
            {"id": 0, "deck": "ESH", "prompt": "CH1: La mondialisation"},
            {"id": 1, "deck": "ESH::CH1: La mondialisation(1)::I - Les phases",
             "prompt": "En 1860, le traité Cobden-Chevalier ouvre l'ère du libre-échange.\n\n"
                       "[IMAGE 1 — description : carte des échanges]\n" + HINT},
            {"id": 2, "deck": "ESH::CH1: La mondialisation(1)::I - Les phases::A) Détail",
             "prompt": "Le tarif Méline de 1892 marque le retour du protectionnisme." + "x" * extra_chars},
            {"id": 3, "deck": "ESH::CH1: La mondialisation(1)::I - Les phases de repli",
             "prompt": "Le krach de 1929 ouvre la Grande Dépression."},
            {"id": 4, "deck": "ESH::CH1: La mondialisation(1)::II - Les théories",
             "prompt": "Ricardo publie ses Principes en 1817."},
            {"id": 5, "deck": "ESH::CH1: La mondialisation(1)::II - Les théories", "prompt": "   "},
        ],
    }


class TestDecks(unittest.TestCase):
    def test_chapter_membership_is_decided_segment_by_segment(self):
        # E5 : « Les phases » ne capture pas « Les phases de repli ».
        self.assertTrue(tp.in_chapter("A::Les phases", "A::Les phases"))
        self.assertTrue(tp.in_chapter("A::Les phases::B", "A::Les phases"))
        self.assertFalse(tp.in_chapter("A::Les phases de repli", "A::Les phases"))
        self.assertFalse(tp.in_chapter("A::Bretagne", "A::B"))
        self.assertFalse(tp.in_chapter("A::B", ""))

    def test_heading_path_leaves_out_the_deck_prefix(self):
        self.assertEqual(tp.heading_path("Économie::Mondialisation::Les phases", "Économie"),
                         "Mondialisation › Les phases")
        self.assertEqual(tp.heading_path("Mondialisation::Les phases", ""), "Mondialisation › Les phases")
        self.assertEqual(tp.heading_path("ESH", "ESH"), "")

    def test_clean_title_drops_outline_numbering(self):
        self.assertEqual(tp.clean_title("I - Quand convient-il de parler de mondialisation ?"),
                         "Quand convient-il de parler de mondialisation ?")
        self.assertEqual(tp.clean_title("B) Une première mondialisation"), "Une première mondialisation")
        self.assertEqual(tp.clean_title("CH1: La dynamique de la mondialisation économique(1)"),
                         "La dynamique de la mondialisation économique")
        self.assertEqual(tp.clean_title("L'importance du protectionnisme"), "L'importance du protectionnisme")


class TestScopes(unittest.TestCase):
    def ids(self, scope):
        return [c["id"] for c in tp.scope_chunks(project(), scope)]

    def test_chunk_chapter_and_project(self):
        self.assertEqual(self.ids({"kind": "chunk", "chunk_ids": [2]}), [2])
        self.assertEqual(self.ids({"kind": "chapter", "deck_path": "ESH::CH1: La mondialisation(1)::I - Les phases"}),
                         [1, 2])
        self.assertEqual(self.ids({"kind": "project"}), [0, 1, 2, 3, 4, 5])

    def test_unknown_or_empty_scope_is_refused(self):
        with self.assertRaises(ValueError):
            tp.scope_chunks(project(), {"kind": "galaxy"})
        with self.assertRaises(ValueError):
            tp.scope_chunks(project(), {"kind": "chapter", "deck_path": "ESH::Nulle part"})

    def test_chapter_levels_are_the_ancestors_that_add_something(self):
        levels = tp.chapter_levels(project(), 2)
        # « CH1 » recouvre tout le cours (au chunk de titre près) et « A) Détail » ce
        # seul chunk : seuls restent les niveaux intermédiaires.
        self.assertEqual([level["deck_path"] for level in levels],
                         ["ESH::CH1: La mondialisation(1)::I - Les phases"])
        self.assertEqual(levels[0]["chunk_ids"], [1, 2])
        self.assertEqual(levels[0]["path"], "CH1: La mondialisation(1) › I - Les phases")
        self.assertEqual(tp.chapter_levels(project(), 99), [])

    def test_scope_deck(self):
        p = project()
        self.assertEqual(tp.scope_deck(p, {"kind": "chunk", "chunk_ids": [2]}),
                         "ESH::CH1: La mondialisation(1)::I - Les phases::A) Détail")
        self.assertEqual(tp.scope_deck(p, {"kind": "chapter", "deck_path": "ESH::CH1: La mondialisation(1)::I - Les phases"}),
                         "ESH::CH1: La mondialisation(1)::I - Les phases")
        # Tout le cours : le cours lui-même, pas le préfixe partagé par plusieurs cours.
        self.assertEqual(tp.scope_deck(p, {"kind": "project"}), "ESH::CH1: La mondialisation(1)")

    def test_scope_title(self):
        p = project()
        self.assertEqual(tp.scope_title(p, {"kind": "project"}), "La mondialisation")
        self.assertEqual(tp.scope_title(p, {"kind": "chapter", "deck_path": "ESH::CH1: La mondialisation(1)::I - Les phases"}),
                         "Les phases")
        self.assertEqual(tp.scope_title(p, {"kind": "chunk", "chunk_ids": [2]}), "Détail")


class TestSource(unittest.TestCase):
    def test_each_chunk_follows_its_heading_path(self):
        chunks = tp.scope_chunks(project(), {"kind": "project"})
        text, spans = tp.build_source(chunks, "ESH")
        self.assertTrue(text.startswith("CH1: La mondialisation\n\n## CH1: La mondialisation(1) › I - Les phases\n\n"))
        self.assertIn("## CH1: La mondialisation(1) › I - Les phases › A) Détail\n\nLe tarif Méline", text)
        # Le chunk vide n'a pas de place dans le texte ni dans les positions.
        self.assertEqual([span[0] for span in spans], [0, 1, 2, 3, 4])

    def test_spans_give_back_each_chunk(self):
        chunks = tp.scope_chunks(project(), {"kind": "project"})
        text, spans = tp.build_source(chunks, "ESH")
        self.assertEqual(tp.chunk_text(text, spans, 4),
                         "## CH1: La mondialisation(1) › II - Les théories\n\nRicardo publie ses Principes en 1817.")
        self.assertEqual(tp.chunk_heading(text, spans, 4), "CH1: La mondialisation(1) › II - Les théories")
        self.assertEqual(tp.chunk_heading(text, spans, 0), "")
        with self.assertRaises(KeyError):
            tp.chunk_text(text, spans, 5)

    def test_card_hints_are_removed_but_image_descriptions_kept(self):
        text, _ = tp.build_source(tp.scope_chunks(project(), {"kind": "chunk", "chunk_ids": [1]}), "ESH")
        self.assertIn("[IMAGE 1 — description : carte des échanges]", text)
        self.assertNotIn("{{IMG:1}}", text)

    def test_summary_switches_to_per_chunk_beyond_the_threshold(self):
        small = tp.scope_summary(project(), {"kind": "project"}, "fr")
        self.assertEqual(small["strategy"], "single")
        self.assertEqual(small["chunks"], 5)
        self.assertGreater(small["tokens"], small["chars"] // tp.CHARS_PER_TOKEN)
        big = tp.scope_summary(project(tp.SINGLE_PROMPT_MAX_CHARS), {"kind": "project"}, "fr")
        self.assertEqual(big["strategy"], "per_chunk")
        self.assertGreater(big["chars"], tp.SINGLE_PROMPT_MAX_CHARS)

    def test_guess_lang(self):
        self.assertEqual(tp.guess_lang("Le traité de 1860 ouvre l'ère du libre-échange et marque la fin des tarifs."), "fr")
        self.assertEqual(tp.guess_lang("The treaty of 1860 opens the era of free trade and ends the tariffs."), "en")
        self.assertEqual(tp.guess_lang("1860 : Cobden-Chevalier", "fr"), "fr")        # trop court : le défaut
        self.assertEqual(tp.scope_summary(project(), {"kind": "project"}, "en")["lang"], "fr")

    def test_date_mentions(self):
        self.assertEqual(tp.date_mentions("En 1860, puis en 1892 et au XIXe siècle ; 58 % en 1870."), 4)
        self.assertEqual(tp.date_mentions("Adam Smith et les avantages absolus."), 0)


class TestTemplates(unittest.TestCase):
    KNOWN = set(tp.limits()) | {"lang", "title", "source", "tracks", "errors", "warnings"}

    def test_every_language_has_the_same_blocks(self):
        reference = set(tp.load_blocks("en"))
        for lang in i18n.LANGUAGES:
            self.assertTrue(tp.template_path(lang).is_file(), lang)
            self.assertEqual(set(tp.load_blocks(lang)), reference, lang)

    def test_every_variable_is_known(self):
        for lang in i18n.LANGUAGES:
            for name, block in tp.load_blocks(lang).items():
                unknown = set(re.findall(r"\{\{([a-z_]+)\}\}", block)) - self.KNOWN
                self.assertFalse(unknown, f"{lang}/{name} : {unknown}")

    def example(self, lang):
        block = tp.load_blocks(lang)["example"]
        start, end = block.index("{"), block.rindex("}")
        paragraphs = [p.strip() for p in block[:start].split("\n\n") if p.strip()]
        return paragraphs[-2], block[start:end + 1]

    def test_the_example_is_a_valid_document_without_warnings(self):
        for lang in i18n.LANGUAGES:
            source, raw = self.example(lang)
            report = timeline_schema.validate_raw(raw, default_lang=lang)
            self.assertTrue(report["ok"], (lang, report["errors"]))
            self.assertEqual(report["warnings"], [], lang)
            self.assertEqual(report["normalized"]["lang"], lang)
            # Les citations de l'exemple sont bien copiées de son texte source.
            statuses, _ = timeline_quotes.check_document(report["normalized"], source)
            self.assertEqual(set(statuses.values()), {"verified"}, lang)

    def test_the_example_teaches_every_editorial_rule(self):
        for lang in i18n.LANGUAGES:
            doc = json.loads(self.example(lang)[1])
            elements = doc["eras"] + doc["periods"] + doc["events"]
            self.assertTrue(all(element.get("source_quote") for element in elements), lang)
            for element in elements:
                words = len(element["source_quote"].split())
                self.assertTrue(5 <= words <= 25, (lang, element["id"], words))
                self.assertTrue(2 <= len(element["label"].split()) <= 8 or element in doc["eras"], element["label"])
            self.assertTrue(2 <= len(doc["tracks"]) <= 5)


class TestExtractionPrompt(unittest.TestCase):
    def test_full_prompt_carries_contract_rules_example_and_source(self):
        prompt = tp.extraction_prompt("Le krach de 1929.", lang="fr", title="Crises")
        for needle in ("## Format du JSON", "## Écrire les dates", "## Règles éditoriales", "## Exemple",
                       "Titre de la frise : Crises", '"lang" : "fr"', "<<<SOURCE\nLe krach de 1929.\nSOURCE>>>",
                       '"1501"', "## Mode strict"):
            self.assertIn(needle, prompt)
        self.assertNotIn("## Mode enrichi", prompt)
        self.assertNotIn("{{", prompt.replace("{{IMG", ""))

    def test_limits_come_from_the_schema(self):
        prompt = tp.extraction_prompt("x", lang="en")
        fields = timeline_schema.ROOT_FIELDS
        self.assertIn(f"0 to {fields['events']['max']} point events", prompt)
        self.assertIn(f"0 to {fields['tracks']['max']} tracks", prompt)
        self.assertIn(f"at most {timeline_schema.EVENT_FIELDS['source_quote']['max']} characters", prompt)
        self.assertIn("at most 48 characters", prompt)

    def test_enriched_mode_allows_model_additions(self):
        strict = tp.extraction_prompt("x", lang="en", mode="strict")
        enriched = tp.extraction_prompt("x", lang="en", mode="enriched")
        self.assertIn("## Enriched mode", enriched)
        self.assertNotIn("## Strict mode", enriched)
        self.assertIn('"origin": "model"', enriched)
        self.assertNotEqual(strict, enriched)
        with self.assertRaises(ValueError):
            tp.extraction_prompt("x", mode="creative")

    def test_skill_mode_reduces_the_prompt_to_the_source(self):
        prompt = tp.extraction_prompt("Le krach de 1929.", lang="fr", mode="enriched", title="Crises", skill=True)
        self.assertIn("Skill « Frise chronologique Ankigen », en mode enrichi", prompt)
        self.assertIn("<<<SOURCE\nLe krach de 1929.\nSOURCE>>>", prompt)
        self.assertIn('Langue du texte : "fr"', prompt)
        self.assertNotIn("## Format du JSON", prompt)
        self.assertLess(len(prompt), 400)

    def test_chunk_mode_accepts_an_empty_answer_and_reuses_tracks(self):
        tracks = [{"id": "commerce", "label": "Commerce"}, {"id": "monnaie", "label": "Monnaie"}]
        prompt = tp.extraction_prompt("x", lang="fr", chunk=True, tracks=tracks)
        self.assertIn("## Ce passage", prompt)
        self.assertIn("des listes vides", prompt)
        self.assertIn('"commerce" (Commerce), "monnaie" (Monnaie)', prompt)
        self.assertNotIn("Pistes déjà utilisées", tp.extraction_prompt("x", lang="fr", chunk=True))
        self.assertNotIn("## Ce passage", tp.extraction_prompt("x", lang="fr"))

    def test_the_source_is_inserted_verbatim(self):
        source = "Un texte qui contient {{title}} et {{source}} et \\1 sans être relu."
        prompt = tp.extraction_prompt(source, lang="en", title="T")
        self.assertIn(f"<<<SOURCE\n{source}\nSOURCE>>>", prompt)

    def test_unknown_language_falls_back_to_english(self):
        self.assertIn("## JSON format", tp.extraction_prompt("x", lang="de"))

    def test_skill_text_is_a_complete_skill(self):
        for lang in i18n.LANGUAGES:
            text = tp.skill_text(lang)
            self.assertTrue(text.startswith("---\nname: ankigen-timeline\n"), lang)
            self.assertIn("<<<SOURCE", text)
            self.assertNotIn("{{", text)
            self.assertIn('"origin": "model"', text)


class TestCorrectionPrompt(unittest.TestCase):
    RAW = json.dumps({
        "schema": "ankigen.timeline/1", "title": "Crises", "lang": "fr",
        "events": [
            {"id": "krach", "date": "vers 1929", "label": "Krach"},
            {"id": "krach", "date": "1933", "label": "New Deal", "lable": "x"},
            {"id": "lehman", "date": "2008", "label": "Faillite de Lehman en 2008"},
        ],
    })

    def report(self):
        return timeline_schema.validate_raw(self.RAW, default_lang="fr")

    def test_lists_every_error_with_its_path_in_the_document_language(self):
        report = self.report()
        prompt = tp.correction_prompt(report, lang="fr")
        self.assertTrue(prompt.startswith("Ton JSON contient les erreurs suivantes :"))
        for error in report["errors"]:
            self.assertIn(f"- {error['path'] or '/'} → ", prompt)
        self.assertEqual(prompt.count("\n- "), len(report["errors"]))
        self.assertIn("Renvoie le JSON complet corrigé", prompt)
        english = tp.correction_prompt(report, lang="en")
        self.assertTrue(english.startswith("Your JSON has the following errors:"))

    def test_warnings_only_on_request(self):
        report = timeline_schema.validate_raw(json.dumps({
            "schema": "ankigen.timeline/1", "title": "Crises", "lang": "fr",
            "events": [{"id": "lehman", "date": "2008", "label": "Faillite de Lehman en 2008"}],
        }), default_lang="fr")
        self.assertTrue(report["ok"])
        self.assertEqual(tp.correction_prompt(report, lang="fr"), "")
        prompt = tp.correction_prompt(report, lang="fr", include_warnings=True)
        self.assertIn("/events/0/label", prompt)
        self.assertNotIn("erreurs suivantes", prompt)

    def test_a_json_syntax_error_points_at_the_whole_document(self):
        report = timeline_schema.validate_raw('{"schema": "ankigen.timeline/1",}', default_lang="en")
        prompt = tp.correction_prompt(report, lang="en")
        self.assertIn("- / → ", prompt)


if __name__ == "__main__":
    unittest.main()
