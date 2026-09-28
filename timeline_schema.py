#!/usr/bin/env python3
"""
timeline_schema.py — Le contrat `ankigen.timeline/1` : constantes, validation, rapport.

Le modèle ne renvoie que du JSON ; tout ce qui se dessine ensuite dépend de ce
qui est accepté ici. La validation est donc stricte (`additionalProperties:
false` partout : une faute de frappe comme `lable` doit se voir) et bavarde :
chaque problème porte un chemin JSON Pointer et un code, qui devient la clé
i18n `timeline.err.<code>` / `timeline.warn.<code>`. Le rapport ne stocke que
des codes et des paramètres : les messages sont rendus au moment de l'affichage,
dans la langue de l'interface, alors que le prompt de correction les rend dans
la langue du document.

Elle est écrite à la main, sans la bibliothèque `jsonschema` (aucune dépendance
runtime nouvelle). Le JSON Schema livré (`static/schemas/timeline-v1.json`, pour
le `response_format` d'un runtime local) est GÉNÉRÉ depuis les mêmes constantes
par `json_schema()` ; un test vérifie que le fichier versionné n'a pas divergé.

    python timeline_schema.py --write-schema    # régénère static/schemas/timeline-v1.json

Module pur : ni Flask, ni I/O (hors la commande ci-dessus).
"""

import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

from i18n import DEFAULT_LANG, load_catalog, translate
from timeline_dates import PRECISIONS, DateError, parse_date, same_at_common_precision

SCHEMA_ID = "ankigen.timeline/1"
SCHEMA_FILE = Path(__file__).parent / "static" / "schemas" / "timeline-v1.json"

# Un document collé plus lourd n'est pas une frise : c'est une erreur de collage.
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

# Les motifs sont ancrés parce que le JSON Schema l'exige pour llama.cpp ; côté
# Python, re.fullmatch les applique sur la chaîne entière (un `$` seul
# accepterait un saut de ligne final). [0-9] plutôt que \d : \d accepte aussi
# les chiffres non latins.
ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,47}$"
COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
LANG_PATTERN = r"^[a-z]{2}$"
DATE_PATTERN = r"^-?[0-9]{1,5}(-[0-9]{2}(-[0-9]{2})?)?$"
END_PATTERN = r"^(-?[0-9]{1,5}(-[0-9]{2}(-[0-9]{2})?)?|present)$"
AS_OF_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"

ORIGINS = ("text", "model")

# Au-delà de ce ratio de pivots (importance 3), l'importance ne hiérarchise plus rien.
HIGH_IMPORTANCE_RATIO = 0.25
# Seuil de similarité des libellés pour un doublon probable (SequenceMatcher).
DUPLICATE_RATIO = 0.85


# ──────────────────────────────────────────────────────────────
# Spécification des champs
# ──────────────────────────────────────────────────────────────
# Chaque table donne l'ordre canonique des clés du document normalisé : deux
# documents équivalents s'écrivent donc à l'identique, octet pour octet.
#   type     : string | integer | boolean | array
#   max      : longueur maximale (string) ou nombre d'éléments (array)
#   fields   : table des champs des objets d'un tableau ; `items` pour des scalaires
#   date     : chaîne de date, analysée par timeline_dates (le motif sert au schéma)
#   line     : texte dessiné sur une ligne : espaces et sauts de ligne compressés
def _s(max_length=None, **extra):
    spec = {"type": "string", **extra}
    if max_length is not None:
        spec["max"] = max_length
    return spec


def _ref():
    return _s(pattern=ID_PATTERN, code="id_invalid")


def _id():
    return _s(pattern=ID_PATTERN, code="id_invalid", required=True)


def _date(pattern=DATE_PATTERN, required=True):
    return _s(pattern=pattern, date=True, required=required)


_COMMON_TAIL = {
    "precision": _s(enum=PRECISIONS, code="precision_invalid"),
    "approx": {"type": "boolean", "default": False},
    "importance": {"type": "integer", "min": 1, "max": 3, "default": 2},
    "origin": _s(enum=ORIGINS, default="text"),
    "description": _s(600),
    "date_text": _s(80),
    "source_quote": _s(240),
    "tags": {"type": "array", "max": 8, "items": _s(30, line=True)},
    "color": _s(pattern=COLOR_PATTERN, code="color_invalid"),
}

