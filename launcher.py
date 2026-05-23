#!/usr/bin/env python3
"""
launcher.py — Production WSGI entry point for Anki ESH.

Used in two ways:
  1. Standalone: `python launcher.py` (opens browser)
  2. Tauri sidecar: launched automatically by the Tauri app (no browser)

Set environment variable ANKI_ESH_SIDECAR=1 to suppress browser opening.
"""

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


APP_DIR = get_app_dir()
DATA_DIR = get_data_dir()


# ── Bootstrap : première exécution en mode frozen ─────────────
if getattr(sys, 'frozen', False):
    os.makedirs(APP_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # Ajouter le dossier applicatif au path Python
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)

    # Première exécution : copier les fichiers embarqués dans APPDATA
    _bundled = os.path.join(sys._MEIPASS, 'app_bundle')
    _version_local = os.path.join(APP_DIR, 'version.json')
    if os.path.isdir(_bundled) and not os.path.exists(_version_local):
        shutil.copytree(_bundled, APP_DIR, dirs_exist_ok=True)
        print(f"[bootstrap] Fichiers applicatifs copiés dans {APP_DIR}")


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

    print(f"Anki ESH running on http://127.0.0.1:{port}", flush=True)

    if not is_sidecar:
        print("   Close this window to stop the server.\n")
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    serve(app, host="127.0.0.1", port=port, threads=4)


if __name__ == "__main__":
    main()
