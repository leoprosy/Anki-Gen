#!/usr/bin/env python3
"""
docx_blocks.py — Extraction structurée d'un .docx en « blocs ».

Contrairement à un simple parcours de `doc.paragraphs`, on itère le corps du
document dans l'ordre réel (`Document.iter_inner_content()`), ce qui permet de
récupérer AUSSI les tableaux et les images — y compris les images portées par un
paragraphe sans texte, qui étaient silencieusement perdues.

Blocs produits :
  {"type": "heading", "level": 1..4, "text": str}
  {"type": "text",    "text": str}
  {"type": "image",   "asset": "img_3"}
  {"type": "table",   "n_cols": int, "rows": [[cell, ...], ...], "assets": [...]}

Une cellule :
  {"text": str, "html": str, "colspan": int, "rowspan": int,
   "header": bool, "assets": [...], "tables": [table_block, ...]}
"""

import re

from docx import Document
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from render import runs_to_html

# ── Namespaces OOXML ──────────────────────────────────────────
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "v": "urn:schemas-microsoft-com:vml",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
R_EMBED = "{%s}embed" % NS["r"]
R_ID = "{%s}id" % NS["r"]
W_VAL = "{%s}val" % NS["w"]
W_DRAWING = "{%s}drawing" % NS["w"]
W_PICT = "{%s}pict" % NS["w"]
MC_FALLBACK = "{%s}Fallback" % NS["mc"]
EMU_PER_CM = 360000

MAX_TABLE_DEPTH = 2

# Styles de titre (Word FR/EN + export Google Docs)
STYLE_LEVELS = {
    "heading 1": 1,
    "heading 2": 2,
    "heading 3": 3,
    "heading 4": 4,
    "titre 1": 1,
    "titre 2": 2,
    "titre 3": 3,
    "titre 4": 4,
}