TRACK_FIELDS = {
    "id": _id(),
    "label": _s(40, required=True, line=True),
    "color": _s(pattern=COLOR_PATTERN, code="color_invalid"),
    "order": {"type": "integer", "min": 1, "max": 99},
}

ERA_FIELDS = {
    "id": _id(),
    "label": _s(60, required=True, line=True),
    "start": _date(),
    "end": _date(END_PATTERN),
    **_COMMON_TAIL,
}

PERIOD_FIELDS = {
    "id": _id(),
    "track": _ref(),
    "label": _s(80, required=True, line=True),
    "start": _date(),
    "end": _date(END_PATTERN),
    **_COMMON_TAIL,
}

EVENT_FIELDS = {
    "id": _id(),
    "track": _ref(),
    "label": _s(80, required=True, line=True),
    "date": _date(),
    **_COMMON_TAIL,
}

LINK_FIELDS = {
    "from": _s(pattern=ID_PATTERN, code="id_invalid", required=True),
    "to": _s(pattern=ID_PATTERN, code="id_invalid", required=True),
    "label": _s(40, line=True),
}

ROOT_FIELDS = {
    "schema": _s(const=SCHEMA_ID, code="schema_unknown", required=True),
    "title": _s(120, required=True, line=True),
    "subtitle": _s(200, line=True),
    "lang": _s(pattern=LANG_PATTERN, code="lang_invalid"),
    "as_of": _s(pattern=AS_OF_PATTERN, code="as_of_invalid"),
    "tracks": {"type": "array", "max": 12, "fields": TRACK_FIELDS},
    "eras": {"type": "array", "max": 20, "fields": ERA_FIELDS},
    "periods": {"type": "array", "max": 200, "fields": PERIOD_FIELDS},
    "events": {"type": "array", "max": 400, "fields": EVENT_FIELDS},
    # Réservé à la phase 8 (flèches cause → conséquence) : accepté et vérifié, pas dessiné.
    "links": {"type": "array", "max": 200, "fields": LINK_FIELDS},
}

# Tous les codes que ce module peut produire. Chacun a sa clé i18n (test).
ERROR_CODES = (
    "json_missing", "json_invalid", "json_trailing_comma", "json_smart_quotes", "too_large",
    "key_duplicate", "type_invalid", "required_missing", "key_unknown", "string_empty",
    "too_long", "too_many", "out_of_range", "enum_invalid", "schema_unknown", "id_invalid",
    "id_duplicate", "color_invalid", "lang_invalid", "track_missing", "track_unknown",
    "date_invalid", "date_year_zero", "date_month_invalid", "date_day_invalid",
    "present_not_allowed", "precision_invalid", "precision_mismatch", "as_of_invalid",
    "end_before_start", "document_empty", "eras_overlap", "link_unknown_ref",
)
WARNING_CODES = (
    "label_contains_year", "century_ambiguous", "millennium_ambiguous", "origin_model",
    "duplicate_probable", "importance_high_ratio", "track_empty", "track_undeclared",
)
NORMALIZATION_CODES = (
    "bom_removed", "fences_removed", "prose_removed", "year_as_number", "trimmed",
    "whitespace_collapsed",
)
# Indices plus précis que le message, quand ils existent (`timeline.hint.<code>`).
HINT_CODES = (
    "json_invalid", "json_trailing_comma", "json_smart_quotes", "key_unknown",
    "key_unknown_suggestion", "id_invalid", "date_invalid", "date_year_zero",
    "precision_mismatch", "present_not_allowed", "end_before_start", "eras_overlap",
    "century_ambiguous", "millennium_ambiguous", "label_contains_year",
)

_INVALID = object()   # valeur refusée (une erreur a été consignée)
_ABSENT = object()    # champ facultatif vide : traité comme absent


