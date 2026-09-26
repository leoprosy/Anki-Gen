"""Configuration publique de collecte, commune aux builds et à l'application."""

import json
import os
import re
from pathlib import Path

import paths

INGESTION_HOSTS = {"eu": "https://eu.i.posthog.com", "us": "https://us.i.posthog.com"}
TOKEN_PATTERN = re.compile(r"phc_[A-Za-z0-9]+")
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?")


def _read_object(path):
    try:
        value = Path(path).read_text(encoding="utf-8-sig")
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def _public_config(existing):
    return {
        "project_token": os.environ.get("ANKIGEN_POSTHOG_TOKEN", existing.get("project_token", "")),
        "region": os.environ.get("ANKIGEN_POSTHOG_REGION", existing.get("region", "eu")),
    }


def write_build_config(destination):
    """N'embarque jamais de clé personnelle, ni de destination arbitraire."""
    target = Path(destination)
    config = _public_config(_read_object(target))
    token = config["project_token"]
    if token and (not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token)):
        raise ValueError("Expected a public PostHog project token starting with phc_.")
    if config["region"] not in INGESTION_HOSTS:
        raise ValueError("ANKIGEN_POSTHOG_REGION must be eu or us.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def load_configuration(app_dir=None, packaged=None):
    """Absence/configuration incorrecte/dev normal : aucune collecte."""
    if packaged is None:
        packaged = paths.is_frozen()
    if not packaged and os.environ.get("ANKIGEN_ANALYTICS_DEV") != "1":
        return None
    root = Path(app_dir) if app_dir is not None else paths.APP_DIR
    config = _public_config(_read_object(root / "analytics_config.json"))
    token, region = config["project_token"], config["region"]
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        return None
    if not isinstance(region, str) or region not in INGESTION_HOSTS:
        return None
    version = _read_object(root / "version.json").get("version")
    config["app_version"] = version if isinstance(version, str) and VERSION_PATTERN.fullmatch(version) else "unknown"
    return config
