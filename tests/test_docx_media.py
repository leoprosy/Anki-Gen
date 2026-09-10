#!/usr/bin/env python3
"""
tests/test_docx_media.py — Tests de l'extraction images/tableaux et de l'export.

Repose sur `unittest` (stdlib) : lançable sans dépendance supplémentaire.

    python -m unittest discover -s tests        (ou : python tests/test_docx_media.py)
    python -m pytest tests                      (si pytest est installé)
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_anki_csv import parse_tsv_response  # noqa: E402
from make_fixtures import build_all  # noqa: E402
from media_store import MediaStore  # noqa: E402
from parse_cours import parse_docx  # noqa: E402
from project_store import export_rows, normalize, set_asset_alt  # noqa: E402
from render import (  # noqa: E402
    render_prompt_text,
    render_table_html,
    render_table_text,
    resolve_placeholders,
)


class FakeImage:
    """Imite `docx.image.image.Image` pour tester MediaStore sans .docx."""

    def __init__(self, blob, ext, sha1, px_width=100, px_height=80):
        self.blob = blob
        self.ext = ext
        self.sha1 = sha1
        self.px_width = px_width
        self.px_height = px_height


class BaseFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ankigen-tests-"))
        cls.fixtures = build_all(cls.tmp / "fixtures")
        cls.media = cls.tmp / "media"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def parse(self, name, deck_prefix="*TEST*"):
        return parse_docx(
            self.fixtures[name],
            deck_prefix,
            project_id=Path(name).stem,
            media_dir=self.media / Path(name).stem,
        )


class TestImages(BaseFixtureTest):
    def test_image_seule_dans_un_paragraphe_vide_est_conservee(self):
        chunks, assets, _ = self.parse("fixture_images.docx")
        image_blocks = [b for c in chunks for b in c["blocks"] if b["type"] == "image"]
        # 2 images distinctes + 1 répétition = 3 occurrences dans le document
        self.assertEqual(len(image_blocks), 3)

    def test_alt_text_est_recupere(self):
        _, assets, _ = self.parse("fixture_images.docx")
        alts = [a["alt"] for a in assets.values()]
        self.assertIn("Courbe du PIB par habitant en Angleterre, 1500-1900", alts)
        self.assertIn("", alts)  # l'image sans alt reste, avec une description vide

    def test_dedoublonnage_par_sha1(self):
        _, assets, _ = self.parse("fixture_images.docx")
        # 2 fichiers uniquement (l'image bleue apparaît deux fois)
        self.assertEqual(len(assets), 2)
        repeated = [a for a in assets.values() if a["occurrences"] == 2]
        self.assertEqual(len(repeated), 1)

    def test_fichiers_ecrits_et_prefixes(self):
        _, assets, _ = self.parse("fixture_images.docx")
        media_dir = self.media / "fixture_images"
        for asset in assets.values():
            self.assertTrue((media_dir / asset["file"]).exists())
            self.assertTrue(asset["file"].startswith("ag_fixture_images_"))
            self.assertIn(asset["sha1"][:10], asset["file"])

    def test_numerotation_locale_au_chunk(self):
        chunks, _, _ = self.parse("fixture_images.docx")
        for chunk in chunks:
            ns = [b["n"] for b in chunk["blocks"] if b["type"] == "image"]
            self.assertEqual(ns, list(range(1, len(ns) + 1)))

    def test_prompt_contient_le_marqueur_et_la_description(self):
        chunks, assets, _ = self.parse("fixture_images.docx")
        prompt = next(c["prompt"] for c in chunks
                      if any(b["type"] == "image" for b in c["blocks"]))
        self.assertIn("[IMAGE 1", prompt)
        self.assertIn("{{IMG:1}}", prompt)
        self.assertIn("Courbe du PIB", prompt)

    def test_prompt_signale_absence_de_description(self):
        chunks, assets, _ = self.parse("fixture_images.docx")
        prompts = "\n".join(c["prompt"] for c in chunks)
        self.assertIn("aucune description disponible", prompts)


class TestTables(BaseFixtureTest):
    def setUp(self):
        self.chunks, self.assets, _ = self.parse("fixture_tables.docx")
        self.tables = [b for c in self.chunks for b in c["blocks"] if b["type"] == "table"]

    def test_les_tableaux_sont_extraits(self):
        self.assertEqual(len(self.tables), 3)

    def test_tableau_colle_a_un_titre_reste_dans_sa_section(self):
        chunk = next(c for c in self.chunks
                     if any(b["type"] == "table" for b in c["blocks"]))
        self.assertIn("I - Fusions", chunk["deck"])

    def test_fusion_verticale_donne_un_rowspan(self):
        cells = [c for row in self.tables[0]["rows"] for c in row]
        self.assertTrue(any(c["rowspan"] == 2 for c in cells),
                        "la fusion verticale doit produire un rowspan=2")
        # la cellule de continuation ne doit pas être émise une seconde fois
        self.assertEqual(len(self.tables[0]["rows"][2]), 2)

    def test_fusion_horizontale_donne_un_colspan(self):
        cells = [c for row in self.tables[1]["rows"] for c in row]
        merged = [c for c in cells if c["colspan"] == 2]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "Indicateurs")

    def test_entete_en_gras_detectee(self):
        self.assertTrue(all(c["header"] for c in self.tables[0]["rows"][0]))
        self.assertFalse(any(c["header"] for c in self.tables[0]["rows"][1]))

    def test_tableau_imbrique_et_image_en_cellule(self):
        nested_found = any(cell["tables"] for row in self.tables[2]["rows"] for cell in row)
        self.assertTrue(nested_found)
        self.assertTrue(self.tables[2]["assets"], "l'image de la cellule doit être extraite")

    def test_rendu_html(self):
        html = render_table_html(self.tables[1])
        self.assertIn('colspan="2"', html)
        self.assertIn("<th", html)
        self.assertIn("overflow-x", html)   # défilement sur mobile

    def test_rendu_html_prefixe_les_images_pour_l_apercu(self):
        html = render_table_html(self.tables[2], media_prefix="/media/projet")
        if "<img" in html:
            self.assertIn('src="/media/projet/', html)

    def test_rendu_markdown_pour_le_prompt(self):
        text = render_table_text(self.tables[0])
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("| Phase |"))
        self.assertIn("---", lines[1])          # séparateur d'en-tête
        self.assertIn("Décollage", text)

    def test_image_de_cellule_decrite_dans_le_prompt(self):
        """L'image logée dans une cellule doit être annoncée à Claude, pas escamotée."""
        prompt = next(c["prompt"] for c in self.chunks if "Imbrication" in c["deck"])
        self.assertIn("[image: Schéma dans une cellule]", prompt)
        self.assertNotIn("CELLIMG", prompt)

    def test_marqueur_de_cellule_absent_du_html_de_carte(self):
        html = render_table_html(self.tables[2])
        self.assertNotIn("CELLIMG", html)
        self.assertIn("<img", html)

    def test_edition_alt_d_une_image_de_cellule_suit_dans_le_prompt(self):
        project = {
            "version": 2, "assets": self.assets,
            "prompts": [{"id": 0, "deck": c["deck"], "blocks": c["blocks"],
                         "assets": c["assets"], "prompt": c["prompt"],
                         "status": "pending", "response": ""}
                        for i, c in enumerate(self.chunks)],
        }
        for i, p in enumerate(project["prompts"]):
            p["id"] = i
        asset_id = next(a["id"] for a in self.assets.values()
                        if a["alt"] == "Schéma dans une cellule")
        touched = set_asset_alt(project, asset_id, "Courbe corrigée à la main")
        self.assertTrue(touched)
        prompt = project["prompts"][touched[0]]["prompt"]
        self.assertIn("[image: Courbe corrigée à la main]", prompt)

    def test_prompt_contient_le_tableau_et_son_placeholder(self):
        prompt = next(c["prompt"] for c in self.chunks
                      if any(b["type"] == "table" for b in c["blocks"]))
        self.assertIn("[TABLEAU 1]", prompt)
        self.assertIn("{{TABLE:1}}", prompt)


