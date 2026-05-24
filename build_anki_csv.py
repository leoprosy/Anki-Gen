#!/usr/bin/env python3
"""
build_anki_csv.py — Étape 3 du pipeline Anki ESH
Lit prompts.json (avec les réponses remplies) et génère le CSV final Anki.

Usage:
    python build_anki_csv.py [--prompts prompts.json] [--output anki_export.tsv]

Format TSV de sortie (import Anki) :
    Colonne 1 : Deck (ex: ESH::I - Croissance::A) Modèles)
    Colonne 2 : Recto (question HTML)
    Colonne 3 : Verso (réponse HTML)
    Séparateur : tabulation
    Encodage   : UTF-8
"""

import json
import csv
import argparse
import sys
import re
from pathlib import Path


def parse_tsv_response(raw_response: str):
    """
    Parse la réponse brute de Claude (format TSV : QUESTION[TAB]RÉPONSE).
    Retourne une liste de (question, réponse).
    Ignore les lignes vides et les artefacts markdown.
    """
    cards = []
    lines = raw_response.strip().splitlines()
    for line in lines:
        line = line.strip()
        # Ignore lignes vides et blocs markdown
        if not line or line.startswith("```"):
            continue
        # Sépare sur la première tabulation
        parts = line.split("\t", 1)
        if len(parts) == 2:
            question, reponse = parts
            reponse = reponse.strip()
            if reponse.startswith('"') and reponse.endswith('"'):
                reponse = reponse[1:-1].strip()
            cards.append((question.strip(), reponse))
    return cards


def main():
    parser = argparse.ArgumentParser(
        description="Assemble le TSV Anki depuis prompts.json"
    )
    parser.add_argument(
        "--prompts", default="prompts.json", help="Fichier JSON des prompts/réponses"
    )
    parser.add_argument(
        "--output", default="anki_export.tsv", help="Fichier TSV de sortie"
    )
    parser.add_argument(
        "--only-done",
        action="store_true",
        help="N'inclure que les prompts avec status=done (ignore les pending)",
    )
    args = parser.parse_args()

    prompts_path = Path(args.prompts)
    if not prompts_path.exists():
        print(f"❌ Fichier introuvable : {prompts_path}", file=sys.stderr)
        sys.exit(1)

    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))

    output_path = Path(args.output)
    total_cards = 0
    skipped = 0

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL)

        # En-tête Anki (optionnel, commenté pour import direct)
        # writer.writerow(["#separator:tab"])
        # writer.writerow(["#html:true"])
        writer.writerow(["#deck column:1"])

        for prompt in prompts:
            status = prompt.get("status", "pending")
            deck = prompt.get("deck", "ESH")
            response = prompt.get("response", "").strip()

            if not response:
                skipped += 1
                continue

            if args.only_done and status != "done":
                skipped += 1
                continue

            cards = parse_tsv_response(response)
            for question, reponse in cards:
                writer.writerow([deck, question, reponse])
                total_cards += 1

    print(f"✅ {total_cards} cartes exportées → {output_path}")
    if skipped:
        print(f"⚠️  {skipped} chunks ignorés (réponse vide ou status pending)")


if __name__ == "__main__":
    main()