# ──────────────────────────────────────────────────────────────
# Rapport
# ──────────────────────────────────────────────────────────────
def pointer(*parts) -> str:
    """JSON Pointer (RFC 6901) : ("events", 3, "date") → "/events/3/date"."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


class _Issues:
    def __init__(self):
        self.errors, self.warnings, self.normalizations = [], [], []

    @staticmethod
    def _item(path, code, params, hint=None):
        item = {"path": path, "code": code, "params": params}
        if hint:
            item["hint"] = hint
        return item

    def error(self, path, code, hint=None, **params):
        self.errors.append(self._item(path, code, params, hint))

    def warn(self, path, code, hint=None, **params):
        self.warnings.append(self._item(path, code, params, hint))

    def norm(self, path, code):
        self.normalizations.append({"path": path, "code": code})

    def report(self, normalized):
        ok = not self.errors
        return {
            "ok": ok,
            "errors": self.errors,
            # Gardés même en cas d'erreur : le prompt de correction peut les reprendre.
            "warnings": self.warnings,
            "normalizations": self.normalizations,
            # Un document refusé n'a pas de forme normalisée : rien ne doit
            # pouvoir dessiner ou enregistrer un demi-document.
            "normalized": normalized if ok else None,
        }


def with_messages(report: dict, lang: str) -> dict:
    """Copie du rapport avec `message` (et `hint` rendu) dans la langue demandée."""
    known = load_catalog(DEFAULT_LANG)

    def render(item, prefix):
        out = dict(item)
        out["message"] = translate(f"timeline.{prefix}.{item['code']}", lang, **item.get("params", {}))
        hint = item.get("hint") or item["code"]
        if f"timeline.hint.{hint}" in known:
            out["hint"] = translate(f"timeline.hint.{hint}", lang, **item.get("params", {}))
        else:
            out.pop("hint", None)
        return out

    rendered = dict(report)
    rendered["errors"] = [render(e, "err") for e in report.get("errors", [])]
    rendered["warnings"] = [render(w, "warn") for w in report.get("warnings", [])]
    rendered["normalizations"] = [
        dict(n, message=translate(f"timeline.norm.{n['code']}", lang))
        for n in report.get("normalizations", [])
    ]
    return rendered


# ──────────────────────────────────────────────────────────────
# Texte brut → objet JSON (tolérances du §4.3)
# ──────────────────────────────────────────────────────────────
class _Object(dict):
    """dict qui se souvient des clés répétées : json.loads garderait la dernière en silence."""

    duplicates = ()


def _object_hook(pairs):
    obj = _Object()
    seen = []
    for key, value in pairs:
        if key in obj:
            seen.append(key)
        obj[key] = value
    obj.duplicates = tuple(seen)
    return obj


def _reject_constant(name):
    raise ValueError(f"{name} n'est pas un nombre JSON")


def _position(raw, pos):
    line = raw.count("\n", 0, pos) + 1
    column = pos - (raw.rfind("\n", 0, pos) + 1) + 1
    start = raw.rfind("\n", 0, pos) + 1
    end = raw.find("\n", pos)
    text = raw[start:end if end != -1 else len(raw)].strip()
    return line, column, text[:80]


def _json_error(issues, raw, offset, error):
    pos = offset + getattr(error, "pos", 0)
    line, column, excerpt = _position(raw, pos)
    char = raw[pos] if pos < len(raw) else ""
    before = raw[offset:pos].rstrip()
    after = raw[pos + 1:].lstrip()[:1]
    if char and char in "“”„«»":
        code = "json_smart_quotes"
    elif (char and char in "}]" and before.endswith(",")) or (char == "," and after in ("}", "]")):
        # Python ≤ 3.12 s'arrête sur le crochet ; 3.13 signale la virgule elle-même.
        code = "json_trailing_comma"
    else:
        code = "json_invalid"
    issues.error("", code, line=line, column=column, excerpt=excerpt)


def parse_raw(raw, issues=None):
    """
    Réponse collée → (objet | None, _Issues).

    Tolère le BOM, les clôtures ```json et le texte avant le premier `{` ou après
    le dernier `}` : c'est ce que les modèles ajoutent le plus souvent. Rien d'autre
    n'est réparé (guillemets typographiques, virgules finales) : c'est au prompt
    de correction de s'en charger, avec la ligne et la colonne fautives.
    """
    issues = issues or _Issues()
    if not isinstance(raw, str):
        issues.error("", "type_invalid", expected="string")
        return None, issues
    size = len(raw.encode("utf-8"))
    if size > MAX_DOCUMENT_BYTES:
        issues.error("", "too_large", size=size // 1024, max=MAX_DOCUMENT_BYTES // 1024)
        return None, issues
    if raw.startswith("﻿"):
        raw = raw[1:]
        issues.norm("", "bom_removed")
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end < start:
        issues.error("", "json_missing")
        return None, issues
    outside = raw[:start] + "\n" + raw[end + 1:]
    if "```" in outside:
        issues.norm("", "fences_removed")
    if re.sub(r"```[A-Za-z]*", "", outside).strip():
        issues.norm("", "prose_removed")
    try:
        obj = json.loads(raw[start:end + 1], object_pairs_hook=_object_hook,
                         parse_constant=_reject_constant)
    except json.JSONDecodeError as error:
        _json_error(issues, raw, start, error)
        return None, issues
    except (ValueError, RecursionError):  # NaN, Infinity ; imbrication absurde
        line, column, excerpt = _position(raw, start)
        issues.error("", "json_invalid", line=line, column=column, excerpt=excerpt)
        return None, issues
    return obj, issues