class TestNonRegression(BaseFixtureTest):
    def test_document_sans_media_inchange(self):
        chunks, assets, warnings = self.parse("fixture_plain.docx")
        self.assertEqual(assets, {})
        self.assertEqual(warnings, [])
        self.assertTrue(all(b["type"] == "text" for c in chunks for b in c["blocks"]))
        decks = [c["deck"] for c in chunks]
        self.assertTrue(any("Sous-section" in d for d in decks))

    def test_hierarchie_de_deck(self):
        chunks, _, _ = self.parse("fixture_plain.docx")
        deck = chunks[-1]["deck"]
        self.assertTrue(deck.startswith("*TEST*::"))
        self.assertIn("::", deck.replace("*TEST*::", ""))


class TestMediaStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-store-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_format_illisible_signale_sans_planter(self):
        store = MediaStore("projet", self.tmp)
        asset = store.add(FakeImage(b"pas vraiment un emf", "emf", "a" * 40))
        self.assertTrue(asset["missing"])
        self.assertIsNone(asset["file"])
        self.assertEqual(len(store.warnings), 1)

    def test_alt_recupere_a_la_seconde_occurrence(self):
        """Une image sans alt puis la même avec alt : la description est conservée."""
        store = MediaStore("projet", self.tmp)
        first = store.add(FakeImage(b"binaire png", "png", "b" * 40))
        second = store.add(FakeImage(b"binaire png", "png", "b" * 40), alt="Un schéma")
        self.assertIs(first, second)
        self.assertEqual(second["alt"], "Un schéma")
        self.assertEqual(second["occurrences"], 2)
        self.assertEqual(len(store.assets), 1)


