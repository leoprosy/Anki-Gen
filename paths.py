#!/usr/bin/env python3
"""
paths.py — Résolution des chemins de données d'Anki-Gen.

En développement (`python app.py`), tout vit à la racine du projet.
Une fois packagé, l'entrée est `launcher.py` : il expose APP_DIR (code, templates,
static — sous %APPDATA%/AnkiGen/app) et DATA_DIR (%APPDATA%/AnkiGen). On s'appuie
dessus pour que projets, uploads, médias et exports survivent aux mises à jour et
ne disparaissent pas dans le dossier temporaire de PyInstaller.

L'import de `launcher` est tenté paresseusement : en mode dev l'import est
circulaire (launcher importe app, app importe paths) et lève une exception —
on retombe alors sur le dossier du script, ce qui est le comportement voulu.
"""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _resolve_base_dirs():
    """(APP_DIR, DATA_DIR) — délègue à launcher.py si disponible, sinon script."""
    try:
        from launcher import APP_DIR as _app, DATA_DIR as _data
        return Path(_app), Path(_data)
    except Exception:
        root = Path(__file__).parent.resolve()
        return root, root


APP_DIR, DATA_DIR = _resolve_base_dirs()
UPLOAD_DIR = DATA_DIR / "uploads"
PROJECTS_DIR = DATA_DIR / "projects"
MEDIA_DIR = DATA_DIR / "media"
EXPORT_DIR = DATA_DIR / "exports"


def ensure_dirs() -> None:
    for d in (UPLOAD_DIR, PROJECTS_DIR, MEDIA_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data() -> list:
    """
    Compat : rien à migrer. `launcher.py` gère le bootstrap des fichiers
    applicatifs ; les données (projects/, media/…) vivent déjà sous DATA_DIR.
    Conservé pour ne pas casser l'appel dans app.py.
    """
    return []


def project_media_dir(project_id: str) -> Path:
    """Dossier médias d'un projet (créé à la demande)."""
    d = MEDIA_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def anki_media_dirs() -> list:
    """
    Repère les dossiers `collection.media` des profils Anki installés.
    Retourne [{"profile": str, "path": str, "files": int}, ...]
    """
    candidates = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Anki2")
    else:
        candidates.append(Path.home() / ".local" / "share" / "Anki2")
        candidates.append(Path.home() / "Library" / "Application Support" / "Anki2")

    found = []
    for base in candidates:
        if not base.is_dir():
            continue
        for profile in sorted(base.iterdir()):
            media = profile / "collection.media"
            if media.is_dir():
                try:
                    count = sum(1 for _ in media.iterdir())
                except OSError:
                    count = -1
                found.append({"profile": profile.name, "path": str(media), "files": count})
    return found
