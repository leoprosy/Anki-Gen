#!/usr/bin/env python3
"""
timeline_cards.py — Cartes Anki tirées d'une frise (§10), sans LLM.

Le code génère les cartes depuis le document : `{id, type, ref, front, back, media}`.
L'`id` dérive d'un hash de (type, ref, recto) : il reste stable tant que la question
ne change pas, et c'est lui que la frise mémorise pour une carte désactivée. Le recto
est déterministe : un réimport met à jour les notes au lieu de les dupliquer (Anki
compare le premier champ).

Tout le texte venu du document est échappé, et aucun champ ne garde de tabulation
ni de saut de ligne (les retours deviennent `<br>`) : le TSV d'Anki n'a pas d'autre
façon de s'y tromper.

Images :
  * `whole_image` : la frise entière ;
  * `masked_image` : la frise recadrée à ±450 px autour d'un évènement, en gardant
    la gouttière des pistes et l'axe ; au recto, l'étiquette est remplacée par « ? »
    sur fond surligné, au verso elle est révélée et surlignée. Les deux vues sortent
    de la même display list : on retire ou on complète les primitives de l'évènement,
    la mise en page ne bouge pas.

Le nom d'une image embarque un hash de tout ce qui la détermine (version du rendu,
options, document, variante) : `collection.media` est un espace plat, et Anki ne
voit pas qu'un fichier a changé s'il garde son nom. Le nom se calcule sans dessiner ;
l'image est rendue à la demande, puis gardée sur disque.
"""

import hashlib
import html
import json
import os
import random
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from i18n import translate
from media_store import slugify
from timeline_dates import DateError, format_date, format_range, parse_date
from timeline_layout import Layout, LayoutOptions, Line, Marker, Path as PathPrim, Rect, Text

CARD_TYPES = ("event_to_date", "date_to_event", "period_bounds", "ordering", "neighbors",
              "whole_image", "masked_image")
DEFAULT_TYPES = ("event_to_date", "date_to_event", "period_bounds")
MAX_MASKED = 30
MASK_WINDOW = 450                   # px de part et d'autre de l'évènement (§10.3)
CROP_GAP = 8                        # liseré entre la gouttière des pistes et la fenêtre
# À incrémenter quand le dessin des images change : leurs noms changent avec lui.
RENDER_VERSION = 3  # Durées contenant leurs événements : renouveler les médias mis en cache.
# Style des dates, aligné sur skill_templates/fr.md (rouge, gras, souligné) : une
# seule constante, remplaçable plus tard par les balises sémantiques de l'agent local.
DATE_STYLE = "color: red; font-weight: bold; text-decoration: underline;"
HIGHLIGHT = "#FFE58A"               # surlignage de l'étiquette masquée
CROP_EXCLUDED_ROLES = ("title", "subtitle", "legend", "note", "note-badge", "note-text")
QUESTION_BY_PRECISION = {"day": "q_day", "month": "q_month", "year": "q_year", "decade": "q_decade",
                         "century": "q_century", "millennium": "q_millennium"}


@dataclass(frozen=True)
class Card:
    id: str
    type: str
    ref: str
    front: str
    back: str
    media: tuple = ()               # noms de fichiers utilisés par la carte
    images: tuple = field(default=(), compare=False)   # ((nom, variante, ref), …) à rendre


def card_layout_options(render_options=None) -> LayoutOptions:
    """Les images des cartes : thème clair, densité de la frise, sans marquage des citations."""
    density = (render_options or {}).get("density")
    return LayoutOptions(theme="light", density=density if density in ("comfortable", "compact") else "compact",
                         show_unverified=False)


# ──────────────────────────────────────────────────────────────
# Texte
# ──────────────────────────────────────────────────────────────
def field_text(value) -> str:
    """Champ TSV sûr : ni tabulation, ni saut de ligne."""
    text = str(value or "")
    for newline in ("\r\n", "\n", "\r"):
        text = text.replace(newline, "<br>")
    return text.replace("\t", " ")


def esc(text) -> str:
    """Texte du document dans un contenu HTML (jamais dans un attribut) : &, < et > suffisent."""
    return html.escape(str(text or ""), quote=False).replace("\r\n", "\n").replace("\n", "<br>")


def styled_date(text) -> str:
    return f'<span style="{DATE_STYLE}">{esc(text)}</span>'


def _t(key, lang, **params):
    return translate(f"timeline.cards.{key}", lang, **params)


def _card_id(kind, ref, front) -> str:
    return hashlib.sha1(f"{kind}\x1f{ref}\x1f{front}".encode("utf-8")).hexdigest()[:12]


def _description(element) -> str:
    return f"<br><br>{esc(element['description'])}" if element.get("description") else ""


