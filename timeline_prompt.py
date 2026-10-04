#!/usr/bin/env python3
"""
timeline_prompt.py — Texte source d'une frise et prompts d'extraction (§6.1 à §6.6).

Une portée (un paragraphe, un chapitre, tout le cours) devient un texte source :
chaque chunk y est précédé de son chemin de titres, pour que le modèle ait le
contexte. Ce texte est gardé en instantané dans la frise, avec la position de
chaque chunk, pour reconstruire les prompts et vérifier les citations même si le
projet change ou disparaît.

Le prompt est assemblé depuis `prompt_templates/<lang>/timeline_extract.md`
(écart E1), un fichier versionné et relisible sans toucher au code. Le contrat
de la frise appartient à l'app : il est toujours dans le prompt copié, sauf si
l'utilisateur a installé le Skill, fait des mêmes blocs. Les limites du contrat
ne sont jamais recopiées dans les gabarits : elles viennent de timeline_schema.

Module pur : il lit ses gabarits, rien d'autre (ni Flask ni projet sur disque).
"""

import math
import re

import paths
from i18n import DEFAULT_LANG
from timeline_schema import (
    ERA_FIELDS,
    EVENT_FIELDS,
    ID_PATTERN,
    ROOT_FIELDS,
    SCHEMA_ID,
    TRACK_FIELDS,
    with_messages,
)

TEMPLATE_DIR = paths.APP_DIR / "prompt_templates"
TEMPLATE_NAME = "timeline_extract.md"

# D1 : au-delà de ce texte source, le mode par défaut devient « paragraphe par
# paragraphe + fusion » ; un chapitre entier collé d'un coup fait survoler le modèle.
SINGLE_PROMPT_MAX_CHARS = 25_000
# Estimation grossière, affichée comme telle (« ≈ ») : un token vaut environ
# quatre caractères en anglais, un peu moins en français.
CHARS_PER_TOKEN = 4
MODES = ("strict", "enriched")

_BLOCK_RE = re.compile(r"^<!-- @([a-z_]+) -->$")
_VAR_RE = re.compile(r"\{\{([a-z_]+)\}\}")
# Indications destinées aux cartes (« écris {{IMG:1}} dans une carte… ») : sans
# objet pour une frise, et elles inviteraient le modèle à recopier les marqueurs.
_CARD_HINT_RE = re.compile(r"^\(.*\{\{(?:IMG|TABLE):\d+\}\}.*\)$")
# Numérotation de plan en tête d'un titre (« I - », « B) », « 2. », « CH1: ») et
# suffixe de doublon (« (1) ») : utiles au deck, pas au titre d'une frise.
_OUTLINE_RE = re.compile(r"^(?:[A-Z]{1,3}\d+|[IVXLC]+|[A-Za-z]|\d+)\s*[-–—).:]\s+")
_DUPLICATE_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")
_YEAR_RE = re.compile(r"(?<![\d.,])(?:1\d{3}|20\d{2})(?!\d)")
_CENTURY_RE = re.compile(r"\b[IVXL]+(?:e|er|ème|è)\s+siècle|\b\d{1,2}(?:st|nd|rd|th)\s+century", re.I)


# ──────────────────────────────────────────────────────────────
# Decks et portées
# ──────────────────────────────────────────────────────────────
def deck_segments(deck) -> list:
    return [segment.strip() for segment in (deck or "").split("::") if segment.strip()]


def in_chapter(deck, chapter) -> bool:
    """
    Le chunk appartient-il au chapitre ? Comparaison segment par segment (E5) :
    `A::B` contient `A::B` et `A::B::C`, mais pas `A::Bretagne`.
    """
    chapter_segments = deck_segments(chapter)
    return bool(chapter_segments) and deck_segments(deck)[:len(chapter_segments)] == chapter_segments


def heading_path(deck, deck_prefix="") -> str:
    """« Économie::Mondialisation::Les phases » → « Mondialisation › Les phases »."""
    segments = deck_segments(deck)
    prefix = deck_segments(deck_prefix)
    if prefix and segments[:len(prefix)] == prefix:
        segments = segments[len(prefix):]
    return " › ".join(segments)


def clean_title(segment: str) -> str:
    """« I - Quand convient-il… », « CH1: La dynamique…(1) » → le titre seul."""
    text = _DUPLICATE_SUFFIX_RE.sub("", (segment or "").strip())
    return _OUTLINE_RE.sub("", text, count=1).strip() or text


