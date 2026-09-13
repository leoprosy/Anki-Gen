#!/usr/bin/env python3
"""
updater.py — Module d'auto-mise à jour pour Ankigen.

Interroge l'API GitHub Releases pour vérifier si une nouvelle version
est disponible, et remplace les fichiers applicatifs dans %APPDATA%/AnkiGen/app/
sans toucher aux données utilisateur (projects/, uploads/).

Usage interne uniquement — appelé par les endpoints Flask /api/update/*.
"""

import json
import os
import shutil
import tempfile
import zipfile
from urllib.error import URLError
from urllib.request import Request, urlopen

GITHUB_REPO = "leoprosy/Anki-Gen"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _get_app_dir():
    """Résout le dossier applicatif (identique à launcher.get_app_dir)."""
    try:
        from launcher import APP_DIR
        return APP_DIR
    except ImportError:
        # Fallback mode dev
        return os.path.dirname(os.path.abspath(__file__))


def get_local_version():
    """Lit la version locale depuis version.json dans le dossier applicatif."""
    version_file = os.path.join(_get_app_dir(), "version.json")
    if not os.path.exists(version_file):
        return "0.0.0"
    try:
        with open(version_file, encoding="utf-8") as f:
            return json.load(f).get("version", "0.0.0")
    except (json.JSONDecodeError, OSError):
        return "0.0.0"


def fetch_latest_release():
    """Interroge l'API GitHub pour obtenir le dernier release.

    Returns:
        dict: Réponse JSON de l'API GitHub Releases.

    Raises:
        URLError: Si pas de connexion réseau.
        Exception: Pour toute autre erreur HTTP.
    """
    req = Request(RELEASES_URL, headers={"User-Agent": "AnkiGen-Updater/1.0"})
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def download_and_apply(download_url, target_dir):
    """Télécharge le zip du release et remplace les fichiers applicatifs.

    Effectue un remplacement semi-atomique :
      1. Backup du dossier actuel → target_dir_backup
      2. Extraction et copie des nouveaux fichiers
      3. Suppression du backup en cas de succès
      4. Restauration du backup en cas d'échec

    Args:
        download_url: URL de téléchargement de l'asset app.zip.
        target_dir: Chemin du dossier applicatif à mettre à jour.
    """
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "update.zip")

        # Téléchargement
        req = Request(download_url, headers={"User-Agent": "AnkiGen-Updater/1.0"})
        with urlopen(req, timeout=60) as resp, open(zip_path, "wb") as f:
            f.write(resp.read())

        # Extraction
        extract_dir = os.path.join(tmp, "extracted")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        # Trouver le dossier 'app' dans l'archive
        # (structure attendue : app.zip contient un dossier 'app/' à la racine)
        extracted_app = os.path.join(extract_dir, "app")
        if not os.path.isdir(extracted_app):
            # Si pas de sous-dossier 'app', utiliser la racine de l'extraction
            extracted_app = extract_dir

        # Remplacement avec backup
        backup_dir = target_dir + "_backup"
        try:
            # 1. Backup
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
            if os.path.exists(target_dir):
                shutil.copytree(target_dir, backup_dir)

            # 2. Copie des nouveaux fichiers (merge, ne supprime pas le dossier)
            for item in os.listdir(extracted_app):
                src = os.path.join(extracted_app, item)
                dst = os.path.join(target_dir, item)
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

            # 3. Succès → supprimer le backup
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)

        except Exception:
            # 4. Échec → restaurer le backup
            if os.path.exists(backup_dir):
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
                shutil.move(backup_dir, target_dir)
            raise


def check_and_update():
    """Point d'entrée principal pour vérifier et appliquer une mise à jour.

    Le message est retourné sous forme de *clé* de traduction et de paramètres,
    et non de texte : ce module ne connaît pas la langue de l'utilisateur, et la
    traduire ici l'obligerait à dépendre de i18n. C'est `app.py`, qui lit les
    préférences, qui rend la clé en texte.

    Returns:
        dict: Résultat avec les clés :
            - status: 'up_to_date' | 'updated' | 'error'
            - version: str (version courante ou nouvelle)
            - message_key: str (clé de traduction)
            - message_params: dict (paramètres d'interpolation)
    """
    try:
        release = fetch_latest_release()
        remote_version = release["tag_name"].lstrip("v")
        local_version = get_local_version()

        if remote_version == local_version:
            return {
                "status": "up_to_date",
                "version": local_version,
                "message_key": "update.up_to_date",
                "message_params": {},
            }

        # Cherche l'asset app.zip dans le release
        asset_url = next(
            (
                a["browser_download_url"]
                for a in release.get("assets", [])
                if a["name"] == "app.zip"
            ),
            None,
        )
        if not asset_url:
            return {
                "status": "error",
                "version": local_version,
                "message_key": "update.asset_missing",
                "message_params": {},
            }

        download_and_apply(asset_url, _get_app_dir())
        return {
            "status": "updated",
            "version": remote_version,
            "message_key": "update.applied",
            "message_params": {"version": remote_version},
        }

    except URLError:
        return {
            "status": "error",
            "version": get_local_version(),
            "message_key": "update.offline",
            "message_params": {},
        }
    except Exception as e:
        return {
            "status": "error",
            "version": get_local_version(),
            "message_key": "update.failed",
            "message_params": {"error": str(e)},
        }
