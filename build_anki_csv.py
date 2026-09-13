#!/usr/bin/env python3
"""
build_anki_csv.py — Étape 3 du pipeline Anki ESH
Lit un projet (prompts + réponses) et génère le TSV final importable dans Anki.

Usage:
    python build_anki_csv.py --prompts projects/mon_cours.json --output anki_export.tsv
    python build_anki_csv.py --prompts projects/mon_cours.json --output anki_export.tsv --media-out ./media_export

Format de sortie (import Anki) :
    #separator:tab / #html:true / #deck column:1
    Colonne 1 : Deck (ex: ESH::I - Croissance::A) Modèles)
    Colonne 2 : Recto (question HTML)
    Colonne 3 : Verso (réponse HTML)
    Encodage   : UTF-8
"""

import argparse
import csv
import sys
from pathlib import Path

# En-tête Anki. `#html:true` est indispensable : sans lui, Anki affiche les
# balises <img> et <table> comme du texte brut au lieu de les interpréter.
ANKI_HEADER_LINES = [
    "#separator:tab",
    "#html:true",
    "#deck column:1",
]


def parse_tsv_response(raw_response: str):
    """
    Parse la réponse brute de Claude : une carte par ligne, QUESTION<TAB>RÉPONSE.
    Retourne une liste de (question, réponse).

    Tolérances :
      * lignes vides, clôtures markdown (```) et lignes de directive (#) ignorées ;
      * repli sur la virgule UNIQUEMENT si la ligne ne contient aucune tabulation
        (compatibilité avec les anciennes réponses) ;
      * guillemets encadrant un champ entier retirés.

    Le découpage se fait sur la tabulation et non sur la virgule : du HTML de
    carte contient presque toujours des virgules (styles CSS, énumérations).
    """
    cards = []
    for line in (raw_response or "").strip().splitlines():
        line = line.strip()
        if not line or line.startswith("```") or line.startswith("#"):
            continue

        if "\t" in line:
            question, answer = line.split("\t", 1)
            # Une 3e colonne éventuelle reste dans la réponse : on neutralise les tabs
            answer = answer.replace("\t", " ")
        elif "," in line:
            question, answer = line.split(",", 1)
        else:
            continue

        question, answer = _unquote(question), _unquote(answer)
        if question and answer:
            cards.append((question, answer))
    return cards


def _unquote(field: str) -> str:
    field = (field or "").strip()
    if len(field) >= 2 and field[0] == field[-1] == '"':
        field = field[1:-1].strip()
    return field


def write_rows(path: Path, rows, header: bool = True) -> int:
    """Écrit les lignes (deck, recto, verso) dans un TSV importable par Anki."""
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        if header:
            for line in ANKI_HEADER_LINES:
                f.write(line + "\n")
        for row in rows:
            writer.writerow(row)
    return len(rows)


def main():
    from parse_cours import force_utf8_stdout
    from project_store import export_rows, load_project_file

    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Assemble le TSV Anki depuis un projet JSON")
    parser.add_argument("--prompts", default="prompts.json", help="Fichier JSON du projet")
    parser.add_argument("--output", default="anki_export.tsv", help="Fichier TSV de sortie")
    parser.add_argument("--only-done", action="store_true",
                        help="N'inclure que les prompts avec status=done (ignore les pending)")
    parser.add_argument("--media-dir", default=None,
                        help="Dossier contenant les images extraites (défaut: media/<nom du projet>)")
    parser.add_argument("--media-out", default=None,
                        help="Copie les images réellement utilisées dans ce dossier")
    args = parser.parse_args()

    prompts_path = Path(args.prompts)
    if not prompts_path.exists():
        print(f"❌ Fichier introuvable : {prompts_path}", file=sys.stderr)
        sys.exit(1)

    project = load_project_file(prompts_path)
    rows, report = export_rows(project, only_done=args.only_done)
    total = write_rows(Path(args.output), rows)

    print(f"✅ {total} cartes exportées → {args.output}")
    if report["skipped"]:
        print(f"⚠️  {report['skipped']} chunks ignorés (réponse vide ou status pending)")
    if report["unknown_placeholders"]:
        print(f"⚠️  {len(report['unknown_placeholders'])} placeholder(s) inconnu(s) supprimé(s) : "
              + ", ".join(report["unknown_placeholders"][:5]))
    if report["media"]:
        print(f"🖼️  {len(report['media'])} image(s) utilisée(s)")

    if args.media_out and report["media"]:
        import shutil

        media_dir = Path(args.media_dir) if args.media_dir else None
        if media_dir is None:
            from paths import MEDIA_DIR
            media_dir = MEDIA_DIR / prompts_path.stem
        out = Path(args.media_out)
        out.mkdir(parents=True, exist_ok=True)
        copied = 0
        for filename in sorted(report["media"]):
            src = media_dir / filename
            if src.exists():
                shutil.copy2(src, out / filename)
                copied += 1
            else:
                print(f"⚠️  image manquante : {src}")
        print(f"📁 {copied} image(s) copiée(s) → {out}")


if __name__ == "__main__":
    main()
