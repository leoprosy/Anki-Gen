#!/usr/bin/env python3
"""
parse_cours.py — Étape 1 du pipeline Ankigen
Lit un .docx, détecte la hiérarchie du plan (styles Titre), découpe en chunks par
section, extrait les images (+ leur texte alternatif) et les tableaux, et génère
le projet JSON prêt à être travaillé dans l'app.

Usage:
    python parse_cours.py <fichier.docx> [--output prompts.json] [--deck-prefix "ESH"]
"""

import argparse
import json
import re
import sys
from pathlib import Path

from docx import Document

from docx_blocks import STYLE_LEVELS, iter_blocks
from media_store import MediaStore
from render import render_prompt_text

# Patterns de numérotation : I. / II. → niveau 1, A) / B) → 2, 1) / 2) → 3, a) → 4
# (conservés pour l'affichage/diagnostic : la détection réelle se fait sur les styles)
NUMBERING_PATTERNS = [
    (re.compile(r"^\s*[IVX]+[\.\)]\s+\S"), 1),
    (re.compile(r"^\s*[A-Z][\.\)]\s+\S"), 2),
    (re.compile(r"^\s*\d+[\.\)]\s+\S"), 3),
    (re.compile(r"^\s*[a-z][\.\)]\s+\S"), 4),
]


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def build_deck_path(stack, prefix):
    """
    Chemin de deck Anki depuis la pile hiérarchique.

    Le préfixe est optionnel depuis l'ouverture au public. On filtre les segments
    vides au lieu de les joindre : `"::".join(["", "Chapitre"])` donnerait
    « ::Chapitre », que Anki refuse.
    """
    segments = [(prefix or "").strip()] + [title for _, title in stack]
    return "::".join(segment for segment in segments if segment)


def split_chapter_title(stem: str):
    """
    'CH8_ La croissance économique' → ('CH8', 'La croissance économique').
    Tolère l'absence du séparateur '_ '.
    """
    if "_ " in stem:
        chap, title = stem.split("_ ", 1)
        return chap.strip(), title.strip()
    return "", stem.strip()


def number_blocks(blocks: list) -> list:
    """
    Numérote images et tableaux LOCALEMENT au chunk ({{IMG:1}}, {{TABLE:1}}…).
    Le modèle n'a ainsi jamais à manipuler de nom de fichier.
    """
    img_n = table_n = 0
    for block in blocks:
        if block.get("type") == "image":
            img_n += 1
            block["n"] = img_n
        elif block.get("type") == "table":
            table_n += 1
            block["n"] = table_n
    return blocks


# ──────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────
def parse_docx(path: Path, deck_prefix: str, project_id: str = None,
               media_dir: Path = None, title_stem: str = None):
    """
    Parse le .docx et retourne (chunks, assets, warnings).

    chunks : [{"deck": str, "blocks": [...], "assets": [...], "prompt": str}, ...]
    assets : {"img_1": {...}, ...}  (métadonnées des images extraites)

    `title_stem` sert à nommer chapitre et titre dans les decks : le fichier est
    stocké sous un nom assaini, mais les decks doivent garder les accents.
    """
    path = Path(path)
    project_id = project_id or path.stem
    if media_dir is None:
        from paths import project_media_dir
        media_dir = project_media_dir(project_id)

    chap, _ = split_chapter_title(title_stem or path.stem)
    doc = Document(path)
    store = MediaStore(project_id, media_dir)

    chunks = []
    stack = []              # [(level, titre), ...]
    current_blocks = []
    current_deck = deck_prefix

    def flush(deck):
        nonlocal current_blocks
        blocks = number_blocks(current_blocks)
        has_content = any(
            (b["type"] == "text" and b.get("text"))
            or b["type"] in ("image", "table")
            for b in blocks
        )
        # `stack` vide = on n'est pas encore entré dans une section : c'est le
        # contenu antérieur au premier titre (ligne de titre, intro), qu'on
        # ignore. L'ancienne condition `deck != deck_prefix` disait la même chose
        # de façon détournée, et devenait fausse avec un préfixe vide.
        if has_content and stack:
            prompt = render_prompt_text(blocks, store.assets)
            chunks.append({
                "deck": deck,
                "blocks": blocks,
                "assets": sorted({b["asset"] for b in blocks if b["type"] == "image"}
                                 | {a for b in blocks if b["type"] == "table"
                                    for a in b.get("assets", [])}),
                "prompt": prompt,
            })
        current_blocks = []

    for block in iter_blocks(doc, store):
        if block["type"] == "heading":
            level, clean_text = block["level"], block["text"]
            # On flush le chunk en cours avant de changer de section
            flush(current_deck)

            # Met à jour la pile : retire tout ce qui est ≥ ce niveau
            stack = [(l, t) for l, t in stack if l < level]
            if level == 1:
                clean_text = "%s::%s" % (chap, clean_text) if chap else clean_text
            stack.append((level, clean_text))
            current_deck = build_deck_path(stack, deck_prefix)
        else:
            current_blocks.append(block)

    flush(current_deck)
    return chunks, store.assets, store.warnings