# ──────────────────────────────────────────────────────────────
# Éléments datés
# ──────────────────────────────────────────────────────────────
def _events(doc):
    """(évènement, date) des évènements venus du cours, triés par date puis par ordre du document."""
    out = []
    for index, event in enumerate(doc.get("events") or []):
        if event.get("origin") == "model":      # hors cours : exclu des cartes (§6.3)
            continue
        try:
            date = parse_date(event["date"], event.get("precision"))
        except (DateError, KeyError):
            continue
        out.append((index, event, date))
    out.sort(key=lambda item: (item[2].t0, item[2].t1, item[0]))
    return [(event, date) for _, event, date in out]


def _track_labels(doc):
    return {track["id"]: track["label"] for track in doc.get("tracks") or []}


def _by_track(doc):
    groups = {}
    for event, date in _events(doc):
        groups.setdefault(event.get("track"), []).append((event, date))
    return groups


def _group_sizes(n):
    """Groupes de 3 à 5 qui couvrent n éléments (n ≥ 3), 4 de préférence."""
    sizes, remaining = [], n
    while remaining >= 3:
        size = {3: 3, 5: 5, 6: 3, 7: 4}.get(remaining, 4)
        sizes.append(size)
        remaining -= size
    return sizes


# ──────────────────────────────────────────────────────────────
# Génération
# ──────────────────────────────────────────────────────────────
def generate(doc, *, types=DEFAULT_TYPES, layout=None, media_prefix="ag_tl", render_key="") -> list:
    """
    Document normalisé → cartes, dans l'ordre des types puis des dates.

    `layout` (mise en page des images) n'est nécessaire que pour `masked_image` et
    `whole_image`. `render_key` résume les options du rendu : il entre dans le
    hash des noms d'images.
    """
    lang = doc.get("lang") or "en"
    tracks = _track_labels(doc)
    selected = [kind for kind in CARD_TYPES if kind in set(types or ())]
    cards = []
    doc_key = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def add(kind, ref, front, back, images=()):
        front, back = field_text(front), field_text(back)
        media = tuple(name for name, _, _ in images)
        cards.append(Card(id=_card_id(kind, ref, front), type=kind, ref=ref, front=front, back=back,
                          media=media, images=tuple(images)))

    def image_name(ref, variant):
        digest = hashlib.sha1(json.dumps([RENDER_VERSION, render_key, doc_key, ref, variant],
                                         ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
        return f"{media_prefix}_{ref}_{variant}_{digest}.png"

    for kind in selected:
        if kind == "event_to_date":
            for event, date in _events(doc):
                question = _t(QUESTION_BY_PRECISION[date.precision], lang, label=esc(event["label"]))
                answer = styled_date(format_date(date, lang, approx=event.get("approx", False)))
                add(kind, event["id"], question, answer + _description(event))

        elif kind == "date_to_event":
            groups = {}
            for event, date in _events(doc):
                if date.precision in ("century", "millennium"):
                    continue
                key = (event.get("track"), date.t0, date.t1, bool(event.get("approx")))
                groups.setdefault(key, []).append((event, date))
            for members in sorted(groups.values(), key=lambda m: (m[0][1].t0, m[0][1].t1, m[0][0]["id"])):
                event, date = members[0]
                shown = styled_date(format_date(date, lang, approx=event.get("approx", False)))
                track = tracks.get(event.get("track"))
                question = (_t("date_to_event", lang, date=shown, track=esc(track)) if track
                            else _t("date_to_event_plain", lang, date=shown))
                answer = "<br>".join(f"<b>{esc(e['label'])}</b>" for e, _ in members)
                answer += "".join(_description(e) for e, _ in members)
                add(kind, "+".join(e["id"] for e, _ in members), question, answer)

        elif kind == "period_bounds":
            for period in doc.get("periods") or []:
                if period.get("origin") == "model":
                    continue
                try:
                    start = parse_date(period["start"], period.get("precision"))
                    end = parse_date(period["end"], None if period["end"] == "present" else period.get("precision"),
                                     allow_present=True, as_of=doc.get("as_of"))
                except (DateError, KeyError):
                    continue
                question = _t("period_bounds", lang, label=esc(period["label"]))
                answer = styled_date(format_range(start, end, lang, approx=period.get("approx", False)))
                add(kind, period["id"], question, answer + _description(period))

        elif kind == "ordering":
            for _, members in sorted(_by_track(doc).items(), key=lambda item: str(item[0])):
                distinct = []
                for event, date in members:
                    if distinct and (distinct[-1][1].t0, distinct[-1][1].t1) == (date.t0, date.t1):
                        continue            # même date : l'ordre serait arbitraire
                    distinct.append((event, date))
                start = 0
                for size in _group_sizes(len(distinct)):
                    group = distinct[start:start + size]
                    start += size
                    ids = [event["id"] for event, _ in group]
                    order = list(range(len(group)))
                    # Mélange déterministe (graine = ids) ; jamais l'ordre de la réponse.
                    seed = int(hashlib.sha1("+".join(ids).encode("utf-8")).hexdigest()[:12], 16)
                    random.Random(seed).shuffle(order)
                    if order == sorted(order):
                        order = order[1:] + order[:1]
                    question = _t("ordering", lang, items=" · ".join(esc(group[i][0]["label"]) for i in order))
                    answer = "<ol>" + "".join(
                        f"<li>{styled_date(format_date(date, lang, approx=event.get('approx', False)))} — "
                        f"{esc(event['label'])}</li>" for event, date in group) + "</ol>"
                    add(kind, "+".join(ids), question, answer)

        elif kind == "neighbors":
            for track_id, members in sorted(_by_track(doc).items(), key=lambda item: str(item[0])):
                for index, (event, date) in enumerate(members):
                    parts = []
                    for key, neighbour in (("before", members[index - 1] if index > 0 else None),
                                           ("after", members[index + 1] if index + 1 < len(members) else None)):
                        if neighbour:
                            item = (f"<b>{esc(neighbour[0]['label'])}</b> ("
                                    f"{styled_date(format_date(neighbour[1], lang, approx=neighbour[0].get('approx', False)))})")
                            parts.append(_t(key, lang, item=item))
                    if not parts:
                        continue
                    track = tracks.get(track_id)
                    question = (_t("neighbors", lang, track=esc(track), label=esc(event["label"])) if track
                                else _t("neighbors_plain", lang, label=esc(event["label"])))
                    add(kind, event["id"], question, "<br>".join(parts))

        elif kind == "whole_image" and layout is not None:
            name = image_name("all", "full")
            question = _t("whole_image", lang, title=esc(doc.get("title")))
            add(kind, "all", question, f'<img src="{name}">', images=((name, "full", "all"),))

        elif kind == "masked_image" and layout is not None:
            labeled = {p.ref for p in layout.primitives if p.role == "event-label" and isinstance(p, Text)}
            candidates = [(event, date) for event, date in _events(doc)
                          if event.get("importance", 2) >= 2 and event["id"] in labeled]
            chosen = sorted(candidates, key=lambda item: (-item[0].get("importance", 2), item[1].t0))[:MAX_MASKED]
            chosen_ids = {event["id"] for event, _ in chosen}
            for event, date in candidates:
                if event["id"] not in chosen_ids:
                    continue
                front_name, back_name = image_name(event["id"], "q"), image_name(event["id"], "a")
                question = f'<img src="{front_name}"><br>{_t("masked_question", lang)}'
                answer = (f'<img src="{back_name}"><br><b>{esc(event["label"])}</b> — '
                          f'{styled_date(format_date(date, lang, approx=event.get("approx", False)))}'
                          + _description(event))
                add(kind, event["id"], question, answer,
                    images=((front_name, "q", event["id"]), (back_name, "a", event["id"])))
    return cards


# ──────────────────────────────────────────────────────────────
# Images
# ──────────────────────────────────────────────────────────────
def _translate_prim(prim, dx, dy):
    if isinstance(prim, Rect):
        return replace(prim, x=prim.x + dx, y=prim.y + dy)
    if isinstance(prim, Line):
        return replace(prim, x1=prim.x1 + dx, y1=prim.y1 + dy, x2=prim.x2 + dx, y2=prim.y2 + dy)
    if isinstance(prim, PathPrim):
        return replace(prim, points=tuple((c, x + dx, y + dy) for c, x, y in prim.points))
    if isinstance(prim, Marker):
        return replace(prim, cx=prim.cx + dx, cy=prim.cy + dy)
    if isinstance(prim, Text):
        return replace(prim, x=prim.x + dx, y=prim.y + dy)
    return prim


def _masked_primitives(layout, ref, variant, measure):
    """Primitives de la vue masquée (q) ou révélée (a) de l'évènement `ref`."""
    own = [p for p in layout.primitives if p.ref == ref and p.role in ("event-label", "event-date")]
    others = [p for p in layout.primitives if not (p.ref == ref and p.role in ("event-label", "event-date"))]
    if not own:
        return list(layout.primitives), None
    x0 = min(p.bbox[0] for p in own) - 4
    y0 = min(p.bbox[1] for p in own) - 3
    x1 = max(p.bbox[2] for p in own) + 4
    y1 = max(p.bbox[3] for p in own) + 3
    highlight = Rect(x=x0, y=y0, w=x1 - x0, h=y1 - y0, rx=4, fill=HIGHLIGHT, role="highlight", ref=ref)
    if variant == "a":
        return others + [highlight] + own, (x0 + x1) / 2
    label = next((p for p in own if p.role == "event-label"), own[0])
    ink = (layout.theme or {}).get("ink", "#1D1D1F")
    size = round(min(label.size * 1.6, (y1 - y0) * 0.7), 1)
    question = Text(x=(x0 + x1) / 2, y=(y0 + y1) / 2 + 0.35 * size, lines=("?",), size=size, weight=600,
                    fill=ink, anchor="middle", line_height=label.line_height,
                    widths=(measure("?", size, 600),), role="highlight", ref=ref)
    return others + [highlight, question], (x0 + x1) / 2


def _sub_layout(layout, primitives, x0, x1, y0, y1):
    """Fenêtre [x0, x1] × [y0, y1] de la display list, ramenée à l'origine."""
    kept = [p for p in primitives
            if p.role not in CROP_EXCLUDED_ROLES and p.bbox[2] >= x0 - 1 and p.bbox[0] <= x1 + 1
            and p.bbox[3] >= y0 - 1 and p.bbox[1] <= y1 + 1]
    return Layout(width=x1 - x0, height=y1 - y0, primitives=tuple(_translate_prim(p, -x0, -y0) for p in kept),
                  theme=layout.theme)


def _vertical_bounds(layout):
    boxes = [p.bbox for p in layout.primitives if p.role not in CROP_EXCLUDED_ROLES]
    return max(0.0, min(b[1] for b in boxes) - 8), min(layout.height, max(b[3] for b in boxes) + 8)


def render_media(layout, variant, ref, *, fonts=None) -> bytes:
    """PNG d'une image de carte : frise entière (`full`), recto masqué (`q`) ou verso révélé (`a`)."""
    import io

    from PIL import Image

    from timeline_fonts import default_fonts
    from timeline_render_raster import render_image
    fonts = fonts or default_fonts()
    buffer = io.BytesIO()
    if variant == "full":
        render_image(layout, scale=1, supersample=2, fonts=fonts).save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    primitives, center = _masked_primitives(layout, ref, variant, fonts.measure)
    if center is None:
        raise KeyError(ref)
    gutter = layout.scale.segments[0][2] if layout.scale else 0.0
    y0, y1 = _vertical_bounds(layout)
    # Fenêtre de 2 × 450 px autour de l'évènement, décalée pour rester dans le tracé.
    left = max(gutter, min(center - MASK_WINDOW, layout.width - 2 * MASK_WINDOW))
    right = min(layout.width, left + 2 * MASK_WINDOW)
    parts = [render_image(_sub_layout(layout, primitives, 0, gutter, y0, y1), scale=1, supersample=2, fonts=fonts)
             if gutter > 1 else None,
             render_image(_sub_layout(layout, primitives, left, right, y0, y1), scale=1, supersample=2, fonts=fonts)]
    parts = [part for part in parts if part is not None]
    # Un liseré de fond sépare la gouttière de la fenêtre : un texte coupé au bord gauche
    # de la fenêtre ne paraît pas prolonger les libellés de piste.
    gap = CROP_GAP if len(parts) > 1 else 0
    background = (layout.theme or {}).get("bg", "#FFFFFF")
    sheet = Image.new("RGB", (sum(p.size[0] for p in parts) + gap, max(p.size[1] for p in parts)),
                      tuple(int(background[i:i + 2], 16) for i in (1, 3, 5)))
    x = 0
    for part in parts:
        sheet.paste(part, (x, 0))
        x += part.size[0] + gap
    sheet.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def ensure_media(cards, layout, directory, *, names=None, fonts=None) -> list:
    """
    Rend les images manquantes des cartes dans `directory` (écriture atomique) et
    renvoie leurs noms. `names` limite le travail aux images demandées.
    """
    directory = Path(directory)
    written = []
    for card in cards:
        for name, variant, ref in card.images:
            if names is not None and name not in names:
                continue
            target = directory / name
            if target.exists():
                continue
            directory.mkdir(parents=True, exist_ok=True)
            data = render_media(layout, variant, ref, fonts=fonts)
            fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".card-", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(tmp, target)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            written.append(name)
    return written


# ──────────────────────────────────────────────────────────────
# Deck et noms
# ──────────────────────────────────────────────────────────────
def media_prefix(timeline_id, project_id=None) -> str:
    """`ag_<projet>_tl_<frise>` ou `ag_tl_<frise>` : les images d'une frise se reconnaissent dans collection.media."""
    timeline = slugify(timeline_id, 32)
    return f"ag_{slugify(project_id)}_tl_{timeline}" if project_id else f"ag_tl_{timeline}"


def default_deck(base, lang) -> str:
    """Deck de la portée suivi du sous-deck, dans la langue du document ; figé ensuite dans la frise."""
    subdeck = _t("subdeck", lang)
    return f"{base}::{subdeck}" if base else subdeck