# ──────────────────────────────────────────────────────────────
# Valeurs
# ──────────────────────────────────────────────────────────────
def _string(issues, path, value, spec):
    if spec.get("date") and isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
        issues.norm(path, "year_as_number")
    if not isinstance(value, str):
        issues.error(path, "type_invalid", expected="string")
        return _INVALID
    cleaned = value.strip()
    if cleaned != value:
        issues.norm(path, "trimmed")
    if spec.get("line"):
        # Le SVG compresse de toute façon les espaces : la mesure doit porter sur
        # le texte réellement affiché.
        collapsed = " ".join(cleaned.split())
        if collapsed != cleaned:
            issues.norm(path, "whitespace_collapsed")
        cleaned = collapsed
    if not cleaned:
        if spec.get("required"):
            issues.error(path, "string_empty")
            return _INVALID
        return _ABSENT
    if "const" in spec and cleaned != spec["const"]:
        issues.error(path, spec.get("code", "enum_invalid"), value=cleaned)
        return _INVALID
    if "enum" in spec and cleaned not in spec["enum"]:
        issues.error(path, spec.get("code", "enum_invalid"), value=cleaned,
                     allowed=", ".join(spec["enum"]))
        return _INVALID
    if "pattern" in spec and not spec.get("date") and not re.fullmatch(spec["pattern"], cleaned):
        issues.error(path, spec["code"], value=cleaned)
        return _INVALID
    if "max" in spec and len(cleaned) > spec["max"]:
        issues.error(path, "too_long", length=len(cleaned), max=spec["max"])
        return _INVALID
    return cleaned


def _value(issues, path, value, spec):
    kind = spec["type"]
    if kind == "string":
        return _string(issues, path, value, spec)
    if kind == "boolean":
        if not isinstance(value, bool):
            issues.error(path, "type_invalid", expected="boolean")
            return _INVALID
        return value
    if kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            issues.error(path, "type_invalid", expected="integer")
            return _INVALID
        if not spec["min"] <= value <= spec["max"]:
            issues.error(path, "out_of_range", value=value, min=spec["min"], max=spec["max"])
            return _INVALID
        return value
    # array
    if not isinstance(value, list):
        issues.error(path, "type_invalid", expected="array")
        return _INVALID
    if len(value) > spec["max"]:
        issues.error(path, "too_many", count=len(value), max=spec["max"])
        return _INVALID
    out = []
    for i, item in enumerate(value):
        if "fields" in spec:
            checked = _object(issues, f"{path}/{i}", item, spec["fields"])
        else:
            checked = _value(issues, f"{path}/{i}", item, spec["items"])
            if checked is _ABSENT:
                continue
        out.append(checked)
    return _INVALID if any(v is _INVALID for v in out) else out


def _object(issues, path, value, fields):
    """Objet → dict normalisé dans l'ordre canonique, ou _INVALID."""
    if not isinstance(value, dict):
        issues.error(path, "type_invalid", expected="object")
        return _INVALID
    for key in getattr(value, "duplicates", ()):
        issues.error(pointer_join(path, key), "key_duplicate", name=key)
    for key in value:
        if key not in fields:
            close = difflib.get_close_matches(key, list(fields), n=1, cutoff=0.6)
            if close:
                issues.error(pointer_join(path, key), "key_unknown",
                             hint="key_unknown_suggestion", name=key, suggestion=close[0])
            else:
                issues.error(pointer_join(path, key), "key_unknown", name=key)
    out = {}
    valid = True
    for key, spec in fields.items():
        member = pointer_join(path, key)
        if key not in value:
            if spec.get("required"):
                issues.error(member, "required_missing", name=key)
                valid = False
            elif "default" in spec:
                out[key] = spec["default"]
            continue
        checked = _value(issues, member, value[key], spec)
        if checked is _INVALID:
            valid = False
        elif checked is _ABSENT:
            if "default" in spec:
                out[key] = spec["default"]
        else:
            out[key] = checked
    return out if valid else _INVALID