class TestTsvParsing(unittest.TestCase):
    def test_decoupe_sur_tabulation_et_preserve_les_virgules(self):
        raw = 'Question ?\t<span style="color: red, bold">Réponse, avec virgules</span>'
        cards = parse_tsv_response(raw)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0][0], "Question ?")
        self.assertIn("Réponse, avec virgules", cards[0][1])

    def test_repli_sur_la_virgule_sans_tabulation(self):
        cards = parse_tsv_response("Question ?,Réponse")
        self.assertEqual(cards, [("Question ?", "Réponse")])

    def test_ignore_les_blocs_markdown_et_directives(self):
        raw = "```csv\n#separator:tab\nQ1\tR1\n\nQ2\tR2\n```"
        self.assertEqual(parse_tsv_response(raw), [("Q1", "R1"), ("Q2", "R2")])

    def test_troisieme_colonne_neutralisee(self):
        cards = parse_tsv_response("Q\tR\textra")
        self.assertEqual(cards, [("Q", "R extra")])


class TestPlaceholders(unittest.TestCase):
    def setUp(self):
        self.assets = {
            "img_1": {"id": "img_1", "file": "ag_p_abc.png", "alt": "Une courbe"},
        }
        self.chunk = {
            "blocks": [
                {"type": "image", "asset": "img_1", "n": 1},
                {
                    "type": "table", "n": 1, "n_cols": 1, "assets": [],
                    "rows": [[{"text": "x", "html": "x", "colspan": 1, "rowspan": 1,
                               "header": False, "assets": [], "tables": [], "col": 0}]],
                },
            ]
        }

    def test_substitution_image_et_tableau(self):
        text, used, unknown = resolve_placeholders(
            "Voir {{IMG:1}} et {{TABLE:1}}", self.chunk, self.assets
        )
        self.assertIn('<img src="ag_p_abc.png"', text)
        self.assertIn("<table", text)
        self.assertEqual(used, {"img_1"})
        self.assertEqual(unknown, [])

    def test_tolerance_de_syntaxe(self):
        text, _, unknown = resolve_placeholders("{{ img 1 }}", self.chunk, self.assets)
        self.assertIn("<img", text)
        self.assertEqual(unknown, [])

    def test_placeholder_invente_est_supprime_et_signale(self):
        text, _, unknown = resolve_placeholders("A {{IMG:9}} B", self.chunk, self.assets)
        self.assertEqual(text.strip(), "A  B".strip())
        self.assertEqual(unknown, ["{{IMG:9}}"])

    def test_prefixe_media_pour_l_apercu(self):
        text, _, _ = resolve_placeholders(
            "{{IMG:1}}", self.chunk, self.assets, media_prefix="/media/p"
        )
        self.assertIn('src="/media/p/ag_p_abc.png"', text)


