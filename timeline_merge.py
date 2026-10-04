#!/usr/bin/env python3
"""
timeline_merge.py — Fusion d'une frise extraite paragraphe par paragraphe (§6.4).

Chaque paragraphe donne un document `ankigen.timeline/1` validé seul. La fusion
en fait une seule frise :

- les `id` sont préfixés par le chunk (`c12_gatt`), en tronquant la fin de
  l'`id` d'origine pour tenir en 48 caractères, puis `-2`, `-3`… en cas de
  collision (E6) ;
- les pistes sont rapprochées par libellé normalisé (casse, accents, espaces et
  ponctuation ignorés), ou par `id` identique : le prompt d'un paragraphe donne
  au modèle les pistes déjà utilisées, et il les réutilise ;
- les doublons entre paragraphes (même date à la précision commune, libellés
  similaires à ≥ 0,85) deviennent un seul élément : importance maximale,
  description la plus longue, union des tags, date la plus précise. Toutes les
  citations restent dans le rapport ;
- deux ères qui se chevauchent sont invalides : la seconde est écartée, et le
  rapport le dit ;
- au-delà de 12 pistes, les moins utilisées sont regroupées dans « Autres ».

L'utilisateur peut annuler une fusion de doublons : sa clé passe dans
`keep_separate`, et la fusion suivante garde les éléments séparés. Tout est
déterministe : ordre des chunks, puis ordre de chaque document.

Module pur : ni Flask ni I/O.
"""

from i18n import translate
from timeline_dates import DateError, parse_date, same_at_common_precision
from timeline_schema import ROOT_FIELDS, SCHEMA_ID, comparable_label, similar_labels

ID_MAX = 48
MAX_TRACKS = ROOT_FIELDS["tracks"]["max"]
OTHER_TRACK = "other"
_KINDS = ("eras", "periods", "events")


# ──────────────────────────────────────────────────────────────
# Identifiants
# ──────────────────────────────────────────────────────────────
def prefixed_id(chunk_id, original, taken) -> str:
    """`gatt` du chunk 12 → `c12_gatt`, tronqué à 48 caractères, unique dans `taken`."""
    prefix = f"c{chunk_id}_"
    base = prefix + original[:ID_MAX - len(prefix)]
    candidate, n = base, 2
    while candidate in taken:
        suffix = f"-{n}"
        candidate = base[:ID_MAX - len(suffix)] + suffix
        n += 1
    taken.add(candidate)
    return candidate


def _unique_id(wanted, taken) -> str:
    candidate, n = wanted[:ID_MAX], 2
    while candidate in taken:
        suffix = f"-{n}"
        candidate = wanted[:ID_MAX - len(suffix)] + suffix
        n += 1
    taken.add(candidate)
    return candidate


# ──────────────────────────────────────────────────────────────
# Dates
# ──────────────────────────────────────────────────────────────
def _dates(element, kind, as_of):
    precision = element.get("precision")
    try:
        if kind == "events":
            return {"date": parse_date(element["date"], precision)}
        end = element["end"]
        return {"start": parse_date(element["start"], precision),
                "end": parse_date(end, None if end == "present" else precision,
                                  allow_present=True, as_of=as_of)}
    except (DateError, KeyError):
        return None


def _width(dates):
    return sum(d.t1 - d.t0 for d in dates.values())


def _same_dates(a, b, kind) -> bool:
    if kind == "events":
        return same_at_common_precision(a["date"], b["date"])
    return (same_at_common_precision(a["start"], b["start"])
            and same_at_common_precision(a["end"], b["end"]))


def _span(dates, kind):
    if kind == "events":
        return dates["date"].t0, dates["date"].t1
    return dates["start"].t0, dates["end"].t1


# ──────────────────────────────────────────────────────────────
# Fusion
# ──────────────────────────────────────────────────────────────
def duplicate_key(ids) -> str:
    return "+".join(ids)