def pointer_join(path, key):
    return path + pointer(key)


# ──────────────────────────────────────────────────────────────
# Comparaison de libellés (doublons ; réutilisée par la fusion)
# ──────────────────────────────────────────────────────────────
def comparable_label(label: str) -> str:
    """Forme de comparaison : sans accents, en minuscules, ponctuation ramenée à des espaces."""
    text = unicodedata.normalize("NFKD", label or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text).split())


def similar_labels(a: str, b: str, threshold: float = DUPLICATE_RATIO) -> bool:
    matcher = difflib.SequenceMatcher(None, comparable_label(a), comparable_label(b))
    return matcher.real_quick_ratio() >= threshold and matcher.quick_ratio() >= threshold \
        and matcher.ratio() >= threshold


# ──────────────────────────────────────────────────────────────
# Document
# ──────────────────────────────────────────────────────────────
def _parse(issues, path, text, precision, *, allow_present=False, as_of=None):
    try:
        date = parse_date(text, precision, allow_present=allow_present, as_of=as_of)
    except DateError as error:
        issues.error(path, error.code, **error.params)
        return None
    if date.ambiguous:
        size = 100 if date.precision == "century" else 1000
        issues.warn(path, f"{date.precision}_ambiguous", value=text,
                    first=size * (date.unit - 1) + 1)
    return date


def _label_year_warning(issues, path, label, dates):
    for date in dates:
        if date is None or date.present or date.precision not in ("day", "month", "year", "decade"):
            continue
        year = abs(date.year)
        if re.search(rf"(?<![0-9]){year}(?![0-9])", label):
            issues.warn(pointer_join(path, "label"), "label_contains_year", year=year)
            return


def validate(doc, *, default_lang=DEFAULT_LANG, issues=None) -> dict:
    """
    Objet JSON (déjà décodé) → rapport {ok, errors, warnings, normalizations, normalized}.

    Toutes les erreurs sont collectées en un passage : le prompt de correction doit
    pouvoir les lister toutes, pas une par aller-retour avec le modèle.
    """
    issues = issues or _Issues()
    root = _object(issues, "", doc, ROOT_FIELDS)
    if root is _INVALID:
        # On continue quand même sur les parties lisibles pour tout signaler d'un coup.
        root = None

    source = doc if isinstance(doc, dict) else {}
    # `as_of` sert de référence à « present ». Sa forme est vérifiée par _object ;
    # reste le jour qui n'existe pas (« 2026-02-30 »).
    as_of = source.get("as_of").strip() if isinstance(source.get("as_of"), str) else None
    if as_of is not None:
        if not re.fullmatch(AS_OF_PATTERN, as_of):
            as_of = None
        else:
            try:
                parse_date(as_of)
            except DateError:
                issues.error("/as_of", "as_of_invalid", value=as_of)
                as_of = None

    ids = {}

    def claim(path, element_id):
        if element_id in ids:
            issues.error(pointer_join(path, "id"), "id_duplicate", id=element_id, other=ids[element_id])
        else:
            ids[element_id] = path

    tracks = _list(source, "tracks")
    track_ids = []
    for i, track in enumerate(tracks):
        if isinstance(track, dict) and isinstance(track.get("id"), str):
            claim(pointer("tracks", i), track["id"].strip())
            track_ids.append(track["id"].strip())
    declared = bool(track_ids)

    parsed = {"eras": [], "periods": [], "events": []}
    used_tracks = set()
    for kind in ("eras", "periods", "events"):
        for i, element in enumerate(_list(source, kind)):
            if not isinstance(element, dict):
                continue
            path = pointer(kind, i)
            element_id = element.get("id").strip() if isinstance(element.get("id"), str) else None
            if element_id:
                claim(path, element_id)
            if kind != "eras":
                track = element.get("track")
                if isinstance(track, str) and track.strip():
                    if not declared:
                        issues.warn(pointer_join(path, "track"), "track_undeclared")
                    elif track.strip() not in track_ids:
                        close = difflib.get_close_matches(track.strip(), track_ids, n=1, cutoff=0.6)
                        suggestion = {"hint": "key_unknown_suggestion", "suggestion": close[0]} if close else {}
                        issues.error(pointer_join(path, "track"), "track_unknown",
                                     value=track.strip(), **suggestion)
                    used_tracks.add(track.strip())
                elif declared and (track is None or isinstance(track, str)):
                    # Absente ou vide ; une valeur d'un autre type est déjà une erreur de type.
                    issues.error(path, "track_missing")
            parsed[kind].append((i, element_id, _element_dates(issues, path, element, kind, as_of)))

    for i, link in enumerate(_list(source, "links")):
        if isinstance(link, dict):
            for end in ("from", "to"):
                ref = link.get(end)
                if isinstance(ref, str) and ref.strip() and ref.strip() not in ids:
                    issues.error(pointer("links", i, end), "link_unknown_ref", value=ref.strip())

    if not _list(source, "events") and not _list(source, "periods") and isinstance(doc, dict):
        issues.error("", "document_empty")

    _check_eras(issues, source, parsed["eras"])

    normalized = None
    if root is not None and not issues.errors:
        normalized = dict(root)
        normalized.setdefault("lang", default_lang)
        for key in ("tracks", "eras", "periods", "events", "links"):
            normalized.setdefault(key, [])
        normalized = {key: normalized[key] for key in ROOT_FIELDS if key in normalized}
        _document_warnings(issues, normalized, parsed, declared, used_tracks)
    return issues.report(normalized)