class TestProjectStore(unittest.TestCase):
    def v1_project(self):
        return [
            {"id": 0, "deck": "*ESH*::Chap", "prompt": "Un paragraphe.",
             "system": "s", "status": "done", "response": "Q\tR"},
        ]

    def test_migration_v1_vers_v2(self):
        project = normalize(self.v1_project())
        self.assertEqual(project["version"], 2)
        self.assertEqual(project["assets"], {})
        self.assertEqual(project["prompts"][0]["blocks"],
                         [{"type": "text", "text": "Un paragraphe."}])

    def test_migration_idempotente(self):
        once = normalize(self.v1_project())
        twice = normalize(once)
        self.assertEqual(once, twice)

    def test_export_v1_fonctionne_toujours(self):
        rows, report = export_rows(normalize(self.v1_project()))
        self.assertEqual(rows, [["*ESH*::Chap", "Q", "R"]])
        self.assertEqual(report["media"], [])

    def test_export_resout_les_placeholders_et_liste_les_medias(self):
        project = {
            "version": 2,
            "assets": {"img_1": {"id": "img_1", "file": "ag_p_abc.png", "alt": "c"}},
            "prompts": [{
                "id": 0, "deck": "D", "status": "done",
                "blocks": [{"type": "image", "asset": "img_1", "n": 1}],
                "assets": ["img_1"],
                "response": "Que montre le graphique ?\tCeci : {{IMG:1}}",
            }],
        }
        rows, report = export_rows(normalize(project))
        self.assertIn('<img src="ag_p_abc.png"', rows[0][2])
        self.assertEqual(report["media"], ["ag_p_abc.png"])
        self.assertEqual(report["unused_assets"], [])

    def test_image_non_utilisee_est_signalee(self):
        project = normalize({
            "version": 2,
            "assets": {"img_1": {"id": "img_1", "file": "f.png", "alt": ""}},
            "prompts": [{
                "id": 0, "deck": "D", "status": "done",
                "blocks": [{"type": "image", "asset": "img_1", "n": 1}],
                "assets": ["img_1"], "response": "Q\tR sans image",
            }],
        })
        _, report = export_rows(project)
        self.assertEqual(report["unused_assets"], ["img_1"])

    def test_edition_alt_rerend_le_prompt(self):
        project = normalize({
            "version": 2,
            "assets": {"img_1": {"id": "img_1", "file": "f.png", "alt": ""}},
            "prompts": [{
                "id": 0, "deck": "D", "status": "pending",
                "blocks": [{"type": "text", "text": "Texte."},
                           {"type": "image", "asset": "img_1", "n": 1}],
                "assets": ["img_1"], "response": "",
                "prompt": render_prompt_text(
                    [{"type": "text", "text": "Texte."},
                     {"type": "image", "asset": "img_1", "n": 1}],
                    {"img_1": {"id": "img_1", "file": "f.png", "alt": ""}},
                ),
            }],
        })
        self.assertIn("aucune description", project["prompts"][0]["prompt"])
        touched = set_asset_alt(project, "img_1", "Graphique du chômage")
        self.assertEqual(touched, [0])
        self.assertIn("Graphique du chômage", project["prompts"][0]["prompt"])
        self.assertEqual(project["assets"]["img_1"]["alt_source"], "manual")


if __name__ == "__main__":
    unittest.main(verbosity=2)
