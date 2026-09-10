#!/usr/bin/env python3
"""
tests/make_fixtures.py — Génère les .docx de test.

Couvre les cas qui cassaient (ou risquent de casser) l'extraction :
image avec alt text, image sans alt, image seule dans un paragraphe vide,
image répétée (dédoublonnage), image dans une cellule, tableau avec fusions
horizontales ET verticales, tableau imbriqué, tableau collé à un titre.

Usage : python tests/make_fixtures.py [dossier_de_sortie]
"""

import sys
from pathlib import Path

from docx import Document
from docx.shared import Cm

NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def png_bytes(color=(30, 90, 200), size=(40, 30)) -> bytes:
    """Petit PNG généré à la volée (évite de versionner des binaires)."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def set_alt_text(run, description: str) -> None:
    """Écrit le texte alternatif là où Word et Google Docs le lisent : docPr/@descr."""
    for doc_pr in run._r.findall(".//{%s}docPr" % NS_WP):
        doc_pr.set("descr", description)
        doc_pr.set("title", description[:60])


def add_picture(doc_or_cell, blob: bytes, alt: str = None, width_cm: float = 4.0):
    import io

    para = doc_or_cell.add_paragraph()
    run = para.add_run()
    run.add_picture(io.BytesIO(blob), width=Cm(width_cm))
    if alt:
        set_alt_text(run, alt)
    return para


def build_images_docx(path: Path) -> None:
    doc = Document()
    blue, red = png_bytes(), png_bytes((200, 40, 40))

    doc.add_paragraph("CH1: Test des images", style="Heading 1")

    doc.add_paragraph("I - Images", style="Heading 2")
    doc.add_paragraph("Paragraphe d'introduction de la section images.")
    # 1. image avec alt text, dans un paragraphe SANS texte (cas qui sautait)
    add_picture(doc, blue, alt="Courbe du PIB par habitant en Angleterre, 1500-1900")
    # 2. image sans alt text
    add_picture(doc, red)

    doc.add_paragraph("II - Répétition", style="Heading 2")
    doc.add_paragraph("La même image revient ici : un seul fichier doit être écrit.")
    add_picture(doc, blue, alt="Courbe du PIB par habitant en Angleterre, 1500-1900")

    doc.save(path)


def build_tables_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("CH2: Test des tableaux", style="Heading 1")

    # Tableau collé au titre (aucun paragraphe de texte entre les deux)
    doc.add_paragraph("I - Fusions", style="Heading 2")
    t = doc.add_table(rows=3, cols=3)
    t.style = "Table Grid"
    for i, label in enumerate(("Phase", "Période", "Taux")):
        t.cell(0, i).paragraphs[0].add_run(label).bold = True
    t.cell(1, 0).text = "Décollage"
    t.cell(1, 1).text = "1780-1830"
    t.cell(1, 2).text = "1,5 %"
    t.cell(2, 1).text = "1830-1870"
    t.cell(2, 2).text = "2,1 %"
    # fusion verticale colonne 0 (lignes 1-2) et horizontale sur la ligne 0
    t.cell(1, 0).merge(t.cell(2, 0))

    doc.add_paragraph("II - En-tête fusionné", style="Heading 2")
    t2 = doc.add_table(rows=2, cols=3)
    t2.style = "Table Grid"
    t2.cell(0, 0).paragraphs[0].add_run("Indicateurs").bold = True
    t2.cell(0, 0).merge(t2.cell(0, 1))
    t2.cell(0, 2).paragraphs[0].add_run("Source").bold = True
    t2.cell(1, 0).text = "PIB"
    t2.cell(1, 1).text = "+2 %"
    t2.cell(1, 2).text = "Maddison"

    doc.add_paragraph("III - Imbrication et image", style="Heading 2")
    doc.add_paragraph("Texte avant le tableau imbriqué.")
    t3 = doc.add_table(rows=1, cols=2)
    t3.style = "Table Grid"
    t3.cell(0, 0).text = "Cellule avec un tableau :"
    inner = t3.cell(0, 0).add_table(rows=1, cols=2)
    inner.cell(0, 0).text = "a"
    inner.cell(0, 1).text = "b"
    add_picture(t3.cell(0, 1), png_bytes((20, 160, 80)), alt="Schéma dans une cellule", width_cm=2)

    doc.save(path)


def build_plain_docx(path: Path) -> None:
    """Document sans média : garantit la non-régression du comportement d'origine."""
    doc = Document()
    doc.add_paragraph("CH3: Test sans média", style="Heading 1")
    doc.add_paragraph("I - Section", style="Heading 2")
    doc.add_paragraph("Premier paragraphe.")
    doc.add_paragraph("Second paragraphe.")
    doc.add_paragraph("A) Sous-section", style="Heading 3")
    doc.add_paragraph("Contenu de la sous-section.")
    doc.save(path)


BUILDERS = {
    "fixture_images.docx": build_images_docx,
    "fixture_tables.docx": build_tables_docx,
    "fixture_plain.docx": build_plain_docx,
}


def build_all(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    made = {}
    for name, builder in BUILDERS.items():
        path = out_dir / name
        builder(path)
        made[name] = path
    return made


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "fixtures"
    for name, path in build_all(target).items():
        print(f"✓ {path}")