def _list(source, key):
    value = source.get(key)
    return value if isinstance(value, list) else []


def _element_dates(issues, path, element, kind, as_of):
    """Analyse les dates d'un élément ; vérifie l'ordre des bornes. → dict de TimelineDate | None."""
    # Une précision invalide est déjà signalée par _object : on analyse alors la
    # date avec la précision que dit sa chaîne, pour ne pas multiplier les erreurs.
    raw_precision = element.get("precision")
    precision = None
    if isinstance(raw_precision, str) and raw_precision.strip() in PRECISIONS:
        precision = raw_precision.strip()

    def text_of(key):
        value = element.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return value.strip() if isinstance(value, str) else None

    dates = {}
    if kind == "events":
        text = text_of("date")
        if text:
            dates["date"] = _parse(issues, pointer_join(path, "date"), text, precision)
    else:
        start, end = text_of("start"), text_of("end")
        if start:
            dates["start"] = _parse(issues, pointer_join(path, "start"), start, precision)
        if end:
            end_precision = None if end == "present" else precision
            dates["end"] = _parse(issues, pointer_join(path, "end"), end, end_precision,
                                  allow_present=True, as_of=as_of)
        if dates.get("start") and dates.get("end") and dates["end"].t1 <= dates["start"].t0:
            issues.error(pointer_join(path, "end"), "end_before_start", start=start, end=end)
    label = element.get("label")
    if isinstance(label, str):
        _label_year_warning(issues, path, label, dates.values())
    return dates


def _check_eras(issues, source, eras):
    """
    Deux ères ne se recouvrent pas, sauf d'une unité au point de contact.

    « 1870–1914 » puis « 1914–1945 » partagent l'année 1914 (fin inclusive) : c'est
    la façon naturelle de l'écrire, tolérée et coupée au dessin.
    """
    spans = []
    for i, element_id, dates in eras:
        start, end = dates.get("start"), dates.get("end")
        if start and end:
            spans.append((start.t0, end.t1, i, element_id, start, end))
    spans.sort(key=lambda span: (span[0], span[1], span[2]))
    reach = None
    for t0, t1, i, element_id, start, end in spans:
        if reach is not None and t0 < reach[0]:
            overlap = min(reach[0], t1) - t0
            unit = max(reach[1].t1 - reach[1].t0, start.t1 - start.t0)
            if overlap > unit + 1e-9:
                issues.error(pointer("eras", i), "eras_overlap", other=reach[2] or "")
        if reach is None or t1 > reach[0]:
            reach = (t1, end, element_id)


