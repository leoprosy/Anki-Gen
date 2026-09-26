#!/usr/bin/env python3
"""
settings.py — Préférences utilisateur d'Ankigen.

Persistées dans DATA_DIR/settings.json, donc à côté de projects/ et media/, et
hors de app/ qui est remplacé à chaque mise à jour.

Ne dépend ni de Flask ni de i18n : de la lecture/écriture de fichier, testable
seule. `check_dir` retourne une *clé* de message, pas un texte — la traduction
appartient à la couche qui connaît la langue.
"""

import json
import os
import tempfile
from pathlib import Path

import paths

LANGUAGES = ("en", "fr")

# Global de module, et non constante figée à l'import : les tests le redirigent
# vers un dossier jetable pour ne jamais écrire dans %APPDATA%.
SETTINGS_FILE = paths.DATA_DIR / "settings.json"


def default_download_dir():
    """~/Downloads s'il existe, sinon le dossier d'exports de l'app."""
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else paths.EXPORT_DIR)


def defaults():
    return {
        "language": "en",
        "download_dir": default_download_dir(),
        "deck_prefix": "",
        "analytics_enabled": False,
        "analytics_usage_enabled": False,
        "analytics_product_enabled": False,
        "analytics_decided": False,
    }


def _clean(raw):
    """
    Valide clé par clé, en repartant des défauts.

    Une valeur invalide retombe sur son défaut sans emporter les autres : une
    préférence cassée ne doit coûter que celle-là. Les clés inconnues sont
    ignorées plutôt que conservées, pour que le fichier ne se remplisse pas de
    résidus d'anciennes versions.
    """
    out = defaults()
    if not isinstance(raw, dict):
        return out

    legacy = raw.get("analytics_enabled") is True
    out["analytics_usage_enabled"] = raw.get("analytics_usage_enabled", legacy) is True
    out["analytics_product_enabled"] = raw.get("analytics_product_enabled", legacy) is True
    out["analytics_enabled"] = out["analytics_usage_enabled"] or out["analytics_product_enabled"]
    # Une acceptation enregistrée avant l'ajout du panneau reste acquise.
    out["analytics_decided"] = raw.get("analytics_decided") is True or out["analytics_enabled"]

    language = raw.get("language")
    if isinstance(language, str) and language in LANGUAGES:
        out["language"] = language

    deck_prefix = raw.get("deck_prefix")
    if isinstance(deck_prefix, str):
        out["deck_prefix"] = deck_prefix.strip()

    download_dir = raw.get("download_dir")
    if isinstance(download_dir, str) and download_dir.strip():
        # Conservé tel quel même s'il ne pointe nulle part : réécrire la saisie
        # de l'utilisateur en silence lui ferait perdre ce qu'il a tapé.
        out["download_dir"] = download_dir.strip()

    return out


def load_settings():
    """Préférences complètes. Fichier absent, illisible ou invalide → défauts."""
    try:
        raw = json.loads(Path(SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults()
    return _clean(raw)


def save_settings(partial):
    """
    Fusionne `partial` dans l'existant et écrit atomiquement.

    Écriture par fichier temporaire puis `os.replace` : une coupure en cours
    d'écriture laisse l'ancien fichier intact plutôt qu'un JSON tronqué, que le
    prochain démarrage traiterait comme corrompu.
    """
    merged = load_settings()
    # Older clients use the single switch. An explicit legacy update controls
    # both categories, while a granular update leaves the other one intact.
    if isinstance(partial, dict) and "analytics_enabled" in partial and not any(
        key in partial for key in ("analytics_usage_enabled", "analytics_product_enabled")
    ):
        merged["analytics_usage_enabled"] = partial["analytics_enabled"]
        merged["analytics_product_enabled"] = partial["analytics_enabled"]
    for key in defaults():
        if isinstance(partial, dict) and key in partial:
            merged[key] = partial[key]
    merged = _clean(merged)

    target = Path(SETTINGS_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return merged


def check_dir(path):
    """
    (utilisable, clé de message) pour un dossier de téléchargement candidat.

    Utilisé par la page de réglages pour dire à l'utilisateur si sa saisie tient
    debout, sans rien enregistrer.
    """
    path = (path or "").strip()
    if not path:
        return False, "settings.dir_blank"

    candidate = Path(path)
    if candidate.exists() and not candidate.is_dir():
        return False, "settings.dir_not_a_folder"

    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False, "settings.dir_unreachable"

    if not os.access(candidate, os.W_OK):
        return False, "settings.dir_not_writable"

    return True, "settings.dir_ok"


def resolve_download_dir():
    """
    Dossier d'export utilisable, ou None.

    None n'est pas une erreur : c'est à l'appelant (l'export) de dégrader
    proprement plutôt que d'échouer sur un réglage devenu invalide.
    """
    configured = load_settings()["download_dir"]
    ok, _ = check_dir(configured)
    if not ok:
        return None
    return Path(configured)
