#!/usr/bin/env python3
"""
parse_cours.py — Étape 1 du pipeline Anki ESH
Lit un .docx, détecte la hiérarchie du plan (I. / A) / 1) + styles Titre),
découpe en chunks par paragraphe, et génère prompts.json prêt à coller dans Claude.

Usage:
    python parse_cours.py <fichier.docx> [--output prompts.json] [--deck-prefix "ESH"]
"""

import re
import json
import argparse
import sys
from pathlib import Path
from docx import Document

# ──────────────────────────────────────────────
# Détection du niveau hiérarchique d'un paragraphe
# ──────────────────────────────────────────────

# Styles Google Docs / Word typiques
STYLE_LEVELS = {
    "title": 1,
    "heading 1": 2,
    "heading 2": 3,
    "heading 3": 4,
    "heading 4": 5,
    "titre 1": 2,
    "titre 2": 3,
    "titre 3": 4,
    "titre 4": 5,
}

# Patterns de numérotation : I. / II. → niveau 1, A) / B) → 2, 1) / 2) → 3, a) → 4
NUMBERING_PATTERNS = [
    (re.compile(r"^\s*[IVX]+[\.\)]\s+\S"), 1),        # I. ou I) …
    (re.compile(r"^\s*[A-Z][\.\)]\s+\S"), 2),          # A. ou A) …
    (re.compile(r"^\s*\d+[\.\)]\s+\S"), 3),            # 1. ou 1) …
    (re.compile(r"^\s*[a-z][\.\)]\s+\S"), 4),          # a. ou a) …
]

SYSTEM_PROMPT = """Tu es un expert en ESH (Économie, Sociologie et Histoire) pour les classes préparatoires ECG. Ta mission est de convertir chaque paragraphe de cours fourni par l'utilisateur en cartes Anki de manière exhaustive, précise et structurée.
** Règles de fonctionnement (Paragraphe par paragraphe) : **
- Génération immédiate : À chaque fois que l'utilisateur t'envoie un paragraphe, tu dois générer les cartes correspondantes directement. N'écris aucune phrase d'introduction, de confirmation ou de conclusion.
- Zéro déperdition : Absolument chaque information, mécanisme, chiffre et concept du paragraphe doit être transformé en carte.
- Traitement des œuvres/articles : Si le paragraphe mentionne un ouvrage ou un article, génère systématiquement une carte de cours classique, PLUS une carte dédiée spécifiquement à la mémorisation de son contenu. (Exemple de recto : Quelle est la thèse centrale de [Auteur] dans [Œuvre] ([Date]) ?).
- Format des cartes: Elles doivent être écrites et formatées en HTML brut entièrement.
** Règles de formatage (Style HTML obligatoire) : **
Tu dois impérativement utiliser les balises HTML et le CSS inline suivants pour formater le texte des cartes (en particulier le verso/réponse) :
Éléments textuels :
- Dates d'événements : <span style="color: red; font-weight: bold; text-decoration: underline;">Date</span>
- Citations : <span style="background-color: plum; font-style: italic;">"Citation"</span>
- Œuvres (titre + date + auteur) : <span style="background-color: yellow; font-style: italic;">Œuvre</span>
- Articles (titre + date + auteur) : <span style="background-color: yellow;">"Article"</span>
- Théorie principale : <span style="color: red; font-weight: bold;">Théorie</span>
- Énumérations: <ul> <li> Texte </li> autres balises li ... </ul>
Caractères spéciaux et mathématiques : Utiliser la syntaxe MathJax entre des balises latex (ex: [latex]$x = y$[/latex]).
** Règle de sortie: **
Ne rends que le résultat sous forme de texte csv, colonnes séparées par des tabulations.
Chaque ligne = une carte. Format : QUESTION[TAB]RÉPONSE
Aucune ligne d'intro, aucun commentaire, aucun bloc markdown."""


def detect_level(para):
    """Retourne (niveau:int, texte:str) pour un paragraphe, ou (0, texte) si corps."""
    style_name = para.style.name.lower() if para.style and para.style.name else ""
    text = para.text.strip()

    # 1. Style de titre explicite
    if style_name in STYLE_LEVELS:
        return STYLE_LEVELS[style_name], text

    return 0, text  # 0 = contenu normal


def build_deck_path(stack, prefix):
    """Construit le chemin de deck Anki depuis la pile hiérarchique."""
    parts = [prefix] + [t for _, t in stack]
    return "::".join(parts)


def parse_docx(path: Path, deck_prefix: str):
    """Parse le docx et retourne une liste de chunks avec leur deck path."""
    title = path.stem
    chap, title = title.split("_ ")
    doc = Document(path)
    chunks = []
    # stack = [(level, titre), ...]
    stack = []
    current_paragraphs = []
    current_deck = deck_prefix
    chapter_counter = 0

    def flush(deck):
        nonlocal current_paragraphs
        text = "\n".join(current_paragraphs).strip()
        if text:
            chunks.append({"deck": deck, "text": text})
        current_paragraphs = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        level, clean_text = detect_level(para)

        if level > 0:
            # On flush le chunk en cours avant de changer de section
            flush(current_deck)

            # Met à jour la pile : retire tout ce qui est ≥ ce niveau
            stack = [(l, t) for l, t in stack if l < level]
            if level == 1:
                chapter_counter += 1
                clean_text = f"{chap}: {title}::{clean_text}"
            stack.append((level, clean_text))
            current_deck = build_deck_path(stack, deck_prefix)
        else:
            current_paragraphs.append(text)

    # Dernier flush
    flush(current_deck)
    return chunks


def print_structure(chunks):
    """Affiche la structure hiérarchique du cours sous forme d'arbre indenté."""
    if not chunks:
        print("(aucun chunk détecté)")
        return

    # Collect deck paths with their chunk counts
    deck_counts: dict[str, int] = {}
    for chunk in chunks:
        deck_counts[chunk["deck"]] = deck_counts.get(chunk["deck"], 0) + 1

    # Track which nodes have already been printed to avoid duplicates
    printed: set[str] = set()

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


def build_prompts(chunks):
    """Génère la liste de prompts à partir des chunks."""
    prompts = []
    for i, chunk in enumerate(chunks):
        prompts.append({
            "id": i,
            "deck": chunk["deck"],
            "prompt": chunk["text"],
            "system": SYSTEM_PROMPT,
            "status": "pending",   # pending | done
            "response": ""
        })
    return prompts


def main():
    parser = argparse.ArgumentParser(description="Parse un cours .docx → prompts Anki JSON")
    parser.add_argument("docx", help="Chemin vers le fichier .docx")
    parser.add_argument("--output", default="prompts.json", help="Fichier JSON de sortie")
    parser.add_argument("--deck-prefix", default="*ESH*", help="Nom du deck racine Anki")
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

    print(f"📖 Lecture de {docx_path.name} ...")
    chunks = parse_docx(docx_path, args.deck_prefix)
    print(f"✅ {len(chunks)} chunks détectés")

    if args.structure:
        print_structure(chunks)
        return

    prompts = build_prompts(chunks)
    output_path = Path(args.output)
    output_path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 {output_path} généré ({len(prompts)} prompts)")

    # Résumé des decks
    decks = {}
    for p in prompts:
        decks[p["deck"]] = decks.get(p["deck"], 0) + 1
    print("\n📚 Répartition par deck :")
    for deck, count in decks.items():
        print(f"   {deck} → {count} chunk(s)")


if __name__ == "__main__":
    main()