#!/usr/bin/env python3
"""
updater.py — Module d'auto-mise à jour pour Ankigen.

Interroge l'API GitHub Releases pour vérifier si une nouvelle version
est disponible, et télécharge les fichiers applicatifs dans un dossier de
staging (%APPDATA%/AnkiGen/app_staged/) sans toucher au dossier live pendant
que le serveur tourne. L'échange effectif a lieu au démarrage suivant
(voir apply_staged_update, appelé par launcher.py), et ne touche jamais
aux données utilisateur (projects/, uploads/).

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


def is_newer_version(remote_version, local_version):
    """Indique si une version distante lisible est plus récente que la version locale."""

    def parse(version):
        try:
            parts = tuple(int(part) for part in version.split("."))
        except (AttributeError, ValueError):
            return None
        if len(parts) != 3 or any(part < 0 for part in parts):
            return None
        return parts

    remote = parse(remote_version)
    local = parse(local_version)
    if remote is None or local is None or local == (0, 0, 0):
        return False
    return remote > local


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


def _staging_dir(target_dir):
    return target_dir + "_staged"


def download_and_apply(download_url, target_dir):
    """Télécharge le zip du release et le prépare pour application au prochain démarrage.

    Le dossier applicatif du process en cours d'exécution n'est JAMAIS touché :
    le nouveau contenu est extrait vers `target_dir + "_staged"`. C'est
    `apply_staged_update()` (appelé par launcher.py avant de démarrer le serveur)
    qui effectue l'échange, une fois qu'aucun serveur ne sert de requêtes.

    Args:
        download_url: URL de téléchargement de l'asset app.zip.
        target_dir: Chemin du dossier applicatif à mettre à jour.
    """
    staging_dir = _staging_dir(target_dir)
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)

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

        # Copie vers le dossier de staging (le dossier live n'est pas touché)
        shutil.copytree(extracted_app, staging_dir)


def apply_staged_update(target_dir):
    """Échange le dossier applicatif live avec la mise à jour en attente, si présente.

    Appelé au tout début du démarrage, avant que le serveur n'écoute sur un port :
    aucune requête n'est en cours de traitement à ce moment, donc l'opération
    n'a aucune fenêtre d'indisponibilité perceptible côté utilisateur. Si l'échange
    échoue en cours de route, `target_dir` n'est jamais supprimé avant que le
    nouveau contenu ne soit confirmé en place, donc une interruption (crash,
    coupure de courant) laisse au pire l'ancienne version intacte.

    Returns:
        bool: True si une mise à jour en attente a été appliquée.
    """
    staging_dir = _staging_dir(target_dir)
    if not os.path.isdir(staging_dir):
        return False

    backup_dir = target_dir + "_backup"
    try:
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)

        # 1. L'ancien contenu live est déplacé de côté (pas supprimé)
        if os.path.exists(target_dir):
            os.rename(target_dir, backup_dir)

        # 2. Le nouveau contenu devient le dossier live
        os.rename(staging_dir, target_dir)

        # 3. Succès → l'ancienne version n'est plus nécessaire
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        return True

    except Exception:
        # Échec : restaurer l'ancien contenu s'il a été déplacé, et conserver
        # le staging pour ne pas perdre le téléchargement.
        if os.path.exists(backup_dir) and not os.path.exists(target_dir):
            os.rename(backup_dir, target_dir)
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
            "status": "staged",
            "version": remote_version,
            "message_key": "update.staged",
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
