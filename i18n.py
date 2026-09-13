#!/usr/bin/env python3
"""
i18n.py — Résolution des chaînes traduites d'Ankigen.

Les traductions vivent dans `locales/<lang>.json` : des dictionnaires plats dont
les clés sont namespacées par écran (`upload.title`, `work.cards_detected`). Les
clés du namespace `js.` sont celles que `base.html` sérialise dans
`window.__I18N__` pour `static/app.js`.

Ce module ne dépend ni de Flask ni de `settings` : c'est `app.py` qui le relie au
reste. Il est ainsi testable seul, et utilisable hors requête HTTP.
"""

import json
from pathlib import Path

DEFAULT_LANG = "en"
LANGUAGES = ("en", "fr")
LANGUAGE_LABELS = {"en": "English", "fr": "Français"}

# En mode packagé, i18n.py vit dans APP_DIR et locales/ est copié à côté :
# résoudre relativement au module fonctionne dans les deux modes.
LOCALES_DIR = Path(__file__).parent / "locales"

_CACHE = {}


def load_catalog(lang):
    """Dictionnaire plat d'une langue. Locale absente ou illisible → {}."""
    if lang in _CACHE:
        return _CACHE[lang]
    try:
        catalog = json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        if not isinstance(catalog, dict):
            catalog = {}
    except (OSError, ValueError):
        catalog = {}
    _CACHE[lang] = catalog
    return catalog


def translate(key, lang=DEFAULT_LANG, **params):
    """
    Chaîne traduite pour `key`.

    Repli en cascade : langue demandée → anglais → la clé elle-même. Retourner la
    clé plutôt que de lever garde l'interface utilisable quand une traduction
    manque, et rend l'oubli visible pendant le développement.
    """
    text = load_catalog(lang).get(key)
    if text is None:
        text = load_catalog(DEFAULT_LANG).get(key)
    if text is None:
        return key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError):
        # Un paramètre oublié ne doit pas casser la page : on rend le gabarit brut.
        return text


def catalog_for_js(lang, prefix="js."):
    """Sous-ensemble destiné à `window.__I18N__`, anglais complété par la langue."""
    merged = dict(load_catalog(DEFAULT_LANG))
    merged.update(load_catalog(lang))
    return {k: v for k, v in merged.items() if k.startswith(prefix)}


def available_languages():
    """[{"code": "en", "label": "English"}, ...] — pour le sélecteur de langue."""
    return [{"code": code, "label": LANGUAGE_LABELS[code]} for code in LANGUAGES]
