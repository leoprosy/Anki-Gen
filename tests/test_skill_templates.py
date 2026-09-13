#!/usr/bin/env python3
"""
tests/test_skill_templates.py — Intégrité des templates de Skill Claude.

Ces fichiers sont ce que l'utilisateur copie pour écrire son skill. Une
convention manquante ou un marqueur de la mauvaise langue et les images du
.docx n'atterrissent jamais dans les cartes.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402

TEMPLATE_DIR = ROOT / "skill_templates"


class TestSkillTemplates(unittest.TestCase):
    def templates(self):
        return {lang: (TEMPLATE_DIR / f"{lang}.md").read_text(encoding="utf-8")
                for lang in i18n.LANGUAGES}

    def test_one_template_per_language(self):
        for lang in i18n.LANGUAGES:
            path = TEMPLATE_DIR / f"{lang}.md"
            self.assertTrue(path.is_file(), f"template manquant : {path.name}")
            self.assertGreater(len(path.read_text(encoding="utf-8")), 500)

    def test_frontmatter_is_well_formed(self):
        """Sans `name` ni `description`, Claude ne sait pas quand charger le skill."""
        for lang, text in self.templates().items():
            lines = text.split("\n")
            self.assertEqual(lines[0], "---", f"{lang}: pas de frontmatter en tête")
            closing = lines.index("---", 1)
            front = "\n".join(lines[1:closing])
            self.assertIn("name:", front, f"{lang}: `name` absent du frontmatter")
            self.assertIn("description:", front, f"{lang}: `description` absente")

    def test_placeholder_convention_is_documented(self):
        """{{IMG:n}} / {{TABLE:n}} sont ce que resolve_placeholders sait lire."""
        for lang, text in self.templates().items():
            self.assertIn("{{IMG:n}}", text, f"{lang}: convention image absente")
            self.assertIn("{{TABLE:n}}", text, f"{lang}: convention tableau absente")

    def test_forbids_hand_written_img_tags(self):
        """Une balise <img> écrite à la main pointe vers un fichier inexistant."""
        for lang, text in self.templates().items():
            self.assertIn("<img>", text, f"{lang}: l'interdiction n'est pas énoncée")

    def test_marker_matches_the_language_of_the_prompt(self):
        """
        Les marqueurs annoncés doivent être ceux que render_prompt_text émet
        dans cette même langue, sinon le modèle cherche un marqueur absent.
        """
        expected = {
            "en": ("[IMAGE n]", "[TABLE n]", "[TABLEAU n]"),
            "fr": ("[IMAGE n]", "[TABLEAU n]", "[TABLE n]"),
        }
        for lang, text in self.templates().items():
            image, table, wrong = expected[lang]
            self.assertIn(image, text, f"{lang}: marqueur image absent")
            self.assertIn(table, text, f"{lang}: marqueur tableau absent")
            self.assertNotIn(wrong, text, f"{lang}: marqueur d'une autre langue")

    def test_output_contract_is_stated(self):
        """Deux colonnes séparées par une tabulation, sans ligne d'en-tête."""
        for lang, text in self.templates().items():
            self.assertIn("<TAB>", text, f"{lang}: séparateur non énoncé")

    def test_examples_use_mathjax_not_the_latex_tag(self):
        """
        `[latex]…[/latex]` exige une distribution LaTeX installée ; les exemples
        s'en tiennent à MathJax, intégré à Anki. La syntaxe [latex] peut être
        *mentionnée* dans l'explication, jamais employée dans une carte.
        """
        for lang, text in self.templates().items():
            card_rows = [l for l in text.split(chr(10)) if chr(9) in l]
            self.assertTrue(card_rows, f'{lang}: aucun exemple de carte')
            for row in card_rows:
                self.assertNotIn('[latex]', row, f'{lang}: [latex] dans un exemple')
            self.assertIn("anki-mathjax", text, f"{lang}: MathJax non documenté")


if __name__ == "__main__":
    unittest.main()