def merge(parts, *, title, lang, keep_separate=()) -> tuple:
    """
    parts = [(chunk_id, document normalisé), …] dans l'ordre du cours
    → (document fusionné, rapport de fusion).

    Le document n'est pas encore validé : l'appelant le passe à
    timeline_schema.validate, comme un collage.
    """
    keep_separate = set(keep_separate or ())
    as_of = next((doc.get("as_of") for _, doc in parts if doc.get("as_of")), None)
    taken = set()
    report = {"chunks": [chunk_id for chunk_id, _ in parts], "duplicates": [], "tracks": [],
              "tracks_folded": [], "eras_dropped": [], "links_dropped": 0}

    # ── Pistes ────────────────────────────────────────────────
    tracks, sources, by_label, by_id, track_map = [], [], {}, {}, {}
    for chunk_id, doc in parts:
        for track in doc.get("tracks") or []:
            key = comparable_label(track["label"])
            index = by_label.get(key, by_id.get(track["id"]))
            if index is None:
                index = len(tracks)
                merged = {"id": _unique_id(track["id"], taken), "label": track["label"]}
                if track.get("color"):
                    merged["color"] = track["color"]
                tracks.append(merged)
                sources.append([])
                by_label[key] = by_id[track["id"]] = index
            else:
                by_label.setdefault(key, index)
                by_id.setdefault(track["id"], index)
            sources[index].append((chunk_id, track["label"]))
            track_map[(chunk_id, track["id"])] = tracks[index]["id"]
    for index, track in enumerate(tracks):
        chunks = sorted({chunk for chunk, _ in sources[index]}, key=report["chunks"].index)
        if len(chunks) > 1:
            variants = []
            for _, label in sources[index]:
                if label not in variants:
                    variants.append(label)
            report["tracks"].append({"id": track["id"], "label": track["label"], "chunks": chunks,
                                     "variants": variants})

    # ── Éléments, avec leurs nouveaux identifiants ─────────────
    items = {kind: [] for kind in _KINDS}
    id_maps = {}
    trackless = False
    for chunk_id, doc in parts:
        id_map = id_maps[chunk_id] = {}
        for kind in _KINDS:
            for element in doc.get(kind) or []:
                dates = _dates(element, kind, as_of)
                if dates is None:        # un document validé n'en a pas ; prudence
                    continue
                new = dict(element)
                new["id"] = prefixed_id(chunk_id, element["id"], taken)
                id_map[element["id"]] = new["id"]
                if kind != "eras":
                    if element.get("track"):
                        new["track"] = track_map.get((chunk_id, element["track"]), element["track"])
                    else:
                        new.pop("track", None)
                        trackless = trackless or bool(tracks)
                items[kind].append({"chunk": chunk_id, "element": new, "dates": dates})

    # ── Doublons entre paragraphes ─────────────────────────────
    absorbed_into = {}
    for kind in ("periods", "events"):
        items[kind] = _merge_duplicates(kind, items[kind], keep_separate, report, absorbed_into)
    items["eras"] = _merge_duplicates("eras", items["eras"], keep_separate, report, absorbed_into)
    items["eras"] = _drop_overlapping_eras(items["eras"], report)

    # ── Pistes : éléments sans piste, et plafond de 12 ─────────
    elements = [entry["element"] for kind in ("periods", "events") for entry in items[kind]]
    other = None
    if trackless:
        other = {"id": _unique_id(OTHER_TRACK, taken), "label": translate("timeline.merge.other_track", lang)}
        tracks.append(other)
        for element in elements:
            element.setdefault("track", other["id"])
    if len(tracks) > MAX_TRACKS:
        usage = {}
        for element in elements:
            usage[element.get("track")] = usage.get(element.get("track"), 0) + 1
        candidates = [i for i, track in enumerate(tracks) if track is not other]
        ranked = sorted(candidates, key=lambda i: (-usage.get(tracks[i]["id"], 0), i))
        keep = set(ranked[:MAX_TRACKS - 1])
        folded = [tracks[i] for i in candidates if i not in keep]
        if other is None:
            other = {"id": _unique_id(OTHER_TRACK, taken), "label": translate("timeline.merge.other_track", lang)}
        folded_ids = {track["id"] for track in folded}
        for element in elements:
            if element.get("track") in folded_ids:
                element["track"] = other["id"]
        tracks = [tracks[i] for i in sorted(keep)] + [other]
        report["tracks_folded"] = [track["label"] for track in folded]

    # ── Liens ──────────────────────────────────────────────────
    links, seen_links = [], set()
    present = {entry["element"]["id"] for kind in _KINDS for entry in items[kind]}
    for chunk_id, doc in parts:
        for link in doc.get("links") or []:
            ends = []
            for end in ("from", "to"):
                new = id_maps[chunk_id].get(link[end])
                ends.append(absorbed_into.get(new, new))
            if None in ends or ends[0] == ends[1] or not set(ends) <= present or tuple(ends) in seen_links:
                report["links_dropped"] += 1
                continue
            seen_links.add(tuple(ends))
            merged = {"from": ends[0], "to": ends[1]}
            if link.get("label"):
                merged["label"] = link["label"]
            links.append(merged)

    doc = {"schema": SCHEMA_ID, "title": title, "lang": lang}
    if as_of:
        doc["as_of"] = as_of
    doc["tracks"] = tracks
    for kind in _KINDS:
        doc[kind] = [entry["element"] for entry in items[kind]]
    doc["links"] = links
    report["elements"] = sum(len(doc[kind]) for kind in _KINDS)
    report["merged"] = sum(len(d["ids"]) - 1 for d in report["duplicates"] if not d["separated"])
    return doc, report


