#!/usr/bin/env python3
"""
timeline_store.py — Persistance des frises dans DATA_DIR/timelines/.

Une frise est un fichier autonome : elle garde un instantané de son texte source,
pour vérifier les citations et reconstruire les prompts même si le projet
d'origine change ou disparaît. Supprimer un projet ne supprime donc pas ses
frises.

Elles ne vivent JAMAIS dans projects/ : list_projects() y prend tous les *.json
pour des projets.

Format (version 1) :
{
  "version": 1, "id": "mondialisation-3f9a", "created_at", "updated_at",
  "title": "…", "lang": "fr",          // avant la première extraction ; ensuite data.title prime
  "source": {"kind", "project_id", "deck_path", "chunk_ids", "text_hash"},
  "source_text": "…",
  "extraction": {"mode": "strict", "strategy": "single", "per_chunk": {}},
  "data": {…document ankigen.timeline/1 normalisé…} | null,
  "raw_responses": [ …5 derniers collages bruts… ],
  "render_options": {}, "card_options": {}, "cards_deck": null, "disabled_cards": []
}

L'identifiant arrive par l'URL : il est validé avant TOUT accès disque.
"""

import datetime
import hashlib
import json
import os
import re
import secrets
import tempfile
import unicodedata
from pathlib import Path

from paths import TIMELINES_DIR

TIMELINE_VERSION = 1
TIMELINE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
SOURCE_KINDS = ("project", "chapter", "chunk", "text", "import")
EXTRACTION_MODES = ("strict", "enriched")
EXTRACTION_STRATEGIES = ("single", "per_chunk")
MAX_SOURCE_CHARS = 200_000
MAX_RAW_RESPONSES = 5

# Noms de périphériques Windows : « con.json » ne désigne pas un fichier, et
# l'ouvrir peut bloquer sur la console. Un identifiant généré ne les produit
# jamais (suffixe hexadécimal), mais une URL peut les demander.
_WINDOWS_DEVICES = {"con", "prn", "aux", "nul"} | {f"{p}{n}" for p in ("com", "lpt") for n in range(1, 10)}


class TimelineStoreError(Exception):
    """Fichier de frise illisible : signalé, jamais pris pour une frise absente."""


class TimelineIdError(TimelineStoreError, ValueError):
    """Identifiant refusé avant tout accès disque."""


# ──────────────────────────────────────────────────────────────
# Identifiants et chemins
# ──────────────────────────────────────────────────────────────
def valid_id(tid) -> bool:
    return (isinstance(tid, str) and TIMELINE_ID_RE.fullmatch(tid) is not None
            and tid not in _WINDOWS_DEVICES)


def timeline_path(tid) -> Path:
    if not valid_id(tid):
        raise TimelineIdError(f"identifiant de frise refusé : {tid!r}")
    return TIMELINES_DIR / f"{tid}.json"


def slugify_title(title: str, max_length: int = 59) -> str:
    """« La dynamique de la mondialisation économique » → « la-dynamique-de-la-mondialisation-economique »."""
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug[:max_length].rstrip("-") or "timeline"


def new_timeline_id(title: str) -> str:
    """Slug du titre suivi de 4 caractères hexadécimaux, libre sur le disque."""
    slug = slugify_title(title)
    while True:
        tid = f"{slug}-{secrets.token_hex(2)}"
        if not timeline_path(tid).exists():
            return tid


