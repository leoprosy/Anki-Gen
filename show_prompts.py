#!/usr/bin/env python3
"""
show_prompts.py — Outil de travail du pipeline Anki ESH
Affiche les prompts en attente de réponse Claude, un par un.
Permet de coller la réponse directement dans le terminal ou de lire depuis un fichier.

Usage:
    python show_prompts.py                  # Affiche le prochain prompt pending
    python show_prompts.py --all            # Affiche tous les prompts pending
    python show_prompts.py --stats          # Résumé de progression
    python show_prompts.py --fill <id>      # Remplit la réponse pour l'id donné
"""

import json
import argparse
import sys
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stats(prompts):
    total = len(prompts)
    done = sum(1 for p in prompts if p.get("status") == "done")
    pending = total - done
    print(f"\n📊 Progression : {done}/{total} chunks traités ({pending} restants)")
    if pending:
        next_p = next((p for p in prompts if p.get("status") != "done"), None)
        if next_p:
            print(f"   Prochain : #{next_p['id']} → {next_p['deck']}")
    print()


def show_prompt(p):
    print(f"\n{'═'*60}")
    print(f"  Chunk #{p['id']} / Deck : {p['deck']}")
    print(f"{'═'*60}")
    print("\n[SYSTEM PROMPT ESH — déjà injecté dans ton projet Claude]\n")
    print("─── PARAGRAPHE À ENVOYER ──────────────────────────────────")
    print(p["prompt"])
    print("────────────────────────────────────────────────────────────\n")


def fill_response(prompts_path, chunk_id, response_text):
    prompts = load(prompts_path)
    for p in prompts:
        if p["id"] == chunk_id:
            p["response"] = response_text
            p["status"] = "done"
            save(prompts_path, prompts)
            print(f"✅ Chunk #{chunk_id} marqué comme done.")
            return
    print(f"❌ Chunk #{chunk_id} introuvable.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", default="prompts.json")
    parser.add_argument("--all", action="store_true", help="Affiche tous les pending")
    parser.add_argument("--stats", action="store_true", help="Résumé progression")
    parser.add_argument("--fill", type=int, metavar="ID",
                        help="ID du chunk à remplir (colle la réponse depuis stdin)")
    parser.add_argument("--fill-file", type=str, metavar="FILE",
                        help="Lire la réponse depuis un fichier .txt au lieu de stdin")
    args = parser.parse_args()

    prompts_path = args.prompts

    if args.fill:
        if args.fill_file:
            response_text = Path(args.fill_file).read_text(encoding="utf-8")
        else:
            print(f"Colle la réponse Claude pour le chunk #{args.fill} (Ctrl+D pour valider) :")
            response_text = sys.stdin.read()
        fill_response(prompts_path, args.fill, response_text.strip())
        return

    prompts = load(prompts_path)

    if args.stats:
        stats(prompts)
        return

    pending = [p for p in prompts if p.get("status") != "done"]

    if not pending:
        print("🎉 Tous les chunks ont été traités ! Lance build_anki_csv.py pour générer le CSV.")
        return

    if args.all:
        for p in pending:
            show_prompt(p)
        print(f"\n→ {len(pending)} chunks en attente.")
    else:
        show_prompt(pending[0])
        print(f"→ {len(pending) - 1} autres chunks en attente. Lance --stats pour voir la progression.")

    print("\nPour enregistrer une réponse :")
    print(f"  python show_prompts.py --fill <ID>")
    print(f"  python show_prompts.py --fill <ID> --fill-file reponse.txt\n")


if __name__ == "__main__":
    main()