# Champs Word (TOC, index…) à ne pas confondre avec du contenu de cours
FIELD_NOISE = re.compile(r"^\s*(TOC|PAGEREF|HYPERLINK)\s", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────
# Titres
# ──────────────────────────────────────────────────────────────
def heading_level(para: Paragraph) -> int:
    style = (para.style.name or "").lower() if para.style else ""
    return STYLE_LEVELS.get(style, 0)


# ──────────────────────────────────────────────────────────────
# Images
# ──────────────────────────────────────────────────────────────
def _in_fallback(el) -> bool:
    """True si l'élément est dans un <mc:Fallback> (doublon VML d'un drawing)."""
    parent = el.getparent()
    while parent is not None:
        if parent.tag == MC_FALLBACK:
            return True
        parent = parent.getparent()
    return False


def _alt_from_drawing(drawing) -> str:
    """
    Texte alternatif d'un <w:drawing>, par ordre de priorité :
    wp:docPr/@descr → wp:docPr/@title → pic:cNvPr/@descr
    (Word et Google Docs n'écrivent pas l'alt text au même endroit).
    """
    for doc_pr in drawing.findall(".//wp:docPr", NS):
        for attr in ("descr", "title"):
            val = (doc_pr.get(attr) or "").strip()
            if val:
                return val
    for cnv in drawing.findall(".//pic:cNvPr", NS):
        val = (cnv.get("descr") or "").strip()
        if val:
            return val
    return ""


def _width_cm_from_drawing(drawing):
    for extent in drawing.findall(".//wp:extent", NS):
        cx = extent.get("cx")
        if cx:
            try:
                return round(int(cx) / EMU_PER_CM, 2)
            except ValueError:
                return None
    return None


def _image_part(doc_part, rid):
    """Retourne la part image liée, ou None (image liée en externe, rel cassée…)."""
    if not rid:
        return None
    try:
        return doc_part.related_parts[rid]
    except KeyError:
        return None


def extract_images(para: Paragraph, doc_part, store) -> list:
    """
    Images d'un paragraphe, dans l'ordre du document.
    Couvre <w:drawing> (wp:inline ET wp:anchor) et le VML hérité <w:pict>.
    """
    assets = []
    for el in para._p.iter():
        if el.tag == W_DRAWING:
            if _in_fallback(el):
                continue
            blips = el.findall(".//a:blip", NS)
            if not blips:
                continue
            part = _image_part(doc_part, blips[0].get(R_EMBED))
            if part is None:
                continue
            assets.append(
                store.add(
                    part.image,
                    alt=_alt_from_drawing(el),
                    width_cm=_width_cm_from_drawing(el),
                )
            )
        elif el.tag == W_PICT:
            if _in_fallback(el):
                continue
            data = el.findall(".//v:imagedata", NS)
            if not data:
                continue
            part = _image_part(doc_part, data[0].get(R_ID))
            if part is None:
                continue
            alt = ""
            for shape in el.findall(".//v:shape", NS):
                alt = (shape.get("alt") or "").strip()
                if alt:
                    break
            assets.append(store.add(part.image, alt=alt))
    return assets


# ──────────────────────────────────────────────────────────────
# Tableaux
# ──────────────────────────────────────────────────────────────
def _tc_grid_span(tc) -> int:
    for span in tc.findall("./w:tcPr/w:gridSpan", NS):
        try:
            return max(1, int(span.get(W_VAL)))
        except (TypeError, ValueError):
            return 1
    return 1


def _tc_vmerge(tc):
    """None (pas de fusion verticale) | 'restart' | 'continue'."""
    for vm in tc.findall("./w:tcPr/w:vMerge", NS):
        val = (vm.get(W_VAL) or "continue").lower()
        return "restart" if val in ("restart", "1", "true") else "continue"
    return None


def _row_is_header(tr) -> bool:
    return bool(tr.findall("./w:trPr/w:tblHeader", NS))


def _all_runs_bold(tc) -> bool:
    """True si toute cellule non vide de la ligne est intégralement en gras."""
    cell = _Cell(tc, None)
    runs = [r for p in cell.paragraphs for r in p.runs if r.text.strip()]
    if not runs:
        return True  # cellule vide : neutre
    return all(bool(r.bold) for r in runs)


def _cell_content(tc, doc_part, store, depth: int) -> dict:
    """Contenu d'une cellule : texte brut, HTML inline, images, tableaux imbriqués."""
    cell = _Cell(tc, None)
    texts, htmls, assets, nested = [], [], [], []

    for item in cell.iter_inner_content():
        if isinstance(item, Paragraph):
            imgs = extract_images(item, doc_part, store)
            assets.extend(a["id"] for a in imgs)
            txt = item.text.strip()
            html = runs_to_html(item)
            for a in imgs:
                if a.get("file"):
                    html = (html + "<br>" if html else "") + '<img src="%s">' % a["file"]
                # Marqueur résolu au rendu (render_table_text) : la description
                # d'une image de cellule doit suivre son texte alternatif, y compris
                # quand celui-ci est modifié après le parsing.
                marker = "{{CELLIMG:%s}}" % a["id"]
                txt = (txt + " " + marker).strip() if txt else marker
            if txt:
                texts.append(txt)
            if html:
                htmls.append(html)
        elif isinstance(item, Table):
            if depth + 1 <= MAX_TABLE_DEPTH:
                sub = extract_table(item, doc_part, store, depth=depth + 1)
                nested.append(sub)
                assets.extend(sub["assets"])
            else:
                # trop profond : on aplatit en texte
                texts.append(" / ".join(c.text for r in item.rows for c in r.cells))

    return {
        "text": "\n".join(texts),
        "html": "<br>".join(h for h in htmls if h),
        "colspan": 1,
        "rowspan": 1,
        "header": False,
        "assets": assets,
        "tables": nested,
    }


def extract_table(table: Table, doc_part, store, depth: int = 1) -> dict:
    """
    Construit la grille d'un tableau en résolvant les fusions.

    Les cellules fusionnées horizontalement portent `gridSpan` ; celles fusionnées
    verticalement existent dans chaque ligne avec `vMerge` sans 'restart' : on les
    absorbe en incrémentant le `rowspan` de la cellule d'origine.
    """
    rows_out = []
    origin_by_col = {}   # colonne -> cellule d'origine d'une fusion verticale
    n_cols = 0
    assets = []

    for tr in table._tbl.tr_lst:
        header = _row_is_header(tr)
        col = 0
        row_cells = []
        for tc in tr.tc_lst:
            span = _tc_grid_span(tc)
            vmerge = _tc_vmerge(tc)

            if vmerge == "continue":
                origin = origin_by_col.get(col)
                if origin is not None:
                    origin["rowspan"] += 1
                    extra = _cell_content(tc, doc_part, store, depth)
                    # du contenu dans une cellule de continuation : on le rattache
                    if extra["text"]:
                        origin["text"] = (origin["text"] + "\n" + extra["text"]).strip()
                        origin["html"] = (
                            origin["html"] + "<br>" + extra["html"]
                        ).strip()
                        origin["assets"].extend(extra["assets"])
                        assets.extend(extra["assets"])
                col += span
                continue

            cell = _cell_content(tc, doc_part, store, depth)
            cell["colspan"] = span
            cell["header"] = header
            cell["col"] = col
            row_cells.append(cell)
            assets.extend(cell["assets"])

            if vmerge == "restart":
                origin_by_col[col] = cell
            else:
                origin_by_col.pop(col, None)
            col += span

        n_cols = max(n_cols, col)
        rows_out.append(row_cells)

    # Heuristique : première ligne entièrement en gras → ligne d'en-tête
    if rows_out and not any(c["header"] for r in rows_out for c in r):
        first_tr = table._tbl.tr_lst[0]
        if first_tr.tc_lst and all(_all_runs_bold(tc) for tc in first_tr.tc_lst):
            if any(c["text"] for c in rows_out[0]):
                for c in rows_out[0]:
                    c["header"] = True

    return {
        "type": "table",
        "depth": depth,
        "n_cols": n_cols or (len(rows_out[0]) if rows_out else 0),
        "rows": rows_out,
        "assets": sorted(set(assets)),
    }


# ──────────────────────────────────────────────────────────────
# Parcours du document
# ──────────────────────────────────────────────────────────────
def iter_blocks(doc: Document, store):
    """
    Génère les blocs du corps du document, dans l'ordre.
    `Document.iter_inner_content()` ignore les <w:sdt> (table des matières
    générée), ce qui nous évite de réimporter le sommaire comme du cours.
    """
    doc_part = doc.part
    for item in doc.iter_inner_content():
        if isinstance(item, Paragraph):
            images = extract_images(item, doc_part, store)
            text = item.text.strip()
            level = heading_level(item)

            if level > 0 and text:
                yield {"type": "heading", "level": level, "text": text}
                # une image collée dans un titre reste rattachée au corps suivant
                for a in images:
                    yield {"type": "image", "asset": a["id"]}
                continue

            if text and not FIELD_NOISE.match(text):
                yield {"type": "text", "text": text}
            for a in images:
                yield {"type": "image", "asset": a["id"]}

        elif isinstance(item, Table):
            table = extract_table(item, doc_part, store)
            if table["rows"]:
                yield table