def _merge_duplicates(kind, entries, keep_separate, report, absorbed_into):
    """Regroupe les doublons venus de chunks différents ; chaque groupe devient un élément."""
    parent = list(range(len(entries)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(entries)), key=lambda i: (_span(entries[i]["dates"], kind)[0], i))
    for pos, a in enumerate(order):
        start_a, end_a = _span(entries[a]["dates"], kind)
        for b in order[pos + 1:]:
            if _span(entries[b]["dates"], kind)[0] >= end_a:
                break
            if entries[a]["chunk"] == entries[b]["chunk"]:
                continue
            if not _same_dates(entries[a]["dates"], entries[b]["dates"], kind):
                continue
            if similar_labels(entries[a]["element"]["label"], entries[b]["element"]["label"]):
                ra, rb = root(a), root(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)

    groups = {}
    for i in range(len(entries)):
        groups.setdefault(root(i), []).append(i)
    out = []                    # (position dans le cours, entrée)
    for i, entry in enumerate(entries):
        members = groups[root(i)]
        if len(members) == 1:
            out.append((i, entry))
            continue
        if i != members[0]:
            continue            # déjà traité avec le premier membre du groupe
        ids = [entries[m]["element"]["id"] for m in members]
        key = duplicate_key(ids)
        separated = key in keep_separate
        report["duplicates"].append({
            "key": key, "kind": kind, "ids": ids, "kept": ids[0],
            "label": entry["element"]["label"],
            "chunks": [entries[m]["chunk"] for m in members],
            "quotes": [entries[m]["element"]["source_quote"] for m in members
                       if entries[m]["element"].get("source_quote")],
            "separated": separated,
        })
        if separated:
            out.extend((m, entries[m]) for m in members)
            continue
        out.append((i, _combine(kind, [entries[m] for m in members])))
        for m in members[1:]:
            absorbed_into[entries[m]["element"]["id"]] = ids[0]
    # Les groupes séparés ont été ajoutés en bloc : on rétablit l'ordre des chunks.
    out.sort(key=lambda item: item[0])
    return [entry for _, entry in out]


def _combine(kind, members):
    """Un élément fait d'un groupe de doublons : le premier garde son id, son libellé et sa piste."""
    base = dict(members[0]["element"])
    elements = [m["element"] for m in members]
    # La date la plus précise (intervalles les plus étroits) ; à égalité, la première.
    donor = min(range(len(members)), key=lambda i: (_width(members[i]["dates"]), i))
    date_keys = ("date",) if kind == "events" else ("start", "end")
    for key in date_keys + ("precision", "approx", "date_text"):
        base.pop(key, None)
        if key in elements[donor]:
            base[key] = elements[donor][key]
    if kind != "eras":
        base["importance"] = max(e.get("importance", 2) for e in elements)
    descriptions = [e.get("description") or "" for e in elements]
    longest = max(range(len(descriptions)), key=lambda i: (len(descriptions[i]), -i))
    if descriptions[longest]:
        base["description"] = descriptions[longest]
    tags = []
    for element in elements:
        for tag in element.get("tags") or []:
            if tag not in tags:
                tags.append(tag)
    if tags:
        base["tags"] = tags[:8]
    if not base.get("source_quote"):
        quote = next((e["source_quote"] for e in elements if e.get("source_quote")), None)
        if quote:
            base["source_quote"] = quote
    if any(e.get("origin", "text") == "text" for e in elements):
        base["origin"] = "text"
    return {"chunk": members[0]["chunk"], "element": base, "dates": members[donor]["dates"]}


def _drop_overlapping_eras(entries, report):
    """
    Deux ères ne se recouvrent pas, sauf d'une unité au point de contact (même
    règle que la validation). En cas de conflit, la première du cours reste.
    """
    kept = []
    for entry in entries:
        start, end = entry["dates"]["start"], entry["dates"]["end"]
        conflict = None
        for other in kept:
            o_start, o_end = other["dates"]["start"], other["dates"]["end"]
            overlap = min(end.t1, o_end.t1) - max(start.t0, o_start.t0)
            if overlap <= 1e-9:
                continue
            # Contact toléré : la fin de l'une et le début de l'autre partagent une unité.
            first_end, second_start = (o_end, start) if o_start.t0 <= start.t0 else (end, o_start)
            unit = max(first_end.t1 - first_end.t0, second_start.t1 - second_start.t0)
            if overlap > unit + 1e-9:
                conflict = other
                break
        if conflict is None:
            kept.append(entry)
        else:
            report["eras_dropped"].append({"chunk": entry["chunk"], "id": entry["element"]["id"],
                                           "label": entry["element"]["label"],
                                           "overlaps": conflict["element"]["label"]})
    return kept