def text_hash(text: str) -> str:
    """Empreinte du texte source : détecte qu'un projet a changé depuis l'extraction."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────────────────────────────────────
# Enregistrements
# ──────────────────────────────────────────────────────────────
def _source(source, source_text):
    source = dict(source or {})
    kind = source.get("kind", "import")
    if kind not in SOURCE_KINDS:
        raise ValueError(f"source de frise inconnue : {kind!r}")
    return {
        "kind": kind,
        "project_id": source.get("project_id"),
        "deck_path": source.get("deck_path"),
        "chunk_ids": list(source.get("chunk_ids") or []),
        "text_hash": text_hash(source_text),
    }


def new_record(*, title="", lang=None, data=None, source=None, source_text="",
               extraction=None, cards_deck=None, now=None) -> dict:
    """Nouvel enregistrement complet. Le texte source est plafonné (§12 : 200 000 caractères)."""
    source_text = source_text or ""
    if len(source_text) > MAX_SOURCE_CHARS:
        raise ValueError(f"texte source trop long : {len(source_text)} > {MAX_SOURCE_CHARS}")
    stamp = now or _now()
    return normalize_record({
        "version": TIMELINE_VERSION,
        "id": None,
        "created_at": stamp,
        "updated_at": stamp,
        "title": title or (data or {}).get("title") or "",
        "lang": lang or (data or {}).get("lang"),
        "source": _source(source, source_text),
        "source_text": source_text,
        "extraction": extraction,
        "data": data,
        "cards_deck": cards_deck,
    })


def normalize_record(record: dict) -> dict:
    """Complète un enregistrement lu sur disque (champs ajoutés plus tard, fichier écrit à la main)."""
    record = dict(record)
    record["version"] = TIMELINE_VERSION
    record.setdefault("id", None)
    record.setdefault("created_at", None)
    record.setdefault("updated_at", record["created_at"])
    record.setdefault("title", "")
    record.setdefault("lang", None)
    source_text = record.get("source_text") or ""
    record["source_text"] = source_text
    source = record.get("source") or {}
    record["source"] = dict(_source(source, source_text), text_hash=source.get("text_hash")
                            or text_hash(source_text))
    extraction = dict(record.get("extraction") or {})
    extraction.setdefault("mode", "strict")
    extraction.setdefault("strategy", "single")
    extraction.setdefault("per_chunk", {})
    record["extraction"] = extraction
    record.setdefault("data", None)
    record["raw_responses"] = list(record.get("raw_responses") or [])[-MAX_RAW_RESPONSES:]
    record["render_options"] = dict(record.get("render_options") or {})
    record["card_options"] = dict(record.get("card_options") or {})
    record.setdefault("cards_deck", None)
    record["disabled_cards"] = list(record.get("disabled_cards") or [])
    return record


def display_title(record: dict) -> str:
    return ((record.get("data") or {}).get("title") or record.get("title") or "").strip()


def push_raw_response(record: dict, raw: str) -> None:
    """Garde les derniers collages bruts, pour l'audit d'une extraction ratée."""
    record["raw_responses"] = (list(record.get("raw_responses") or []) + [raw])[-MAX_RAW_RESPONSES:]


# ──────────────────────────────────────────────────────────────
# Disque
# ──────────────────────────────────────────────────────────────
def load_timeline(tid):
    """Enregistrement, ou None s'il n'existe pas. Un fichier illisible lève TimelineStoreError."""
    path = timeline_path(tid)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TimelineStoreError(f"frise illisible {tid} : {error}") from error
    if not isinstance(record, dict):
        raise TimelineStoreError(f"frise illisible {tid} : objet JSON attendu")
    try:
        record = normalize_record(record)
    except ValueError as error:   # source inconnue, fichier retouché à la main
        raise TimelineStoreError(f"frise illisible {tid} : {error}") from error
    record["id"] = tid
    return record


def save_timeline(tid, record: dict) -> dict:
    """
    Écriture atomique : fichier temporaire dans le même dossier, puis os.replace.

    Une coupure en cours d'écriture laisse l'ancienne version intacte au lieu d'un
    JSON tronqué. L'identifiant est celui du chemin, jamais celui du contenu.
    """
    path = timeline_path(tid)
    record = normalize_record(record)
    record["id"] = tid
    record["updated_at"] = _now()
    record["created_at"] = record["created_at"] or record["updated_at"]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{tid}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return record


def create_timeline(**fields):
    """(identifiant, enregistrement) d'une nouvelle frise, déjà écrite sur disque."""
    record = new_record(**fields)
    tid = new_timeline_id(display_title(record))
    return tid, save_timeline(tid, record)


def delete_timeline(tid) -> bool:
    path = timeline_path(tid)
    if not path.exists():
        return False
    path.unlink()
    return True


def list_timelines() -> list:
    """
    Résumés pour le tableau de bord, du plus récent au plus ancien.

    Un fichier illisible ou étranger est ignoré : il ne doit jamais empêcher
    d'afficher les autres frises.
    """
    if not TIMELINES_DIR.is_dir():
        return []
    out = []
    for file in sorted(TIMELINES_DIR.glob("*.json")):
        if not valid_id(file.stem):
            continue
        try:
            record = load_timeline(file.stem)
        except TimelineStoreError:
            continue
        data = record.get("data") or {}
        out.append({
            "id": record["id"],
            "title": display_title(record),
            "source_kind": record["source"]["kind"],
            "project_id": record["source"]["project_id"],
            "events": len(data.get("events") or []),
            "periods": len(data.get("periods") or []),
            "updated_at": record["updated_at"],
        })
    out.sort(key=lambda item: item["id"])
    out.sort(key=lambda item: item["updated_at"] or "", reverse=True)
    return out