def _document_warnings(issues, doc, parsed, declared, used_tracks):
    for kind in ("eras", "periods", "events"):
        for i, element in enumerate(doc[kind]):
            if element.get("origin") == "model":
                issues.warn(pointer(kind, i), "origin_model")

    for i, track in enumerate(doc["tracks"]):
        if track["id"] not in used_tracks:
            issues.warn(pointer("tracks", i), "track_empty", value=track["id"])

    # Doublons probables : même piste, même date à la précision commune, libellés
    # proches. Le même libellé dans deux pistes est un parallèle voulu (« Passage à
    # l'euro » pour deux pays), pas une répétition.
    for kind, key in (("events", "date"), ("periods", "start")):
        entries = [(i, doc[kind][i]["label"], dates.get(key), dates.get("end"))
                   for i, _, dates in parsed[kind] if dates.get(key)]
        entries.sort(key=lambda e: (e[2].t0, e[0]))
        for a in range(len(entries)):
            ia, label_a, date_a, end_a = entries[a]
            for b in range(a + 1, len(entries)):
                ib, label_b, date_b, end_b = entries[b]
                # Triées par début. Deux dates égales à la précision commune se
                # recoupent (la plus grossière contient l'autre) : dès qu'une date
                # commence après la fin de `a`, les suivantes aussi.
                if date_b.t0 >= date_a.t1:
                    break
                if doc[kind][ia].get("track") != doc[kind][ib].get("track"):
                    continue
                if not same_at_common_precision(date_a, date_b):
                    continue
                if kind == "periods" and not (end_a and end_b and same_at_common_precision(end_a, end_b)):
                    continue
                if similar_labels(label_a, label_b):
                    first, second = sorted((ia, ib))
                    issues.warn(pointer(kind, second), "duplicate_probable",
                                other=doc[kind][first]["id"])

    elements = doc["events"] + doc["periods"]
    pivots = sum(1 for element in elements if element["importance"] == 3)
    if elements and pivots > max(1, HIGH_IMPORTANCE_RATIO * len(elements)):
        issues.warn("", "importance_high_ratio", count=pivots, total=len(elements))


def validate_raw(raw, *, default_lang=DEFAULT_LANG) -> dict:
    """Texte collé → rapport complet (tolérances de collage comprises)."""
    obj, issues = parse_raw(raw)
    if obj is None:
        return issues.report(None)
    return validate(obj, default_lang=default_lang, issues=issues)


# ──────────────────────────────────────────────────────────────
# JSON Schema (dérivé des constantes ci-dessus)
# ──────────────────────────────────────────────────────────────
def _object_schema(fields):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [key for key, field in fields.items() if field.get("required")],
        "properties": {key: _schema_of(field) for key, field in fields.items()},
    }


def _schema_of(spec):
    out = {"type": spec["type"]}
    if spec["type"] == "string":
        if "const" in spec:
            out["const"] = spec["const"]
        if "enum" in spec:
            out["enum"] = list(spec["enum"])
        if "pattern" in spec:
            out["pattern"] = spec["pattern"]
        if "max" in spec:
            out["maxLength"] = spec["max"]
    elif spec["type"] == "integer":
        out["minimum"], out["maximum"] = spec["min"], spec["max"]
    elif spec["type"] == "array":
        out["maxItems"] = spec["max"]
        out["items"] = _object_schema(spec["fields"]) if "fields" in spec else _schema_of(spec["items"])
    return out


def json_schema() -> dict:
    """
    Le JSON Schema 2020-12 du contrat, limité au sous-ensemble que les grammaires
    de llama.cpp savent compiler (type, enum, const, required, properties,
    additionalProperties: false, maxLength, maxItems, minimum, maximum, pattern).
    Les règles qui ne s'y expriment pas (unicité des id, pistes existantes, fin
    après le début, textes non vides…) restent du ressort de validate().
    """
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": SCHEMA_ID}
    schema.update(_object_schema(ROOT_FIELDS))
    return schema


def schema_text() -> str:
    return json.dumps(json_schema(), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    if "--write-schema" in sys.argv:
        SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_FILE.write_text(schema_text(), encoding="utf-8")
        print(f"[schema] {SCHEMA_FILE}")
    else:
        print(__doc__)
