#!/usr/bin/env python3
"""
timeline_extract.py — Extraction d'une frise par un modèle (§6.7).

L'extraction passe par une interface, `TimelineExtractor` : préparer la requête
(le prompt, le schéma), puis lire la réponse (nettoyage, validation, citations).
La v1 n'en a qu'une implémentation, `ManualExtractor` : l'utilisateur copie le
prompt dans Claude et colle la réponse. Quand l'agent local existera, un
`LocalExtractor` enverra `static/schemas/timeline-v1.json` en `response_format`,
et réutilisera `parse_response` et le prompt de correction pour ses nouvelles
tentatives.

On y trouve aussi ce qui relie les réponses d'une extraction paragraphe par
paragraphe à la frise : l'état de chaque paragraphe, et la fusion.

Module pur : ni Flask ni I/O (hors la lecture des gabarits de prompt).
"""

import hashlib
import json

import timeline_merge
import timeline_prompt
import timeline_quotes
import timeline_schema

# États d'un paragraphe en extraction paragraphe par paragraphe.
CHUNK_STATUSES = ("pending", "ok", "empty", "error")


class TimelineExtractor:
    """Interface : une implémentation prépare la requête, puis lit la réponse du modèle."""

    name = "abstract"

    def build_request(self, source_text, lang, mode="strict", **options) -> dict:
        raise NotImplementedError

    def parse_response(self, raw, *, lang, source_text=None, chunk=False) -> tuple:
        raise NotImplementedError


class ManualExtractor(TimelineExtractor):
    """Copier-coller : le prompt est affiché, la réponse arrive par le presse-papiers."""

    name = "manual"

    def build_request(self, source_text, lang, mode="strict", *, title="", skill=False, chunk=False,
                      tracks=()) -> dict:
        prompt = timeline_prompt.extraction_prompt(source_text, lang=lang, mode=mode, title=title,
                                                   skill=skill, chunk=chunk, tracks=tracks)
        return {"prompt": prompt, "schema": timeline_schema.json_schema(), "mode": mode,
                "chars": len(prompt), "tokens": timeline_prompt.estimate_tokens(prompt)}

    def parse_response(self, raw, *, lang, source_text=None, chunk=False) -> tuple:
        """
        Texte collé → (document normalisé | None, rapport).

        Le rapport porte `status` : `ok`, `error`, ou `empty` pour un paragraphe
        sans date (la seule erreur est alors le document vide, réponse normale
        d'un paragraphe qui n'a rien à dater). Si le texte source est connu, les
        citations sont vérifiées.
        """
        report = timeline_schema.validate_raw(raw, default_lang=lang)
        report["status"] = response_status(report, chunk=chunk)
        if source_text:
            report = timeline_quotes.annotate(report, source_text)
        return report["normalized"], report

    def correction_request(self, report, *, lang, include_warnings=False) -> dict:
        prompt = timeline_prompt.correction_prompt(report, lang=lang, include_warnings=include_warnings)
        return {"prompt": prompt, "errors": len(report.get("errors") or []),
                "warnings": len(report.get("warnings") or [])}


def response_status(report, *, chunk=False) -> str:
    if report["ok"]:
        return "ok"
    if chunk and [e["code"] for e in report["errors"]] == ["document_empty"]:
        return "empty"
    return "error"


# ──────────────────────────────────────────────────────────────
# Paragraphe par paragraphe
# ──────────────────────────────────────────────────────────────
def document_hash(doc) -> str:
    """Empreinte d'un document : repère une frise retouchée depuis la dernière fusion."""
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def chunk_order(record) -> list:
    return [span[0] for span in record["source"].get("spans") or []]


def chunk_entry(record, chunk_id) -> dict:
    return record["extraction"]["per_chunk"].get(str(chunk_id)) or {"status": "pending"}


def merge_record(record, *, lang) -> tuple:
    """
    Fusionne les réponses valides des paragraphes → (rapport de validation du
    document fusionné, rapport de fusion). Chaque réponse est revalidée depuis
    son texte brut : le brut est la seule chose stockée, la validation est
    déterministe.
    """
    parts = []
    for chunk_id in chunk_order(record):
        entry = chunk_entry(record, chunk_id)
        if entry.get("status") != "ok" or not entry.get("raw"):
            continue
        report = timeline_schema.validate_raw(entry["raw"], default_lang=lang)
        if report["ok"]:
            parts.append((chunk_id, report["normalized"]))
    merge_state = record["extraction"].get("merge") or {}
    title = record.get("title") or (record.get("data") or {}).get("title") or ""
    doc, merge_report = timeline_merge.merge(parts, title=title, lang=lang,
                                             keep_separate=merge_state.get("keep_separate") or ())
    if not parts:
        return None, merge_report
    return timeline_schema.validate(doc, default_lang=lang), merge_report
