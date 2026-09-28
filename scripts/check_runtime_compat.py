#!/usr/bin/env python3
"""
check_runtime_compat.py — Le nouveau code tourne-t-il sur l'exécutable déjà installé chez les gens ?

C'est le scénario que l'updater crée à chaque livraison : app.zip récent,
exécutable ancien. Ce script récupère `flask-server.exe` sur la dernière release
qui le publie, puis lui fait exécuter `--self-check` sur le nouveau payload.

    0 → compatible ;
    3 → le payload exige un runtime plus récent : les utilisateurs recevront
        « nouvel installateur requis », c'est voulu, la CI passe ;
    autre → le nouveau code casserait les installations existantes : la CI échoue.

Tant qu'aucune release ne publie l'exécutable (celles d'avant ce contrat),
le contrôle est sauté avec un avertissement.

Usage (Windows uniquement, l'exécutable est un .exe) :
    python scripts/check_runtime_compat.py --app-dir release/app [--exclude-tag v1.3.0]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

REPO = "leoprosy/Anki-Gen"
ASSET = "flask-server.exe"


def _request(url):
    headers = {"User-Agent": "Ankigen-CI", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return Request(url, headers=headers)


def find_previous_exe(releases, exclude_tag=None):
    """(tag, url) de la release publiée la plus récente qui porte l'exécutable."""
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        if exclude_tag and release.get("tag_name") == exclude_tag:
            continue
        for asset in release.get("assets", []):
            if asset.get("name") == ASSET:
                return release["tag_name"], asset["browser_download_url"]
    return None


def interpret(exit_code):
    """(la CI passe ?, message)"""
    if exit_code == 0:
        return True, "compatible : le nouveau code tourne sur l'exécutable publié."
    if exit_code == 3:
        return True, ("le nouveau code exige un runtime plus récent : les utilisateurs "
                      "seront invités à réinstaller (attendu après un --bump).")
    return False, ("le nouveau code ne tourne PAS sur l'exécutable publié. Soit un "
                   "import ou une sonde manque au runtime, soit une dépendance a été "
                   "ajoutée sans `python scripts/runtime_contract.py --bump`.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--app-dir", required=True, type=Path)
    parser.add_argument("--exclude-tag", help="release en cours de publication, à ignorer")
    parser.add_argument("--repo", default=REPO)
    args = parser.parse_args(argv)

    if os.name != "nt":
        print("::notice::check_runtime_compat : Windows uniquement, contrôle sauté.")
        return 0

    with urlopen(_request(f"https://api.github.com/repos/{args.repo}/releases?per_page=20"),
                 timeout=30) as resp:
        releases = json.loads(resp.read())
    found = find_previous_exe(releases, args.exclude_tag)
    if found is None:
        print(f"::warning::Aucune release ne publie encore {ASSET} : "
              "compatibilité avec l'exécutable installé non vérifiée.")
        return 0
    tag, url = found

    work = Path(tempfile.mkdtemp(prefix="ankigen-compat-"))
    try:
        exe = work / ASSET
        with urlopen(_request(url), timeout=300) as resp, open(exe, "wb") as out:
            shutil.copyfileobj(resp, out)
        # APPDATA isolé : importer app.py crée les dossiers de données.
        env = dict(os.environ, APPDATA=str(work / "appdata"))
        result = subprocess.run(
            [str(exe), "--self-check", "--app-dir", str(args.app_dir.resolve())],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300,
        )
        print(result.stdout)
        if result.stderr.strip():
            print(result.stderr, file=sys.stderr)
        ok, message = interpret(result.returncode)
        print(("::notice::" if ok else "::error::") + f"Exécutable {tag} : {message}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