def build_prompts(chunks, assets=None):
    """Génère la liste de prompts à partir des chunks."""
    assets = assets or {}
    prompts = []
    for i, chunk in enumerate(chunks):
        prompts.append({
            "id": i,
            "deck": chunk["deck"],
            "prompt": chunk.get("prompt") or render_prompt_text(chunk.get("blocks", []), assets),
            "blocks": chunk.get("blocks", []),
            "assets": chunk.get("assets", []),
            "status": "pending",   # pending | done
            "response": ""
        })
    return prompts


# ──────────────────────────────────────────────
# Affichage CLI
# ──────────────────────────────────────────────
def chunk_stats(chunks):
    """(images, tableaux) — les images logées dans une cellule comptent aussi."""
    images = len({a for c in chunks for a in c.get("assets", [])})
    tables = sum(1 for c in chunks for b in c["blocks"] if b["type"] == "table")
    return images, tables


def print_structure(chunks):
    """Affiche la structure hiérarchique du cours sous forme d'arbre indenté."""
    if not chunks:
        print("(aucun chunk détecté)")
        return

    deck_counts = {}
    for chunk in chunks:
        deck_counts[chunk["deck"]] = deck_counts.get(chunk["deck"], 0) + 1

    printed = set()
    print("\n🗂️  Structure du cours :")
    for deck in deck_counts:
        parts = deck.split("::")
        for depth, _ in enumerate(parts):
            node = "::".join(parts[: depth + 1])
            if node in printed:
                continue
            printed.add(node)
            indent = "   " * depth
            is_leaf = (depth == len(parts) - 1)
            count_str = f"  ({deck_counts[deck]} chunk(s))" if is_leaf else ""
            prefix = "└─ " if depth > 0 else "📘 "
            print(f"{indent}{prefix}{parts[depth]}{count_str}")


def force_utf8_stdout():
    """La console Windows est en cp1252 : sans ça, les emoji font planter les prints."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Parse un cours .docx → prompts Anki JSON")
    parser.add_argument("docx", help="Chemin vers le fichier .docx")
    parser.add_argument("--output", default="prompts.json", help="Fichier JSON de sortie")
    parser.add_argument("--deck-prefix", default="",
                        help="Préfixe de deck Anki (vide par défaut)")
    parser.add_argument("--media-dir", default=None,
                        help="Dossier de sortie des images (défaut: media/<nom du cours>)")
    parser.add_argument(
        "--structure",
        action="store_true",
        help="Affiche uniquement la structure hiérarchique du cours sans générer de fichier JSON",
    )
    args = parser.parse_args()

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"❌ Fichier introuvable : {docx_path}", file=sys.stderr)
        sys.exit(1)

    media_dir = Path(args.media_dir) if args.media_dir else None
    print(f"📖 Lecture de {docx_path.name} ...")
    chunks, assets, warnings = parse_docx(docx_path, args.deck_prefix, media_dir=media_dir)
    images, tables = chunk_stats(chunks)
    print(f"✅ {len(chunks)} chunks détectés — {images} image(s), {tables} tableau(x)")
    for w in warnings:
        print(f"⚠️  {w}")

    if args.structure:
        print_structure(chunks)
        return

    prompts = build_prompts(chunks, assets)
    project = {
        "version": 2,
        "deck_prefix": args.deck_prefix,
        "source": docx_path.name,
        "assets": assets,
        "prompts": prompts,
    }
    output_path = Path(args.output)
    output_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 {output_path} généré ({len(prompts)} prompts)")

    decks = {}
    for p in prompts:
        decks[p["deck"]] = decks.get(p["deck"], 0) + 1
    print("\n📚 Répartition par deck :")
    for deck, count in decks.items():
        print(f"   {deck} → {count} chunk(s)")


if __name__ == "__main__":
    main()
