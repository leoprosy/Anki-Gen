#!/usr/bin/env python3
"""
build_app_payload.py — Construit le dossier applicatif livré par app.zip et embarqué dans l'exe.

Avant ce script, la liste des modules Python existait en trois exemplaires tenus
à la main (flask-server.spec, build-latest.yml, release.yml). Un module ajouté à
l'app mais oublié dans une liste passait tous les tests, puis manquait chez
l'utilisateur. Ici, rien n'est listé : les modules sont ceux que `modulefinder`
atteint depuis les points d'entrée, imports placés dans des fonctions compris.
Seuls les dossiers de données et les fichiers générés au build sont déclarés,
parce qu'aucun import n'y mène.

Le même dossier sert aux deux livraisons :
  * flask-server.spec l'embarque dans l'exécutable (`app_bundle/`) ;
  * les workflows le compressent en app.zip pour l'updater.

Usage :
    python scripts/build_app_payload.py --dest release/app [--zip app.zip]
                                        [--version 1.2.1] [--commit <sha>]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from modulefinder import ModuleFinder
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_contract import runtime_version  # noqa: E402

# `launcher.py` est l'entrée de l'exécutable ; `runtime_probe.py` n'est importé
# par personne dans l'app : c'est launcher --self-check qui le charge.
ENTRY_POINTS = ("app.py", "launcher.py", "runtime_probe.py")
DATA_DIRS = ("templates", "static", "locales", "skill_templates", "prompt_templates")
IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc")


def _analytics_config(root: Path, target: Path) -> None:
    """
    Configuration publique de collecte (voir analytics_config.write_build_config).

    Le fichier de la racine, s'il existe, sert de valeurs par défaut ; les
    variables ANKIGEN_POSTHOG_* de la CI l'emportent. Il est écrit directement
    dans le payload : aucun build ne peut l'oublier.
    """
    sys.path.insert(0, str(root))
    from analytics_config import write_build_config

    existing = root / "analytics_config.json"
    if existing.is_file():
        shutil.copy2(existing, target)
    write_build_config(target)


# Fichiers produits au moment du build : ni un import ni un dossier de données
# n'y mènent, chacun a donc son générateur.
GENERATED_FILES = {"analytics_config.json": _analytics_config}


def local_modules(root: Path = ROOT) -> list:
    """
    Fichiers .py de la racine atteints depuis les points d'entrée.

    Le chemin de recherche est limité à la racine du dépôt : les imports de la
    bibliothèque standard et des dépendances échouent sans bruit dans
    ModuleFinder, ce qui est exactement le tri voulu (ils vivent dans l'exe).
    """
    root = Path(root).resolve()
    finder = ModuleFinder(path=[str(root)])
    for entry in ENTRY_POINTS:
        finder.run_script(str(root / entry))
    found = {
        Path(module.__file__).name
        for module in finder.modules.values()
        if module.__file__ and Path(module.__file__).resolve().parent == root
    }
    return sorted(found | set(ENTRY_POINTS))


def tauri_version(root: Path = ROOT) -> str:
    conf = json.loads((root / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    return conf["version"]


def current_commit(root: Path = ROOT) -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build_payload(dest: Path, version: str, commit: str, root: Path = ROOT) -> dict:
    """
    (Re)crée `dest` et retourne le manifeste écrit dans `dest/version.json`.

    `modules` et `requires_runtime` voyagent avec le code : launcher --self-check
    importe ces modules, et l'updater compare `requires_runtime` au runtime de
    l'exécutable avant d'accepter la mise à jour.
    """
    root, dest = Path(root), Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    modules = local_modules(root)
    for name in modules:
        shutil.copy2(root / name, dest / name)
    for directory in DATA_DIRS:
        shutil.copytree(root / directory, dest / directory, ignore=IGNORED)
    for name, generate in GENERATED_FILES.items():
        generate(root, dest / name)

    manifest = {
        "version": version,
        "commit": commit,
        "requires_runtime": runtime_version(root / "runtime.json"),
        "modules": [Path(name).stem for name in modules],
    }
    (dest / "version.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def write_zip(source: Path, zip_path: Path) -> None:
    """Archive avec un dossier `app/` à la racine, la structure qu'attend l'updater."""
    source = Path(source)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, Path("app") / path.relative_to(source))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--zip", type=Path, help="écrire aussi l'archive app.zip")
    parser.add_argument("--version", help="défaut : src-tauri/tauri.conf.json")
    parser.add_argument("--commit", help="défaut : $GITHUB_SHA, sinon git rev-parse HEAD")
    args = parser.parse_args(argv)

    manifest = build_payload(
        args.dest, args.version or tauri_version(), args.commit or current_commit()
    )
    if args.zip:
        write_zip(args.dest, args.zip)
    print(f"[payload] {manifest['version']} ({manifest['commit'][:7] or 'commit inconnu'}), "
          f"runtime {manifest['requires_runtime']}, {len(manifest['modules'])} modules : "
          + ", ".join(manifest["modules"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