def clean_chunk_text(text: str) -> str:
    lines = [line for line in (text or "").splitlines() if not _CARD_HINT_RE.match(line.strip())]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_WORDS_RE = re.compile(r"[a-zà-ÿ]+")
# Mots outils les plus fréquents de chaque langue proposée : assez pour trancher
# entre le français et l'anglais d'un texte de cours, sans dépendance.
_FUNCTION_WORDS = {
    "fr": {"le", "la", "les", "des", "du", "de", "et", "est", "une", "un", "en", "que", "qui", "dans", "pour",
           "par", "sur", "au", "aux", "ne", "pas", "se", "sont", "avec", "il", "elle"},
    "en": {"the", "of", "and", "to", "in", "is", "a", "that", "for", "on", "with", "as", "by", "are", "was",
           "it", "from", "this", "be", "or", "which", "an", "not", "at", "were"},
}


def guess_lang(text, default=DEFAULT_LANG) -> str:
    """Langue probable d'un texte (fr ou en), pour proposer la langue du contenu d'une frise."""
    words = _WORDS_RE.findall((text or "")[:20_000].lower())
    scores = {lang: sum(1 for w in words if w in vocabulary) for lang, vocabulary in _FUNCTION_WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 5 and scores[best] > 1.5 * min(scores.values()) else default


def date_mentions(text: str) -> int:
    """Nombre approximatif d'années et de siècles cités : aide à repérer les paragraphes sans date."""
    return len(_YEAR_RE.findall(text or "")) + len(_CENTURY_RE.findall(text or ""))


def _prefix_length(project) -> int:
    return len(deck_segments(project.get("deck_prefix")))


def scope_chunks(project, scope) -> list:
    """
    Chunks d'une portée, dans l'ordre du projet.

    scope = {"kind": "chunk", "chunk_ids": [3]} | {"kind": "chapter", "deck_path": "A::B"}
            | {"kind": "project"}
    """
    prompts = project.get("prompts") or []
    kind = (scope or {}).get("kind")
    if kind == "project":
        chunks = list(prompts)
    elif kind == "chapter":
        chunks = [p for p in prompts if in_chapter(p.get("deck"), scope.get("deck_path"))]
    elif kind == "chunk":
        wanted = {int(i) for i in scope.get("chunk_ids") or []}
        chunks = [p for p in prompts if p.get("id") in wanted]
    else:
        raise ValueError(f"portée inconnue : {kind!r}")
    if not chunks:
        raise ValueError("portée vide")
    return chunks


def chapter_levels(project, chunk_id) -> list:
    """
    Niveaux de titre proposés par « Ce chapitre » pour le chunk courant : ses
    ancêtres, déduits du deck. Un niveau qui recouvre tout le cours ou ce seul
    chunk est écarté, puisque « Tout le cours » et « Ce paragraphe » le disent déjà.
    """
    prompts = project.get("prompts") or []
    chunk = next((p for p in prompts if p.get("id") == chunk_id), None)
    if chunk is None:
        return []
    prefix_len = _prefix_length(project)
    segments = deck_segments(chunk.get("deck"))
    everything = {p["id"] for p in prompts}
    # Chunks qui n'ont que le préfixe pour deck (titre du document) : ils ne
    # suffisent pas à distinguer un chapitre du cours entier.
    root_only = {p["id"] for p in prompts if len(deck_segments(p.get("deck"))) <= prefix_len}
    levels, seen = [], set()
    for depth in range(prefix_len + 1, len(segments) + 1):
        deck_path = "::".join(segments[:depth])
        ids = [p["id"] for p in prompts if in_chapter(p.get("deck"), deck_path)]
        if tuple(ids) in seen or set(ids) | root_only == everything or ids == [chunk_id]:
            continue
        seen.add(tuple(ids))
        levels.append({
            "deck_path": deck_path,
            "label": segments[depth - 1],
            "path": " › ".join(segments[prefix_len:depth]),
            "depth": depth - prefix_len,
            "chunk_ids": ids,
        })
    return levels


def scope_deck(project, scope) -> str:
    """
    Deck Anki de la portée, sous lequel iront les cartes de la frise : le chunk, le
    chapitre, ou pour tout le cours le plus long préfixe commun aux decks du cours
    (le cours lui-même plutôt que le préfixe partagé par plusieurs cours).
    """
    kind = scope.get("kind")
    if kind == "chapter":
        return "::".join(deck_segments(scope.get("deck_path")))
    if kind == "chunk":
        return "::".join(deck_segments(scope_chunks(project, scope)[0].get("deck")))
    prefix_len = _prefix_length(project)
    decks = [deck_segments(p.get("deck")) for p in project.get("prompts") or []]
    decks = [segments for segments in decks if len(segments) > prefix_len] or [s for s in decks if s]
    if not decks:
        return ""
    common = decks[0]
    for segments in decks[1:]:
        size = 0
        while size < min(len(common), len(segments)) and common[size] == segments[size]:
            size += 1
        common = common[:size]
    return "::".join(common)


def scope_title(project, scope) -> str:
    """Titre proposé pour la frise d'une portée."""
    kind = scope.get("kind")
    if kind == "chapter":
        return clean_title((deck_segments(scope.get("deck_path")) or [""])[-1])
    if kind == "chunk":
        chunk = scope_chunks(project, scope)[0]
        return clean_title((deck_segments(chunk.get("deck")) or [""])[-1])
    prefix_len = _prefix_length(project)
    for prompt in project.get("prompts") or []:
        segments = deck_segments(prompt.get("deck"))
        if len(segments) > prefix_len:
            return clean_title(segments[prefix_len])
    return clean_title(str(project.get("source") or "").rsplit(".", 1)[0])


# ──────────────────────────────────────────────────────────────
# Texte source (instantané)
# ──────────────────────────────────────────────────────────────
def build_source(chunks, deck_prefix="") -> tuple:
    """
    Chunks → (texte source, positions). Chaque chunk est précédé de son chemin de
    titres. `spans` = [[chunk_id, début, fin], …] dans le texte : il permet de
    rendre le prompt d'un seul paragraphe depuis l'instantané, sans le projet.
    Un chunk sans texte n'y figure pas.
    """
    parts, spans, position = [], [], 0
    for chunk in chunks:
        body = clean_chunk_text(chunk.get("prompt", ""))
        if not body:
            continue
        heading = heading_path(chunk.get("deck"), deck_prefix)
        section = f"## {heading}\n\n{body}" if heading else body
        if parts:
            position += 2
        spans.append([chunk["id"], position, position + len(section)])
        parts.append(section)
        position += len(section)
    return "\n\n".join(parts), spans


def chunk_text(source_text, spans, chunk_id) -> str:
    for span_id, start, end in spans or []:
        if span_id == chunk_id:
            return source_text[start:end]
    raise KeyError(chunk_id)


def chunk_heading(source_text, spans, chunk_id) -> str:
    """Chemin de titres d'un chunk, relu dans l'instantané."""
    first = chunk_text(source_text, spans, chunk_id).split("\n", 1)[0]
    return first[3:] if first.startswith("## ") else ""


def estimate_tokens(text) -> int:
    return math.ceil(len(text or "") / CHARS_PER_TOKEN)


def default_strategy(chars: int) -> str:
    return "per_chunk" if chars > SINGLE_PROMPT_MAX_CHARS else "single"


def scope_summary(project, scope, lang=DEFAULT_LANG) -> dict:
    """Ce que le sélecteur de portée affiche : taille, tokens estimés, stratégie par défaut."""
    chunks = scope_chunks(project, scope)
    text, spans = build_source(chunks, project.get("deck_prefix"))
    overhead = estimate_tokens(extraction_prompt("", lang=lang))
    return {
        "kind": scope["kind"],
        "deck_path": scope.get("deck_path"),
        "chunk_ids": [span[0] for span in spans],
        "chunks": len(spans),
        "chars": len(text),
        "tokens": estimate_tokens(text) + overhead,
        "strategy": default_strategy(len(text)),
        "title": scope_title(project, scope),
        "lang": guess_lang(text, lang),
    }


# ──────────────────────────────────────────────────────────────
# Gabarits
# ──────────────────────────────────────────────────────────────
def template_path(lang):
    return TEMPLATE_DIR / lang / TEMPLATE_NAME


def load_blocks(lang) -> dict:
    """Blocs nommés du gabarit, dans la langue demandée, avec repli sur l'anglais."""
    for candidate in (lang, DEFAULT_LANG):
        path = template_path(candidate)
        if path.is_file():
            return parse_blocks(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"gabarit de prompt introuvable : {template_path(DEFAULT_LANG)}")


def parse_blocks(text) -> dict:
    """Le texte avant le premier bloc (commentaire d'en-tête) est ignoré."""
    blocks, name, lines = {}, None, []
    for line in text.splitlines():
        match = _BLOCK_RE.match(line.strip())
        if match:
            if name:
                blocks[name] = "\n".join(lines).strip()
            name, lines = match.group(1), []
        elif name:
            lines.append(line)
    if name:
        blocks[name] = "\n".join(lines).strip()
    return blocks


def limits() -> dict:
    """Les limites du contrat, pour les {{variables}} des gabarits."""
    tail = EVENT_FIELDS
    return {
        "schema": SCHEMA_ID,
        "max_title": ROOT_FIELDS["title"]["max"],
        "max_tracks": ROOT_FIELDS["tracks"]["max"],
        "max_eras": ROOT_FIELDS["eras"]["max"],
        "max_periods": ROOT_FIELDS["periods"]["max"],
        "max_events": ROOT_FIELDS["events"]["max"],
        "max_track_label": TRACK_FIELDS["label"]["max"],
        "max_label": EVENT_FIELDS["label"]["max"],
        "max_era_label": ERA_FIELDS["label"]["max"],
        "max_id": 1 + int(re.search(r"\{0,(\d+)\}", ID_PATTERN).group(1)),
        "max_description": tail["description"]["max"],
        "max_date_text": tail["date_text"]["max"],
        "max_quote": tail["source_quote"]["max"],
        "max_tags": tail["tags"]["max"],
        "max_tag": tail["tags"]["items"]["max"],
    }


def fill(text, values) -> str:
    """
    Remplit les {{variables}} connues, en un seul passage : une valeur insérée
    (le texte source, un titre) n'est jamais relue, même si elle contient « {{ ».
    """
    return _VAR_RE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def _assemble(blocks, names, values) -> str:
    return "\n\n".join(fill(blocks[name], values) for name in names if blocks.get(name)).strip() + "\n"


def extraction_prompt(source_text, *, lang=DEFAULT_LANG, mode="strict", title="", skill=False,
                      chunk=False, tracks=()) -> str:
    """
    Le prompt à copier dans Claude.

    `chunk` : paragraphe par paragraphe (un passage sans date est une réponse
    normale). `tracks` : pistes déjà présentes dans la frise, à réutiliser.
    `skill` : le contrat est dans le Skill installé, le prompt se réduit au texte.
    """
    if mode not in MODES:
        raise ValueError(f"mode d'extraction inconnu : {mode!r}")
    blocks = load_blocks(lang)
    values = dict(limits(), lang=lang, title=title or "", source=source_text or "",
                  tracks=", ".join(f"\"{t['id']}\" ({t['label']})" for t in tracks))
    if skill:
        names = [f"skill_{mode}", "title", "skill_lang"]
    else:
        names = ["intro", "title", mode, "contract", "rules", "example", "output"]
    if not title:
        names.remove("title")
    if chunk:
        names.append("chunk")
        if tracks:
            names.append("chunk_tracks")
    names.append("source")
    return _assemble(blocks, names, values)


def skill_text(lang=DEFAULT_LANG) -> str:
    """Le Skill « Frise chronologique Ankigen », fait des mêmes blocs que le prompt complet."""
    blocks = load_blocks(lang)
    values = dict(limits(), lang=lang)
    names = ["skill_header", "intro", "strict", "enriched", "contract", "rules", "example", "output"]
    return _assemble(blocks, names, values)


def correction_prompt(report, *, lang=DEFAULT_LANG, include_warnings=False) -> str:
    """
    Prompt de correction (§6.6), dans la langue du DOCUMENT : chemin → message →
    indice, pour chaque erreur. Le JSON fautif n'est pas recopié : il est déjà
    dans la conversation Claude.
    """
    rendered = with_messages(report, lang)

    def lines(items):
        out = []
        for item in items:
            line = f"- {item.get('path') or '/'} → {item['message']}"
            if item.get("hint"):
                line += f" {item['hint']}"
            out.append(line)
        return "\n".join(out)

    blocks = load_blocks(lang)
    names, values = [], {}
    if rendered["errors"]:
        names.append("correction")
        values["errors"] = lines(rendered["errors"])
    if include_warnings and rendered["warnings"]:
        names.append("correction_warnings")
        values["warnings"] = lines(rendered["warnings"])
    if not names:
        return ""
    names.append("correction_end")
    return _assemble(blocks, names, values)
