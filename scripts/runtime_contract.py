#!/usr/bin/env python3
"""
runtime_contract.py — Contrat entre l'exécutable (le « runtime ») et app.zip (le code).

Ankigen est livré en deux morceaux qui ne se mettent pas à jour au même rythme :

  * l'exécutable PyInstaller (`flask-server.exe`) contient l'interpréteur, la
    bibliothèque standard et les dépendances de requirements.txt. Il ne change
    qu'avec un nouvel installateur ;
  * app.zip contient les modules de l'app, les templates et le reste. L'updater
    intégré le remplace à chaud, sur un exécutable qui peut dater de plusieurs
    versions.

Pour que du code récent tourne sur un exécutable ancien, l'exécutable embarque
TOUTE la bibliothèque standard et TOUS les sous-modules des dépendances : un
nouvel `import difflib` ou `from PIL import ImageFont` ne demande donc jamais de
nouvel installateur. Reste le seul cas qu'on ne peut pas anticiper : une nouvelle
dépendance dans requirements.txt. C'est ce que numérote `runtime.json` :

    {"runtime": 1, "requirements_sha256": "…"}

L'exécutable embarque ce fichier, app.zip déclare `requires_runtime`, et
l'updater refuse une mise à jour que l'exécutable ne peut pas faire tourner. Le
test `test_runtime_contract` échoue si la partie runtime de requirements.txt
change sans que le numéro soit incrémenté (`python scripts/runtime_contract.py --bump`).

Ce module ne dépend que de la bibliothèque standard : il est chargé par
flask-server.spec, par scripts/build_app_payload.py et par les tests.
"""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_FILE = ROOT / "runtime.json"
REQUIREMENTS_FILE = ROOT / "requirements.txt"

# requirements.txt mélange le runtime et l'outillage de compilation. Tout ce qui
# suit ce commentaire ne sert qu'à construire l'exécutable et n'est pas embarqué.
PACKAGING_MARKER = "# Packaging"

# Modules de la bibliothèque standard qu'un serveur local n'importera jamais :
# interfaces graphiques, suites de tests, outils d'installation, démos.
STDLIB_EXCLUDES = frozenset({
    "__phello__", "_tkinter", "antigravity", "ensurepip", "idlelib", "lib2to3",
    "pydoc_data", "test", "this", "tkinter", "turtle", "turtledemo", "unittest",
    "venv",
})

# Sous-paquets de tests livrés à l'intérieur de paquets utiles (idlelib.idle_test,
# lib2to3.tests…) : ils alourdissent l'exécutable sans rien apporter.
TEST_PACKAGE_NAMES = frozenset({"test", "tests", "idle_test"})


# ──────────────────────────────────────────────────────────────
# requirements.txt
# ──────────────────────────────────────────────────────────────
def runtime_requirements(text: str) -> list:
    """Lignes de dépendances runtime, normalisées et triées (sans l'outillage)."""
    lines = []
    for raw in text.splitlines():
        if raw.strip().startswith(PACKAGING_MARKER):
            break
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(re.sub(r"\s+", "", line).lower())
    return sorted(lines)


def requirements_digest(lines: list) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def distribution_name(requirement: str) -> str:
    """'python-docx==1.2.0' → 'python-docx' (forme canonique PEP 503)."""
    name = re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def current_requirements() -> list:
    return runtime_requirements(REQUIREMENTS_FILE.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────
# runtime.json
# ──────────────────────────────────────────────────────────────
def load_runtime(path: Path = RUNTIME_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def runtime_version(path: Path = RUNTIME_FILE) -> int:
    return int(load_runtime(path)["runtime"])


def check_contract() -> tuple:
    """(ok, message) — le numéro de runtime couvre-t-il requirements.txt ?"""
    recorded = load_runtime().get("requirements_sha256")
    actual = requirements_digest(current_requirements())
    if recorded == actual:
        return True, "runtime.json à jour."
    return False, (
        "La partie runtime de requirements.txt a changé : un exécutable déjà "
        "installé ne contient pas ces dépendances. Lancez "
        "`python scripts/runtime_contract.py --bump` pour incrémenter le numéro "
        "de runtime (les utilisateurs devront réinstaller)."
    )


def bump() -> int:
    data = load_runtime() if RUNTIME_FILE.exists() else {"runtime": 0}
    data["runtime"] = int(data.get("runtime", 0)) + 1
    data["requirements_sha256"] = requirements_digest(current_requirements())
    RUNTIME_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data["runtime"]


# ──────────────────────────────────────────────────────────────
# Ce que l'exécutable doit embarquer
# ──────────────────────────────────────────────────────────────
def _walk_package(directory: Path, prefix: str):
    """Sous-modules d'un paquet, lus sur le disque : rien n'est importé."""
    for entry in sorted(directory.iterdir()):
        if entry.name == "__pycache__":
            continue
        if entry.is_dir() and (entry / "__init__.py").exists():
            if entry.name in TEST_PACKAGE_NAMES:
                continue
            name = f"{prefix}.{entry.name}"
            yield name
            yield from _walk_package(entry, name)
        elif entry.suffix == ".py" and entry.stem != "__init__":
            yield f"{prefix}.{entry.stem}"


def stdlib_modules() -> list:
    """
    Toute la bibliothèque standard utile, sous-modules compris.

    Les noms de premier niveau viennent de `sys.stdlib_module_names` ; les
    sous-modules sont lus sur le disque plutôt qu'importés, pour rester rapide
    et ne déclencher aucun effet de bord pendant la compilation.
    """
    stdlib = Path(sysconfig.get_path("stdlib"))
    names = []
    for top in sorted(sys.stdlib_module_names):
        if top in STDLIB_EXCLUDES:
            continue
        package = stdlib / top
        if (package / "__init__.py").exists():
            names.append(top)
            names.extend(_walk_package(package, top))
        elif (stdlib / f"{top}.py").exists():
            names.append(top)
        elif importlib.util.find_spec(top) is not None:
            # Module C (intégré ou .pyd) : présent sur cette plateforme.
            names.append(top)
    return names


def runtime_import_names(requirements: list = None) -> list:
    """
    Noms importables des dépendances runtime ('pillow' → 'PIL', 'python-docx' → 'docx').

    Lit les métadonnées de l'environnement courant : les dépendances doivent donc
    être installées, ce qui est le cas partout où l'on compile l'exécutable.
    """
    from importlib.metadata import packages_distributions

    wanted = {distribution_name(r) for r in (requirements or current_requirements())}
    names = set()
    for import_name, distributions in packages_distributions().items():
        if import_name.startswith("_") or not import_name.isidentifier():
            continue
        if any(distribution_name(d) in wanted for d in distributions):
            names.add(import_name)
    return sorted(names)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="vérifier runtime.json")
    group.add_argument("--bump", action="store_true", help="incrémenter le numéro de runtime")
    group.add_argument("--show", action="store_true", help="afficher ce que l'exe embarquera")
    args = parser.parse_args(argv)

    if args.bump:
        print(f"runtime -> {bump()}")
        return 0
    if args.show:
        print(json.dumps({
            "runtime": runtime_version(),
            "packages": runtime_import_names(),
            "stdlib_modules": len(stdlib_modules()),
        }, indent=2))
        return 0
    ok, message = check_contract()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
