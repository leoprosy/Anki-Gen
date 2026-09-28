#!/usr/bin/env python3
"""
launcher.py — Production WSGI entry point for Ankigen.

Used in two ways:
  1. Standalone: `python launcher.py` (opens browser)
  2. Tauri sidecar: launched automatically by the Tauri app (no browser)

Set environment variable ANKI_ESH_SIDECAR=1 to suppress browser opening.
"""

import json
import os
import shutil
import socket
import sys
import threading
import webbrowser

from waitress import serve


# ── Résolution des dossiers applicatifs ────────────────────────

def get_app_dir():
    """Résout le dossier applicatif selon le contexte d'exécution.

    - Mode PyInstaller (frozen) : %APPDATA%/AnkiGen/app/
    - Mode dev : le dossier courant du script
    """
    if getattr(sys, 'frozen', False):
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'AnkiGen', 'app')
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_data_dir():
    """Résout le dossier de données utilisateur (projects, uploads).

    - Mode PyInstaller (frozen) : %APPDATA%/AnkiGen/
    - Mode dev : le dossier courant du script
    """
    if getattr(sys, 'frozen', False):
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'AnkiGen')
    else:
        return os.path.dirname(os.path.abspath(__file__))


def read_version(path):
    """Version déclarée par un version.json, ou None s'il est absent/illisible."""
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle).get('version')
    except (OSError, ValueError, AttributeError):
        return None


APP_DIR = get_app_dir()
DATA_DIR = get_data_dir()


def deploy_bundle(bundle_dir, app_dir):
    """Deploy only a newer bundled version; preserve downloaded updates."""
    from updater import is_newer_version

    installed = read_version(os.path.join(app_dir, 'version.json'))
    shipped = read_version(os.path.join(bundle_dir, 'version.json'))
    if shipped and (not installed or installed == '0.0.0'
                    or is_newer_version(shipped, installed)):
        shutil.copytree(bundle_dir, app_dir, dirs_exist_ok=True)
        return True
    return False


# ── Contrat de runtime et auto-vérification ────────────────────
# L'exécutable embarque runtime.json (voir scripts/runtime_contract.py). Un
# exécutable antérieur au contrat n'en a pas : il vaut 0, et toute mise à jour
# qui déclare `requires_runtime` lui demandera un nouvel installateur.

def read_runtime(path=None):
    """Numéro de runtime de l'exécutable courant, 0 s'il est inconnu."""
    if path is None:
        base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, 'runtime.json')
    try:
        with open(path, encoding='utf-8') as handle:
            return int(json.load(handle)['runtime'])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def default_check_dir():
    """Le code embarqué dans l'exe, sans passer par %APPDATA% ; la racine en dev."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'app_bundle')
    return os.path.dirname(os.path.abspath(__file__))


def _modules_without_manifest(app_dir):
    """
    Modules à importer quand version.json ne les liste pas.

    Dans un dossier livré (payload antérieur au manifeste), tout .py en fait
    partie. Dans le dépôt, la racine contient aussi des scripts et des notes :
    on reprend alors le calcul de scripts/build_app_payload.py.
    """
    scripts = os.path.join(app_dir, 'scripts')
    if os.path.isfile(os.path.join(scripts, 'build_app_payload.py')):
        sys.path.insert(0, scripts)
        from build_app_payload import local_modules
        return [name[:-3] for name in local_modules(app_dir)]
    return sorted(name[:-3] for name in os.listdir(app_dir) if name.endswith('.py'))


def self_check(app_dir, runtime):
    """
    Vérifie que ce runtime fait tourner le code de `app_dir`, sans démarrer le serveur.

    Importe chaque module déclaré par version.json, puis exécute runtime_probe,
    qui exerce les capacités réellement utilisées (encodeurs Pillow, lxml…).
    C'est ce qu'appelle la CI sur l'exe neuf, et sur l'exe de la release
    précédente avec le nouveau code (`--app-dir`).

    Returns:
        (report, exit_code) — 0 : tout passe ; 1 : un import ou une sonde échoue ;
        3 : le code exige un runtime plus récent (échec attendu, pas un bug).
    """
    import importlib

    try:
        with open(os.path.join(app_dir, 'version.json'), encoding='utf-8') as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        manifest = {}
    required = int(manifest.get('requires_runtime') or 0)
    report = {
        'app_dir': app_dir,
        'version': manifest.get('version'),
        'runtime': runtime,
        'requires_runtime': required,
        'modules': {},
        'probes': {},
    }
    if required > runtime:
        report['status'] = 'runtime_too_old'
        return report, 3

    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    modules = manifest.get('modules') or _modules_without_manifest(app_dir)
    for name in modules:
        if name == 'launcher':      # c'est ce script : l'importer relancerait le bootstrap
            continue
        try:
            importlib.import_module(name)
            report['modules'][name] = None
        except Exception as error:
            report['modules'][name] = f'{type(error).__name__}: {error}'

    # Les sondes viennent du code vérifié, jamais d'un module déjà chargé ailleurs.
    if 'runtime_probe' in report['modules'] and report['modules']['runtime_probe'] is None:
        report['probes'] = sys.modules['runtime_probe'].run()

    failed = [v for v in list(report['modules'].values()) + list(report['probes'].values()) if v]
    report['status'] = 'failed' if failed else 'ok'
    return report, 1 if failed else 0


def run_self_check(argv):
    app_dir = default_check_dir()
    if '--app-dir' in argv:
        app_dir = argv[argv.index('--app-dir') + 1]
    report, code = self_check(os.path.abspath(app_dir), read_runtime())
    # ensure_ascii : la console Windows de la CI n'est pas forcément en UTF-8.
    print(json.dumps(report, indent=2, ensure_ascii=True), flush=True)
    return code


if '--self-check' in sys.argv:
    sys.exit(run_self_check(sys.argv))


# ── Bootstrap : première exécution en mode frozen ─────────────
if getattr(sys, 'frozen', False):
    os.makedirs(APP_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # Ajouter le dossier applicatif au path Python
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)

    # Never overwrite a downloaded update with the executable's older bundle.
    _bundled = os.path.join(sys._MEIPASS, 'app_bundle')
    if os.path.isdir(_bundled):
        if deploy_bundle(_bundled, APP_DIR):
            print(f'[bootstrap] Fichiers applicatifs déployés dans {APP_DIR}')

    # Applique une mise à jour préalablement téléchargée (updater.py), si présente.
    # Se fait avant tout import de app.py / démarrage de Waitress, donc jamais
    # pendant que le serveur sert des requêtes.
    try:
        from updater import apply_staged_update
        if apply_staged_update(APP_DIR):
            print(f"[bootstrap] Mise à jour appliquée dans {APP_DIR}")
    except Exception as e:
        print(f"[bootstrap] Échec de l'application de la mise à jour : {e}")


from app import app

PORT = 5000


def find_free_port(start=5000, end=5100):
    """Find a free port so we never collide with another app."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def open_browser(port):
    """Open the browser after a short delay so the server is ready."""
    import time
    time.sleep(1.0)
    webbrowser.open(f"http://127.0.0.1:{port}")


def main():
    port = find_free_port(start=PORT)

    is_sidecar = os.environ.get("ANKI_ESH_SIDECAR") == "1"

    print(f"Ankigen running on http://127.0.0.1:{port}", flush=True)

    if not is_sidecar:
        print("   Close this window to stop the server.\n")
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    serve(app, host="127.0.0.1", port=port, threads=4)


if __name__ == "__main__":
    main()
