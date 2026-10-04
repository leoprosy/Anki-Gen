#!/usr/bin/env python3
"""
timeline_layout.py — Le moteur de mise en page des frises : document → display list.

C'est ici que se joue la promesse « aucun chevauchement ». Le module est PUR :
ni I/O, ni Flask, ni Pillow. Il reçoit la mesure du texte par injection
(`measure(texte, taille_px, graisse) -> largeur_px`), la même que celle des
moteurs de rendu, et produit une liste de primitives (Rect, Line, Path, Marker,
Text) que le SVG et le raster dessinent tels quels : l'aperçu est l'export.

Principes (voir le §7 du contrat et la spec) :
  * la position horizontale d'un marqueur est exactement `scale(date)` ; la
    compaction verticale déplace ensemble marqueurs, étiquettes et traits ;
  * chaque étiquette est essayée à des niveaux croissants au-dessus et en dessous
    de sa piste, avec plusieurs décalages horizontaux, et n'est acceptée que si
    sa boîte (plus une marge) ne touche aucun obstacle déjà placé ;
  * sinon, échelle de repli : libellé sur plus de lignes, canevas élargi (en
    largeur automatique), pastille numérotée renvoyée en note, puis grappe « ×N ».
    Un élément n'est jamais masqué sans trace ;
  * `check_layout()` vérifie après coup les invariants I1–I9, dans les tests et
    à l'exécution ;
  * déterminisme : aucun hasard, aucun ordre de dict ou de set non maîtrisé.

Coordonnées : px, origine en haut à gauche. Chaque piste est d'abord mise en page
dans son propre repère (ligne de base en y = 0, au-dessus = y négatif), puis
translatée à sa place.
"""

import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field, replace

from i18n import translate
from timeline_dates import (
    decimal_year, days_in_month, format_date, format_range, format_year, parse_date,
    to_astronomical, to_historical,
)

# ──────────────────────────────────────────────────────────────
# Constantes (grille de 4 px de design.md pour les espacements)
# ──────────────────────────────────────────────────────────────
ASCENT, DESCENT = 0.97, 0.25        # em — métriques verticales d'Inter, arrondies vers le haut
LINE_HEIGHT = 1.25
SIZES = {"title": 20, "subtitle": 13, "era": 12, "tick": 11, "lane": 13, "date": 11,
         "label": 12, "note": 12, "legend": 12, "badge": 10}
MARGIN = 24
GUTTER_PAD = 16
GUTTER_MAX = 176
LANE_GAP = 4
LABEL_MARGIN = 4            # marge autour d'une étiquette candidate (§7.6)
TEXT_GAP = 2                # I1 : écart minimal entre deux textes
DATE_LABEL_GAP = 3          # entre la ligne de date et le libellé d'une même étiquette
INLINE_DATE_GAP = 8
ERA_PAD = 8
STEM_GAP = 3                # la tige s'arrête avant l'étiquette
STEM_START = 2              # et démarre au bord du marqueur
MARKER_R = {1: 5.5, 2: 5.5, 3: 5.5}
MARKER_RING = 1.5           # anneau couleur du fond autour des marqueurs (skill dataviz)
BAR_H, BAR_PAD, BAR_MIN = 18, 8, 48
BADGE_R = 8
BREAK_PX = 40
CLUSTER_GUARD = 24          # px de part et d'autre d'un bloc de temps, quand l'axe est interrompu
MAX_BREAKS = 3
WIDTH_MIN, WIDTH_MAX = 900, 12000
TARGET_GAP_PX = 24          # écart visé au 20e percentile des évènements d'une piste
MAX_WIDEN = 3
MIN_SPAN_YEARS = 1.0
GRID_CELL = 64
EPS = 0.01

DENSITIES = {
    "comfortable": {"label_max_width": 180, "max_levels": 4, "lane_pad": 12, "row_gap": 6, "pack": False,
                    "level_first": 16, "level_step": 8, "level_pitch": 32, "min_tick_px": 56},
    "compact": {"label_max_width": 208, "max_levels": 6, "lane_pad": 6, "row_gap": 4, "pack": True,
                "level_first": 16, "level_step": 6, "level_pitch": 24, "min_tick_px": 56},
}

SHAPES = ("circle",)

# Avertissements propres au dessin (clés timeline.warn.<code>), à côté de ceux du schéma.
WARNING_CODES = ("label_truncated", "labels_in_notes", "label_unsupported_chars", "layout_violation")

# Palette des pistes : Okabe–Ito ajustée (jaune pur et noir exclus, violet et brun
# ajoutés), pas choisis et ordre validés avec le validateur du skill dataviz :
# ≥ 3:1 sur le fond du thème, séparation CVD des pistes voisines ≥ 15 (ΔE OKLab),
# bande de luminosité respectée. Les pistes sont identifiées par leurs noms et
# leurs couleurs ; les évènements gardent tous le même repère rond.
THEMES = {
    "light": {
        "bg": "#FFFFFF", "ink": "#1D1D1F", "secondary": "#6E6E73", "axis": "#AEAEB2",
        "grid": "#EBEBEF", "lane_bg": ("#F6F6F8", None),
        "palette": ("#0371B1", "#169D74", "#6A3E99", "#D45E00",
                    "#3F9CCF", "#C58801", "#974E40", "#CB7AA7"),
        "era_palette": ("#0D9488", "#D97706", "#7C3AED", "#2563EB", "#DB2777", "#65A30D"),
    },
    "dark": {
        "bg": "#1C1C1E", "ink": "#F5F5F7", "secondary": "#AEAEB2", "axis": "#636366",
        "grid": "#2C2C2E", "lane_bg": ("#232326", None),
        "palette": ("#0371B1", "#169D74", "#7E52AF", "#D45E00",
                    "#429FD2", "#C18501", "#9C5344", "#C574A1"),
        "era_palette": ("#2DD4BF", "#FBBF24", "#A78BFA", "#60A5FA", "#F472B6", "#A3E635"),
    },
    # Impression : fond blanc, encre noire, pistes en niveaux de gris, pas de fonds pâles.
    "print": {
        "bg": "#FFFFFF", "ink": "#000000", "secondary": "#3A3A3C", "axis": "#000000",
        "grid": "#D4D4D8", "lane_bg": (None, None),
        "palette": ("#1D1D1F", "#767676", "#454545", "#8A8A8A"),
        "era_palette": ("#1D1D1F", "#767676", "#454545", "#8A8A8A"),
    },
}


# ──────────────────────────────────────────────────────────────
# Couleurs (WCAG)
# ──────────────────────────────────────────────────────────────
def _rgb(color):
    value = int(color[1:], 16)
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def luminance(color) -> float:
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a, b, t) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def readable(color, backgrounds, ratio) -> str:
    """`color`, assombri (ou éclairci sur fond sombre) jusqu'au contraste demandé sur chaque fond."""
    backgrounds = [bg for bg in backgrounds if bg]
    target = "#000000" if min(luminance(bg) for bg in backgrounds) > 0.18 else "#FFFFFF"
    for step in range(21):
        candidate = mix(color, target, step / 20)
        if all(contrast(candidate, bg) >= ratio for bg in backgrounds):
            return candidate
    return target


def best_text_on(fill, candidates) -> str:
    return max(candidates, key=lambda c: (contrast(c, fill), c))


# ──────────────────────────────────────────────────────────────
# Primitives de la display list
# ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    rx: float = 0.0
    fill: object = None
    stroke: object = None
    opacity: float = 1.0
    fade: str = ""              # "", "both" (période approximative), "end" (période en cours)
    role: str = ""
    ref: object = None
    lane: object = None

    @property
    def bbox(self):
        return (self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    stroke: str = "#000000"
    width: float = 1.0
    dash: str = ""
    role: str = ""
    ref: object = None
    lane: object = None

    @property
    def bbox(self):
        half = self.width / 2
        return (min(self.x1, self.x2) - half, min(self.y1, self.y2) - half,
                max(self.x1, self.x2) + half, max(self.y1, self.y2) + half)


@dataclass(frozen=True)
class Path:
    """Sous-ensemble M/L/Z en coordonnées absolues : zigzags, accolades, flèches."""

    points: tuple               # ((commande, x, y), ...)
    fill: object = None
    stroke: object = None
    width: float = 1.0
    role: str = ""
    ref: object = None
    lane: object = None

    @property
    def d(self):
        return " ".join(f"{c} {_num(x)} {_num(y)}" if c != "Z" else "Z" for c, x, y in self.points)

    @property
    def bbox(self):
        xs = [x for c, x, _ in self.points if c != "Z"]
        ys = [y for c, _, y in self.points if c != "Z"]
        half = self.width / 2
        return (min(xs) - half, min(ys) - half, max(xs) + half, max(ys) + half)


@dataclass(frozen=True)
class Marker:
    shape: str
    cx: float
    cy: float
    r: float
    fill: object = None
    stroke: object = None
    stroke_width: float = MARKER_RING
    dashed: bool = False
    role: str = "marker"
    ref: object = None
    lane: object = None

    @property
    def bbox(self):
        reach = self.r + (self.stroke_width / 2 if self.stroke else 0)
        return (self.cx - reach, self.cy - reach, self.cx + reach, self.cy + reach)


@dataclass(frozen=True)
class Text:
    """Texte sur une ou plusieurs lignes. `y` est la ligne de base de la première ligne."""

    x: float
    y: float
    lines: tuple
    size: float
    weight: int
    fill: str
    anchor: str                 # start | middle | end — identique en SVG et en raster
    line_height: float
    widths: tuple               # largeur mesurée de chaque ligne
    role: str = ""
    ref: object = None
    lane: object = None

    @property
    def bbox(self):
        width = max(self.widths) if self.widths else 0.0
        x0 = self.x - width / 2 if self.anchor == "middle" else self.x - width if self.anchor == "end" else self.x
        top = self.y - ASCENT * self.size
        bottom = self.y + (len(self.lines) - 1) * self.line_height + DESCENT * self.size
        return (x0, top, x0 + width, bottom)


def _num(value) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def refs_of(ref) -> tuple:
    """« a+b » → ("a", "b") : une étiquette de groupe représente plusieurs éléments."""
    return tuple(ref.split("+")) if ref else ()


# ──────────────────────────────────────────────────────────────
# Échelle linéaire par morceaux
# ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Scale:
    segments: tuple             # ((t0, t1, x0, x1, rupture), ...) contigus, triés

    def _segment(self, key, index):
        starts = [segment[index] for segment in self.segments]
        i = max(0, min(len(self.segments) - 1, bisect_right(starts, key) - 1))
        return self.segments[i]

    def x(self, t) -> float:
        t0, t1, x0, x1, _ = self._segment(t, 0)
        return x0 + (t - t0) * (x1 - x0) / (t1 - t0) if t1 > t0 else x0

    def t(self, x) -> float:
        t0, t1, x0, x1, _ = self._segment(x, 2)
        return t0 + (x - x0) * (t1 - t0) / (x1 - x0) if x1 > x0 else t0

    @property
    def breaks(self):
        return tuple((t0, t1, x0, x1) for t0, t1, x0, x1, broken in self.segments if broken)

    @property
    def domain(self):
        return self.segments[0][0], self.segments[-1][1]


# ──────────────────────────────────────────────────────────────
# Options et résultat
# ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LayoutOptions:
    orientation: str = "horizontal"     # « vertical » : phase 8
    width_mode: str = "auto"            # auto | fixed
    width_px: int = 1200
    density: str = "compact"            # comfortable | compact
    axis_breaks: str = "auto"           # auto | off
    label_max_width: object = None      # défaut selon la densité (180 / 208)
    max_levels_per_side: object = None  # défaut selon la densité (4 / 6)
    show_descriptions: bool = False
    show_unverified: bool = True
    # Éléments dont la citation est introuvable dans le cours (§6.5) : marqueur cerclé
    # d'encre et barre contournée. L'aperçu les montre ; l'export, sur option (phase 5).
    unverified: tuple = ()
    theme: str = "light"                # light | dark | print — n'influe que sur les couleurs
    lang: object = None                 # langue des textes dessinés : défaut, celle du document


@dataclass(frozen=True)
class Layout:
    width: float
    height: float
    primitives: tuple
    notes: tuple = ()           # ({"number", "ref", "text"}, ...)
    stats: dict = field(default_factory=dict)
    warnings: tuple = ()        # ({"code", "ref"?, "params"}, ...)
    scale: object = None
    lanes: tuple = ()           # ((y0, y1), ...) : I5
    anchors: tuple = ()         # ((id, t), ...) évènements non groupés : I6
    spans: tuple = ()           # ((id, t0, t1), ...) périodes et ères : I9
    elements: tuple = ()        # identifiants de tous les éléments : I7
    desc: tuple = ()            # une ligne par élément, pour <desc> et les lecteurs d'écran
    theme: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Violation:
    invariant: str
    message: str
    refs: tuple = ()


# ──────────────────────────────────────────────────────────────
# Géométrie
# ──────────────────────────────────────────────────────────────
def _intersects(a, b, gap=0.0) -> bool:
    return (a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap)


def _inflate(box, d):
    return (box[0] - d, box[1] - d, box[2] + d, box[3] + d)


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


class _Grid:
    """Index spatial : cases de 64 px sur x, pour ne tester que les obstacles voisins."""

    def __init__(self):
        self.cells = defaultdict(list)

    def _keys(self, box):
        return range(math.floor(box[0] / GRID_CELL), math.floor(box[2] / GRID_CELL) + 1)

    def add(self, box, kind):
        for key in self._keys(box):
            self.cells[key].append((box, kind))

    def hits(self, box, kinds=None, gap=0.0) -> bool:
        for key in self._keys(_inflate(box, gap)):
            for other, kind in self.cells.get(key, ()):
                if (kinds is None or kind in kinds) and _intersects(box, other, gap):
                    return True
        return False


def _text(x, y, lines, size, weight, fill, anchor, measure, role, ref=None, lane=None, line_height=None):
    lines = tuple(lines)
    return Text(x=x, y=y, lines=lines, size=size, weight=weight, fill=fill, anchor=anchor,
                line_height=line_height or size * LINE_HEIGHT,
                widths=tuple(round(measure(line, size, weight), 3) for line in lines),
                role=role, ref=ref, lane=lane)


def _text_height(size, lines, line_height=None):
    return (ASCENT + DESCENT) * size + (lines - 1) * (line_height or size * LINE_HEIGHT)


def wrap(text, width, size, weight, measure) -> list:
    """Retour à la ligne glouton par mots ; un mot trop long est coupé entre deux caractères."""
    lines, current = [], ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if measure(candidate, size, weight) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while word and measure(word, size, weight) > width:
            cut = 1
            while cut < len(word) and measure(word[:cut + 1], size, weight) <= width:
                cut += 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


def _truncate(lines, width, size, weight, measure, max_lines=3):
    """Garde `max_lines` lignes ; la dernière finit par « … » (avertissement label_truncated)."""
    kept = list(lines[:max_lines])
    last = kept[-1]
    while last and measure(last + "…", size, weight) > width:
        last = last[:-1].rstrip()
    kept[-1] = last + "…"
    return kept


def label_variants(text, max_width, size, weight, measure):
    """
    Découpes candidates d'un libellé, de la plus compacte en hauteur à la plus étroite.

    Échelle de repli, étape 1 : si rien ne passe sur le moins de lignes possible,
    on repasse tous les candidats avec le libellé renvoyé sur 2 lignes, puis 3,
    donc plus étroit. Au-delà de 3 lignes, le libellé est tronqué.
    """
    base = wrap(text, max_width, size, weight, measure)
    if len(base) > 3:
        return [(_truncate(base, max_width, size, weight, measure), True)]
    variants = [(base, False)]
    total = measure(text, size, weight)
    longest_word = max((measure(w, size, weight) for w in text.split(" ")), default=0)
    for count in range(len(base) + 1, 4):
        target = max(longest_word, total / count * 1.08)
        lines = wrap(text, min(target, max_width), size, weight, measure)
        if len(lines) <= 3 and lines not in [v for v, _ in variants]:
            variants.append((lines, False))
    return variants


# ──────────────────────────────────────────────────────────────
# Temps : domaine, ruptures, graduations
# ──────────────────────────────────────────────────────────────
def _merge_intervals(intervals):
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _clusters(items, allow_breaks):
    """
    Blocs de temps conservés sur l'axe : un seul sans rupture, sinon ceux que
    séparent les vides compressés.

    Un vide est compressible s'il dépasse 25 % de l'étendue des données ; on n'en
    compresse que si l'ensemble retenu (au plus 3) en couvre au moins la moitié,
    c'est-à-dire si la densité utile au moins double. Les intervalles occupés
    comprennent périodes et ères : une rupture ne tombe jamais dans l'une d'elles (I9).
    """
    t_min = min(a for a, _, _ in items)
    t_max = max(b for _, b, _ in items)
    span = t_max - t_min
    if span < MIN_SPAN_YEARS:
        middle = (t_min + t_max) / 2
        t_min, t_max, span = middle - MIN_SPAN_YEARS / 2, middle + MIN_SPAN_YEARS / 2, MIN_SPAN_YEARS
    if not allow_breaks:
        return [(t_min, t_max)]
    occupied = _merge_intervals([(a, b) for a, b, _ in items])
    gaps = [(occupied[i][1], occupied[i + 1][0]) for i in range(len(occupied) - 1)]
    candidates = sorted((g for g in gaps if g[1] - g[0] > 0.25 * span),
                        key=lambda g: (-(g[1] - g[0]), g[0]))[:MAX_BREAKS]
    if sum(b - a for a, b in candidates) < 0.5 * span:
        return [(t_min, t_max)]
    clusters, start = [], t_min
    for a, b in sorted(candidates):
        clusters.append((start, a))
        start = b
    clusters.append((start, t_max))
    return clusters


def _cluster_years(clusters):
    """Années effectivement dessinées : l'étendue (+ 2 % de marge) sans rupture, la somme des blocs sinon."""
    if len(clusters) == 1:
        a, b = clusters[0]
        return (b - a) * 1.04
    return max(sum(b - a for a, b in clusters), MIN_SPAN_YEARS)


def _build_scale(clusters, x0, x1, min_cluster_px=0.0):
    """
    Échelle linéaire par morceaux. Sans rupture : 2 % de marge de chaque côté.

    Avec ruptures, les marges sont en px et non en années : 2 % d'un domaine de
    5 000 ans donneraient à un évènement isolé la moitié de la largeur. Chaque bloc
    garde CLUSTER_GUARD px de chaque côté, et au moins `min_cluster_px` au total
    (de quoi poser une étiquette) : un bloc trop court montre alors plus de temps
    vide autour de lui, au MÊME nombre de px par an que les autres blocs. La marge
    en temps ne mord jamais sur plus de 40 % du vide voisin.
    """
    if len(clusters) == 1:
        a, b = clusters[0]
        pad = (b - a) * 0.02
        return Scale(((a - pad, b + pad, x0, x1, False),)), (x1 - x0) / ((b - a) * 1.04)
    n = len(clusters)
    free = x1 - x0 - BREAK_PX * (n - 1)
    lengths = [max(b - a, 0.0) for a, b in clusters]
    fixed = set()
    ppy = None
    for _ in range(n + 1):
        flexible = sum(lengths[i] for i in range(n) if i not in fixed)
        budget = free - sum(max(min_cluster_px, 2 * CLUSTER_GUARD) for i in fixed) - 2 * CLUSTER_GUARD * (n - len(fixed))
        ppy = budget / max(flexible, MIN_SPAN_YEARS * 1e-3)
        grown = {i for i in range(n) if lengths[i] * ppy + 2 * CLUSTER_GUARD < min_cluster_px}
        if grown <= fixed:
            break
        fixed |= grown
    gaps = [clusters[i + 1][0] - clusters[i][1] for i in range(n - 1)]
    guards = []
    for i in range(n):
        wanted = max(min_cluster_px - lengths[i] * ppy, 2 * CLUSTER_GUARD) / 2 / ppy
        room = min([gaps[j] * 0.4 for j in (i - 1, i) if 0 <= j < n - 1])
        guards.append(min(wanted, room))
    segments, x = [], x0
    for i, (a, b) in enumerate(clusters):
        start, end = a - guards[i], b + guards[i]
        width = (end - start) * ppy
        segments.append((start, end, x, x + width, False))
        x += width
        if i + 1 < n:
            segments.append((end, clusters[i + 1][0] - guards[i + 1], x, x + BREAK_PX, True))
            x += BREAK_PX
    # Les arrondis de la dernière passe se rattrapent sur le dernier bloc.
    last = segments[-1]
    segments[-1] = (last[0], last[1], last[2], max(x1, last[2] + 1), False)
    return Scale(tuple(segments)), ppy


_YEAR_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000)
_MONTH_STEPS = (1, 2, 3, 6)
_DAY_STEPS = (1, 2, 5, 10, 15)


def _tick_unit(ppy, min_px):
    for step in _DAY_STEPS:
        if step / 365.2425 * ppy >= min_px:
            return "day", step
    for step in _MONTH_STEPS:
        if step / 12 * ppy >= min_px:
            return "month", step
    for step in _YEAR_STEPS:
        if step * ppy >= min_px:
            return "year", step
    return "year", _YEAR_STEPS[-1]


def _ticks(scale, unit, step, lang):
    """[(t, libellé)] des graduations « rondes » de chaque segment non interrompu."""
    out = []
    for t0, t1, _, _, broken in scale.segments:
        if broken:
            continue
        first_year = to_historical(math.floor(t0))
        last_year = to_historical(math.floor(t1))
        if unit == "year":
            low = first_year - first_year % step - step
            year = low
            while year <= last_year + step:
                if year != 0:
                    t = float(to_astronomical(year))
                    if t0 <= t <= t1:
                        out.append((t, format_year(year, lang)))
                year += step
            continue
        year = first_year
        while year <= last_year:
            if year != 0:
                astro = to_astronomical(year)
                for month in range(1, 13):
                    if unit == "month":
                        if (month - 1) % step:
                            continue
                        t = decimal_year(astro, month)
                        if t0 <= t <= t1:
                            label = format_date(parse_date(f"{year}-{month:02d}"), lang)
                            out.append((t, label))
                        continue
                    last = days_in_month(astro, month)
                    for day in range(1, last + 1, step):
                        if day + step / 2 > last + 1 and day != 1:
                            continue
                        t = decimal_year(astro, month, day)
                        if t0 <= t <= t1:
                            label = translate("timeline.date.day_month", lang,
                                              day=translate("timeline.date.day_first", lang) if day == 1 else day,
                                              month=translate(f"timeline.date.month_{month}", lang))
                            out.append((t, label))
            year += 1
    return sorted(set(out))


# ──────────────────────────────────────────────────────────────
# Document → éléments résolus
# ──────────────────────────────────────────────────────────────
def _parse_elements(doc):
    as_of = doc.get("as_of")
    eras, periods, events = [], [], []
    for era in doc.get("eras", []):
        start = parse_date(era["start"], era.get("precision"))
        end = parse_date(era["end"], None if era["end"] == "present" else era.get("precision"),
                         allow_present=True, as_of=as_of)
        eras.append((era, start, end))
    for period in doc.get("periods", []):
        start = parse_date(period["start"], period.get("precision"))
        end = parse_date(period["end"], None if period["end"] == "present" else period.get("precision"),
                         allow_present=True, as_of=as_of)
        periods.append((period, start, end))
    for event in doc.get("events", []):
        events.append((event, parse_date(event["date"], event.get("precision"))))
    return eras, periods, events


def _lanes(doc):
    tracks = list(doc.get("tracks") or [])
    ordered = sorted(enumerate(tracks), key=lambda item: (item[1].get("order", item[0] + 1), item[0]))
    return [track for _, track in ordered]


def _era_columns(eras, scale):
    """Colonnes disjointes ; les ères partageant une année se rejoignent au milieu."""
    columns = []
    for era, start, end in sorted(eras, key=lambda e: (e[1].t0, e[2].t1, e[0]["id"])):
        x0, x1 = scale.x(start.t0), scale.x(end.t1)
        if columns and x0 < columns[-1][2]:
            cut = (x0 + columns[-1][2]) / 2
            columns[-1][2] = cut
            x0 = cut
        columns.append([era, x0, x1])
    return columns


def _column_at(columns, x):
    return next((i for i, (_, left, right) in enumerate(columns) if left <= x <= right), None)


class _LaneState:
    """Tout ce qu'une piste accumule d'une passe à l'autre, dans son propre repère."""

    def __init__(self, index, track, color, shape, date_fill, marked=frozenset()):
        self.index = index
        self.marked = marked        # éléments à signaler « citation introuvable »
        self.track = track
        self.color = color
        self.shape = shape
        self.date_fill = date_fill
        self.grid = _Grid()
        self.prims = []
        self.units = []
        self.failed = []
        self.periods = []           # (élément, dates, x0, x1, mode, rangée, largeur du libellé)
        self.period_rows = 0


# ──────────────────────────────────────────────────────────────
# Mise en page
# ──────────────────────────────────────────────────────────────
def layout(doc, options=None, measure=None) -> Layout:
    """
    Document `ankigen.timeline/1` VALIDÉ → Layout.

    En largeur automatique, si des étiquettes ne trouvent pas de place, le
    canevas est élargi de 25 % et tout recommence, trois fois au plus (§7.6).
    """
    if measure is None:
        raise ValueError("layout() a besoin d'une fonction de mesure du texte")
    options = options or LayoutOptions()
    if options.orientation != "horizontal":
        raise ValueError("seule l'orientation horizontale existe en v1")
    width = None
    result = None
    for iteration in range(MAX_WIDEN + 1):
        result, failures, natural = _attempt(doc, options, measure, width, iteration)
        if options.width_mode == "fixed" or not failures or result.width >= WIDTH_MAX:
            break
        width = min(WIDTH_MAX, math.ceil(result.width * 1.25))
    return result


def _attempt(doc, options, measure, forced_width, iteration):
    density = DENSITIES[options.density]
    label_max = options.label_max_width or density["label_max_width"]
    max_levels = options.max_levels_per_side or density["max_levels"]
    theme = THEMES[options.theme]
    lang = options.lang or doc.get("lang") or "en"
    bg, ink, secondary = theme["bg"], theme["ink"], theme["secondary"]

    eras, periods, events = _parse_elements(doc)
    tracks = _lanes(doc)
    lanes_spec = tracks or [None]
    lane_of = {track["id"]: i for i, track in enumerate(tracks)}

    # ── Couleurs des pistes ; un même cercle pour tous les événements ───
    palette = theme["palette"]
    marked = frozenset(options.unverified) if options.show_unverified else frozenset()
    lane_states = []
    for i, track in enumerate(lanes_spec):
        color = palette[i % len(palette)]
        if track and track.get("color") and options.theme != "print":
            color = readable(track["color"], [bg], 3.0)
        lane_bg = theme["lane_bg"][i % 2]
        date_fill = readable(color, [bg, lane_bg], 4.5)
        lane_states.append(_LaneState(i, track, color, SHAPES[i % len(SHAPES)], date_fill, marked))

    def lane_index(element):
        return lane_of.get(element.get("track"), 0) if tracks else 0

    # ── Gouttière des libellés de piste ──────────────────────────────────
    lane_labels = []
    gutter = 0.0
    if tracks:
        widest = max(measure(t["label"], SIZES["lane"], 600) for t in tracks)
        gutter_text = min(GUTTER_MAX, widest)
        for track in tracks:
            lane_labels.append(wrap(track["label"], gutter_text, SIZES["lane"], 600, measure)[:3])
        gutter = gutter_text + GUTTER_PAD
    plot_left = MARGIN + gutter

    # ── Domaine, ruptures, largeur ───────────────────────────────────────
    items = []
    for _, start, end in eras + periods:
        items.append((start.t0, end.t1, False))
    for _, date in events:
        point = date.precision in ("day", "month", "year")
        items.append((date.position, date.position, True) if point else (date.t0, date.t1, False))
    clusters = _clusters(items, options.axis_breaks == "auto")
    kept_years = _cluster_years(clusters)
    chrome = plot_left + MARGIN
    min_cluster = label_max + 2 * CLUSTER_GUARD
    if len(clusters) > 1:
        chrome += BREAK_PX * (len(clusters) - 1) + min_cluster * len(clusters)

    if options.width_mode == "fixed":
        width = int(options.width_px)
    elif forced_width is not None:
        width = forced_width
    else:
        gaps = []
        per_lane = defaultdict(list)
        for event, date in events:
            per_lane[lane_index(event)].append(date.position)
        for positions in per_lane.values():
            positions.sort()
            gaps.extend(b - a for a, b in zip(positions, positions[1:]) if b - a > 1e-9)
        if gaps:
            gaps.sort()
            p20 = gaps[int(0.2 * (len(gaps) - 1))]
            target_gap = 14 if options.density == "compact" else TARGET_GAP_PX
            natural = chrome + kept_years * target_gap / p20
        else:
            natural = 1200
        width = int(max(WIDTH_MIN, min(WIDTH_MAX, math.ceil(natural))))
    plot_right = width - MARGIN
    scale, ppy = _build_scale(clusters, plot_left, plot_right, min_cluster)
    era_bands = _era_columns(eras, scale)
    era_fills = [mix(bg, theme["era_palette"][i % len(theme["era_palette"])],
                     0.20 if options.theme == "dark" else 0.10)
                 for i in range(len(era_bands))]
    for state in lane_states:
        lane_fill = mix(bg, state.color, 0.055) if options.theme != "print" else bg
        state.date_fill = readable(state.color, [bg, lane_fill] + era_fills, 4.5)
        state.interval_fill = None if options.theme == "print" else mix(
            bg, state.color, 0.20 if options.theme == "dark" else 0.10)

    # Zones interdites aux étiquettes : ruptures d'axe.
    break_boxes = [(x0 - 2, -1e6, x1 + 2, 1e6) for _, _, x0, x1 in scale.breaks]

    # ── Durées : rectangles titrés, contenant leurs évènements ─────────
    period_notes = []
    by_lane = defaultdict(list)
    for period, start, end in periods:
        by_lane[lane_index(period)].append((period, start, end))
    for lane, items_in_lane in by_lane.items():
        state = lane_states[lane]
        entries = []
        for period, start, end in items_in_lane:
            x0 = min(scale.x(start.t0), plot_right - BAR_MIN)
            x1 = max(scale.x(end.t1), x0 + BAR_MIN)
            weight = 600
            label = period["label"] + (" *" if period.get("origin") == "model" else "")
            w = measure(label, SIZES["label"], weight)
            title_lines = wrap(label, x1 - x0 - 2 * BAR_PAD, SIZES["label"], weight, measure)
            mode, reach = "inside", x1
            if len(title_lines) > 3:
                mode = "note"
                period_notes.append((x0, lane, period["id"]))
            date_line = format_range(start, end, lang, approx=period.get('approx', False))
            date_inside = measure(date_line, SIZES["date"], 400) <= x1 - x0 - 2 * BAR_PAD
            title_h = _text_height(SIZES["label"], len(title_lines)) if mode == "inside" else 2 * BADGE_R
            header_h = title_h + 2 * BAR_PAD
            if date_inside:
                header_h += _text_height(SIZES["date"], 1) + DATE_LABEL_GAP
            note_text = f"{date_line} — {label}"
            entries.append({"period": period, "start": start, "end": end, "x0": x0, "x1": x1,
                            "mode": mode, "reach": reach, "label": label, "weight": weight, "w": w,
                            "note_text": note_text, "title_lines": title_lines, "date_line": date_line,
                            "date_inside": date_inside, "header_h": header_h, "height": header_h,
                            "events": [], "child_prims": []})
        # Partitionnement glouton d'intervalles : optimal en nombre de rangées.
        entries.sort(key=lambda e: (e["x0"], -e["period"]["importance"], e["period"]["id"]))
        row_ends = []
        for entry in entries:
            for r, end_x in enumerate(row_ends):
                # Les rectangles consécutifs peuvent partager leur bord : le
                # padding intérieur sépare déjà leurs titres et événements.
                if end_x <= entry["x0"] + 1e-6:
                    entry["row"] = r
                    row_ends[r] = entry["reach"]
                    break
            else:
                entry["row"] = len(row_ends)
                row_ends.append(entry["reach"])
        state.periods = entries
        state.period_rows = len(row_ends)

    owners = {}
    for event, date in events:
        state = lane_states[lane_index(event)]
        candidates = [entry for entry in state.periods
                      if entry["start"].t0 <= date.t0 and date.t1 <= entry["end"].t1]
        if candidates:
            entry = min(candidates, key=lambda e: (e["end"].t1 - e["start"].t0, e["period"]["id"]))
            owners[event["id"]] = entry
            entry["events"].append((scale.x(date.position), event["id"], event, date))

    # ── Évènements : unités de placement (évènements simultanés regroupés) ──
    per_lane_events = defaultdict(list)
    for event, date in events:
        if event["id"] in owners:
            continue
        per_lane_events[lane_index(event)].append((scale.x(date.position), event["id"], event, date))
    anchors = []
    grouped_count = 0
    for lane, entries in per_lane_events.items():
        state = lane_states[lane]
        entries.sort(key=lambda e: (e[0], e[1]))
        groups = []
        for entry in entries:
            radius = MARKER_R[entry[2]["importance"]]
            if groups:
                last = groups[-1][-1]
                same_era = _column_at(era_bands, entry[0]) == _column_at(era_bands, last[0])
                if same_era and entry[0] - last[0] < MARKER_R[last[2]["importance"]] + radius + 2:
                    groups[-1].append(entry)
                    continue
            groups.append([entry])
        for members in groups:
            column = _column_at(era_bands, members[0][0])
            bounds = None
            if column is not None:
                _, x0, x1 = era_bands[column]
                # Une colonne trop étroite garde le placement libre et les notes de repli.
                if x1 - x0 >= 96:
                    bounds = (x0 + ERA_PAD, x1 - ERA_PAD)
            state.units.append(_make_unit(members, lang, measure, label_max, state, scale,
                                          compact=options.density == "compact", bounds=bounds))
            if len(members) == 1:
                anchors.append((members[0][1], members[0][3].position))
            else:
                grouped_count += len(members)

    # ── Passe 1 : marqueurs et moustaches, puis étiquettes complètes ────
    d_first, d_step = density["level_first"], density["level_step"]
    d_limit = density["level_first"] + max_levels * density["level_pitch"]
    left_limit = plot_left + 4 if tracks else MARGIN
    right_limit = plot_right
    for state in lane_states:
        for box in break_boxes:
            state.grid.add(box, "break")
        for unit in state.units:
            for prim in unit["graphics"]:
                state.prims.append(prim)
                state.grid.add(prim.bbox, "whisker" if prim.role == "whisker" else "marker")
        order = sorted(state.units, key=lambda u: (-u["importance"], u["x"], u["ref"]))
        for rank, unit in enumerate(order):
            spot = None
            for lines, truncated in unit["variants"]:
                w, h = _unit_size(unit, lines, measure)
                left, right = unit.get("bounds") or (left_limit, right_limit)
                spot = _find_spot(state.grid, unit["x"], unit["r"], w, h, rank % 2 == 0,
                                  _label_modes, left, right, d_first, d_step, d_limit)
                if spot:
                    unit["placed"] = (spot, lines, truncated)
                    _commit_label(state, unit, spot, lines, measure)
                    break
            if not spot:
                state.failed.append(unit)

    # Chaque durée possède son espace de placement : ses enfants ne peuvent
    # ni en sortir ni se confondre avec ceux d'une période voisine.
    container_states = []
    for state in lane_states:
        for entry in state.periods:
            child = _LaneState(state.index, state.track, state.color, "circle", state.date_fill, marked)
            child.date_fill = readable(state.color, [bg, mix(bg, state.color,
                                      0.20 if options.theme == "dark" else 0.10)], 4.5)
            child.interval_fill = state.interval_fill
            entry["child"] = child
            container_states.append(child)
            groups = []
            for member in sorted(entry["events"], key=lambda m: (m[0], m[1])):
                if groups and member[0] - groups[-1][-1][0] < 2 * MARKER_R[2] + 2:
                    groups[-1].append(member)
                else:
                    groups.append([member])
            bounds = (entry["x0"] + BAR_PAD, entry["x1"] - BAR_PAD)
            for members in groups:
                unit = _make_unit(members, lang, measure, label_max, child, scale,
                                  compact=options.density == "compact", bounds=bounds)
                child.units.append(unit)
                for prim in unit["graphics"]:
                    child.prims.append(prim)
                    child.grid.add(prim.bbox, "marker")
                if len(members) == 1:
                    anchors.append((members[0][1], members[0][3].position))
                else:
                    grouped_count += len(members)
            for rank, unit in enumerate(child.units):
                for lines, truncated in unit["variants"]:
                    w, h = _unit_size(unit, lines, measure)
                    spot = _find_spot(child.grid, unit["x"], unit["r"], w, h, rank % 2 == 0,
                                      _label_modes, *bounds, d_first, d_step, d_limit)
                    if spot:
                        unit["placed"] = (spot, lines, truncated)
                        _commit_label(child, unit, spot, lines, measure)
                        break
                else:
                    child.failed.append(unit)

    failures = sum(len(state.failed) for state in lane_states)
    if failures and options.width_mode == "auto" and iteration < MAX_WIDEN and width < WIDTH_MAX:
        # Élargir et tout recommencer coûte moins cher que finir cette tentative.
        return Layout(width=width, height=0, primitives=()), failures, width

    # ── Numérotation globale des notes (ordre chronologique) ────────────
    note_items = [(x, lane, ref) for x, lane, ref in period_notes]
    for state in lane_states + container_states:
        for unit in state.failed:
            note_items.append((unit["x"], state.index, unit["ref"]))
    note_items.sort()
    numbers = {ref: i + 1 for i, (_, _, ref) in enumerate(note_items)}

    # ── Passes 2 et 3 : pastilles numérotées, puis grappes ───────────────
    cluster_count = 0
    for state in lane_states:
        leftovers = []
        order = sorted(state.failed, key=lambda u: (-u["importance"], u["x"], u["ref"]))
        for rank, unit in enumerate(order):
            label = str(numbers[unit["ref"]])
            required = unit["importance"] == 3   # un pivot n'entre jamais dans une grappe
            if not _place_badge(state, unit, label, measure, rank, left_limit, right_limit,
                                d_first, d_step, d_limit, ink, bg, required=required):
                leftovers.append(unit)
        leftovers.sort(key=lambda u: u["x"])
        clusters = []
        for unit in leftovers:
            if clusters and unit["x"] - clusters[-1][-1]["x"] < 3 * BADGE_R + 8:
                clusters[-1].append(unit)
            else:
                clusters.append([unit])
        for members in clusters:
            if len(members) == 1:
                _place_badge(state, members[0], str(numbers[members[0]["ref"]]), measure, 0,
                             left_limit, right_limit, d_first, d_step, d_limit, ink, bg, required=True)
                continue
            cluster_count += 1
            _place_cluster(state, members, measure, left_limit, right_limit, d_first, d_step, d_limit,
                           ink, bg)

    for state in container_states:
        for rank, unit in enumerate(state.failed):
            _place_badge(state, unit, str(numbers[unit["ref"]]), measure, rank,
                         left_limit, right_limit, d_first, d_step, d_limit, ink, bg, required=True)
    for state in lane_states:
        for entry in state.periods:
            child = entry["child"]
            child_prims = [_resolve_colors(p, ink, bg) for p in child.prims]
            if child_prims:
                child_prims = _pack_event_blocks(child_prims)
                child_top = min(p.bbox[1] for p in child_prims)
                child_bottom = max(p.bbox[3] for p in child_prims)
                entry["child_prims"] = [_shift(p, entry["header_h"] + BAR_PAD - child_top, state.index)
                                        for p in child_prims]
                entry["height"] += child_bottom - child_top + 2 * BAR_PAD

    # ── Assemblage vertical ──────────────────────────────────────────────
    prims = []
    lang_text = lambda key, **params: translate(key, lang, **params)   # noqa: E731
    y = MARGIN
    title_lines = wrap(doc["title"], width - 2 * MARGIN, SIZES["title"], 600, measure)
    prims.append(_text(MARGIN, y + ASCENT * SIZES["title"], title_lines, SIZES["title"], 600, ink,
                       "start", measure, "title"))
    y += _text_height(SIZES["title"], len(title_lines)) + 4
    if doc.get("subtitle"):
        sub_lines = wrap(doc["subtitle"], width - 2 * MARGIN, SIZES["subtitle"], 400, measure)
        prims.append(_text(MARGIN, y + ASCENT * SIZES["subtitle"], sub_lines, SIZES["subtitle"], 400,
                           secondary, "start", measure, "subtitle"))
        y += _text_height(SIZES["subtitle"], len(sub_lines))
    y += 10 if options.density == "compact" else 16

    # Les titres tiennent dans l'en-tête de leur colonne. Les ères minuscules
    # gardent un libellé extérieur complet, rangé sans recouvrement.
    era_headers = []
    outside = []
    header_h = 0
    for i, (era, x0, x1) in enumerate(era_bands):
        lines = wrap(era["label"], max(1, x1 - x0 - 2 * ERA_PAD), SIZES["era"], 600, measure)
        if x1 - x0 >= 80 and len(lines) <= 4:
            era_headers.append((i, era, x0, x1, lines))
            header_h = max(header_h, _text_height(SIZES["era"], len(lines)) + 2 * ERA_PAD)
        else:
            lines = wrap(era["label"], min(180, plot_right - plot_left), SIZES["era"], 600, measure)
            w = max(measure(line, SIZES["era"], 600) for line in lines)
            lx = min(max((x0 + x1 - w) / 2, plot_left), plot_right - w)
            ly = y
            h = _text_height(SIZES["era"], len(lines))
            while True:
                blockers = [box for box in outside if _intersects((lx, ly, lx + w, ly + h), box, 4)]
                if not blockers:
                    break
                ly = max(box[3] for box in blockers) + 4
            prims.append(_text(lx, ly + ASCENT * SIZES["era"], lines, SIZES["era"], 600,
                               secondary, "start", measure, "era-label", era["id"]))
            outside.append((lx, ly, lx + w, ly + h))
    if outside:
        y = max(box[3] for box in outside) + 8

    # Axe haut : libellés de graduation, puis la ligne.
    unit_name, step = _tick_unit(ppy, density["min_tick_px"])
    ticks = _ticks(scale, unit_name, step, lang)
    tick_base = y + ASCENT * SIZES["tick"]
    tick_texts = _thin_ticks(ticks, scale, tick_base, measure, plot_left, plot_right, secondary)
    prims.extend(tick_texts)
    y = tick_base + DESCENT * SIZES["tick"] + 6
    axis_y = y
    band_top = axis_y + 8
    lanes_top = band_top + header_h
    for i, era, x0, x1, lines in era_headers:
        color = theme["era_palette"][i % len(theme["era_palette"])]
        header_fill = mix(bg, color, 0.30 if options.theme == "dark" else 0.16)
        prims.append(Rect(x=x0, y=band_top, w=x1 - x0, h=header_h,
                          fill=None if options.theme == "print" else header_fill,
                          role="era-header", ref=era["id"]))
        prims.append(_text(x0 + ERA_PAD, band_top + ERA_PAD + ASCENT * SIZES["era"], lines,
                           SIZES["era"], 600, readable(color, [header_fill], 4.5),
                           "start", measure, "era-label", era["id"]))

    # Pistes.
    lane_bounds = []
    cursor = lanes_top
    for state in lane_states:
        label_lines = lane_labels[state.index] if tracks else None
        local, local_top, local_bottom = _assemble_lane(state, label_lines, measure, density,
                                                        numbers, ink, bg, secondary, options.theme)
        offset = cursor - local_top
        lane_bg = mix(bg, state.color, 0.055) if options.theme != "print" else None
        top = round(cursor, 2)
        bottom = round(cursor + (local_bottom - local_top), 2)
        if lane_bg:
            prims.append(Rect(x=MARGIN, y=top, w=width - 2 * MARGIN, h=round(bottom - top, 2),
                              rx=8, fill=lane_bg, role="lane-bg", lane=state.index))
        for prim in local:
            prims.append(_shift(prim, offset, state.index))
        lane_bounds.append((top, bottom))
        cursor = bottom + LANE_GAP
    lanes_bottom = cursor - LANE_GAP

    # Axe : ligne interrompue aux ruptures, graduations, lignes de grille, zigzags.
    chrome = []
    for t0, t1, x0, x1, broken in scale.segments:
        if not broken:
            chrome.append(Line(x1=x0, y1=axis_y, x2=x1, y2=axis_y, stroke=theme["axis"], width=1, role="axis"))
    for tick in tick_texts:
        chrome.append(Line(x1=tick.x, y1=axis_y - 4, x2=tick.x, y2=axis_y, stroke=theme["axis"], width=1,
                           role="tick"))
        chrome.append(Line(x1=tick.x, y1=axis_y, x2=tick.x, y2=lanes_bottom, stroke=theme["grid"],
                           width=1, role="gridline"))
    for _, _, x0, x1 in scale.breaks:
        chrome.append(_zigzag_h(x0, x1, axis_y, theme["axis"]))
        chrome.append(_zigzag_v((x0 + x1) / 2, axis_y + 4, lanes_bottom, theme["axis"]))
    # Colonnes colorées : en-tête et évènements partagent le même rectangle.
    bands = []
    bottom_axis = lanes_bottom - MARGIN > 600
    band_bottom = lanes_bottom + (8 if bottom_axis else 0)
    for i, (era, x0, x1) in enumerate(era_bands):
        color = theme["era_palette"][i % len(theme["era_palette"])]
        bands.append(Rect(x=x0, y=band_top, w=x1 - x0, h=band_bottom - band_top,
                          fill=None if options.theme == "print" else era_fills[i],
                          stroke=mix(bg, color, 0.35), role="era-band", ref=era["id"]))
        bands.append(Rect(x=x0, y=band_top, w=x1 - x0, h=3, fill=color,
                          role="era-accent", ref=era["id"]))
    y = lanes_bottom
    if bottom_axis:
        y += 8
        for t0, t1, x0, x1, broken in scale.segments:
            if not broken:
                chrome.append(Line(x1=x0, y1=y, x2=x1, y2=y, stroke=theme["axis"], width=1, role="axis"))
        base = y + 6 + ASCENT * SIZES["tick"]
        for tick in tick_texts:
            chrome.append(Line(x1=tick.x, y1=y, x2=tick.x, y2=y + 4, stroke=theme["axis"], width=1, role="tick"))
            prims.append(replace(tick, y=round(base, 2)))
        y = base + DESCENT * SIZES["tick"]
    y += 12 if options.density == "compact" else 20

    # ── Légende ──────────────────────────────────────────────────────────
    notes = []
    for x, lane, ref in note_items:
        notes.append({"number": numbers[ref], "ref": ref, "lane": lane})
    legend, y, note_rows = _legend(doc, tracks, lane_states, notes, numbers, scale, y, width, measure,
                                   lang_text, ink, secondary, bg, events, periods)
    prims.extend(legend)
    height = math.ceil(y + MARGIN)

    # Ordre de dessin : fonds, bandes, grille, puis le reste (le rendu respecte cet ordre).
    background = [p for p in prims if p.role == "lane-bg"]
    others = [p for p in prims if p.role != "lane-bg"]
    ordered = tuple(background + bands + chrome + others)

    labeled = sum(1 for p in ordered if p.role in ("event-label", "period-label"))
    warnings = []
    for state in lane_states + container_states:
        for unit in state.units:
            if unit.get("placed") and unit["placed"][2]:
                warnings.append({"code": "label_truncated", "ref": unit["ref"], "params": {}})
    if notes:
        warnings.append({"code": "labels_in_notes", "params": {"count": len(notes)}})

    spans = tuple((e["id"], s.t0, en.t1) for e, s, en in eras + periods)
    elements = tuple(e["id"] for e, _, _ in eras) + tuple(p["id"] for p, _, _ in periods) + \
        tuple(e["id"] for e, _ in events)
    desc = _describe(doc, eras, periods, events, lang)
    stats = {
        "elements": len(elements), "labeled": labeled, "grouped": grouped_count,
        "notes": len(notes), "clusters": cluster_count, "breaks": len(scale.breaks),
        "width": width, "height": height, "iterations": iteration + 1,
        "period_rows": [state.period_rows for state in lane_states],
        "containers": [{"id": entry["period"]["id"], "events": [e[1] for e in entry["events"]]}
                       for state in lane_states for entry in state.periods],
        "eras": [{"id": era["id"], "color": theme["era_palette"][i % len(theme["era_palette"])]}
                 for i, (era, _, _) in enumerate(era_bands)],
        # Couleur et forme réelles de chaque piste : le rail de l'éditeur les reprend.
        "tracks": [{"id": state.track["id"], "color": state.color, "shape": state.shape}
                   for state in lane_states if state.track],
    }
    return (Layout(width=width, height=height, primitives=ordered,
                   notes=tuple({"number": n["number"], "ref": n["ref"], "text": note_rows[n["ref"]]}
                               for n in notes),
                   stats=stats, warnings=tuple(warnings), scale=scale, lanes=tuple(lane_bounds),
                   anchors=tuple(sorted(anchors)), spans=spans, elements=elements, desc=desc,
                   theme=dict(theme)),
            failures, width)


# ──────────────────────────────────────────────────────────────
# Unités d'évènements et étiquettes
# ──────────────────────────────────────────────────────────────
def _block_height(lines):
    date_part = (ASCENT + DESCENT) * SIZES["date"] + DATE_LABEL_GAP
    return date_part + _text_height(SIZES["label"], lines)


def _unit_size(unit, lines, measure):
    w = max(measure(line, SIZES["label"], unit["weight"]) for line in lines)
    if unit["inline"]:
        return unit["date_w"] + INLINE_DATE_GAP + w, _text_height(SIZES["label"], len(lines))
    return max(w, unit["date_w"]), _block_height(len(lines))


def _label_modes(sx, w):
    """Décalages de l'étiquette par rapport à sa tige, dans l'ordre de préférence (§7.6)."""
    return (("middle", sx, sx - w / 2), ("middle", sx - w / 4, sx - 3 * w / 4),
            ("middle", sx + w / 4, sx - w / 4), ("start", sx - 6, sx - 6), ("end", sx + 6, sx + 6 - w))


def _badge_modes(sx, w):
    return (("middle", sx, sx - w / 2), ("middle", sx - 0.75 * w, sx - 1.25 * w),
            ("middle", sx + 0.75 * w, sx + 0.25 * w))


def _stem_box(sx, r, d, above):
    near, far = r + STEM_START, d - STEM_GAP
    if far <= near:
        return None
    return (sx - 1, -far, sx + 1, -near) if above else (sx - 1, near, sx + 1, far)


def _find_spot(grid, sx, r, w, h, prefer_above, modes, left, right, d_first, d_step, d_limit,
               with_stem=True):
    """
    Premier emplacement libre : niveaux croissants, côté préféré d'abord, puis les
    décalages horizontaux. `d_limit` None : pas de limite. `with_stem` False : pas
    de tige (dernier recours, voir _must_place).
    """
    d = d_first
    while d_limit is None or d + h <= d_limit + 1e-9:
        for above in (prefer_above, not prefer_above):
            top = -d - h if above else d
            candidates = list(modes(sx, w))
            # Aux limites d'une ère ou du canevas, aligner le bloc sur le bord disponible.
            if w <= right - left:
                x0 = max(left, min(sx - w / 2, right - w))
                candidates.append(("start", x0, x0))
            for anchor, ax, x0 in candidates:
                if x0 < left or x0 + w > right:
                    continue
                box = (x0, top, x0 + w, top + h)
                if grid.hits(_inflate(box, LABEL_MARGIN)):
                    continue
                stem = _stem_box(sx, r, d, above) if with_stem else None
                if stem and grid.hits(stem, kinds=("text", "badge"), gap=TEXT_GAP):
                    continue
                return {"above": above, "d": d, "anchor": anchor, "ax": ax, "box": box, "stem": stem}
        d += d_step
        if d > 1e5:
            break
    return None


def _must_place(grid, sx, r, w, h, prefer_above, modes, left, right, d_first, d_step, d_limit):
    """
    Emplacement garanti, pour ce qui ne peut pas finir sans trace (pivots, grappes).

    Une tige qui monte vers un niveau lointain traverse toutes les étiquettes de sa
    colonne : au-delà d'un certain encombrement, aucun niveau n'est joignable. On
    essaie donc d'abord avec tige jusqu'au double de la limite, puis sans tige, au
    premier emplacement libre à l'aplomb du marqueur. Il en existe toujours un :
    au-dessus de tous les obstacles.
    """
    spot = _find_spot(grid, sx, r, w, h, prefer_above, modes, left, right, d_first, d_step, 2 * d_limit)
    if spot:
        return spot
    return _find_spot(grid, sx, r, w, h, prefer_above, modes, left, right, d_first, d_step, None,
                      with_stem=False)


def _make_unit(members, lang, measure, label_max, state, scale, *, compact=False, bounds=None):
    events = [m[2] for m in members]
    dates = [m[3] for m in members]
    ids = [m[1] for m in members]
    importance = max(e["importance"] for e in events)
    x = sum(m[0] for m in members) / len(members)
    full_dates = [format_date(d, lang, approx=e.get("approx", False)) for e, d in zip(events, dates)]
    formatted = [_compact_date(d, lang, e.get("approx", False)) if compact else full
                 for e, d, full in zip(events, dates, full_dates)]
    if len(set(formatted)) == 1:
        date_line = formatted[0]
    else:
        first = min(range(len(dates)), key=lambda i: (dates[i].t0, i))
        last = max(range(len(dates)), key=lambda i: (dates[i].t0, -i))
        date_line = f"{formatted[first]}–{formatted[last]}"
    labels = [e["label"] + (" *" if e.get("origin") == "model" else "") for e in events]
    label = " · ".join(labels)
    weight = 600 if importance == 3 else 400
    r = MARKER_R[importance]
    unverified = any(i in state.marked for i in ids)
    ref = "+".join(ids)
    date_w = measure(date_line, SIZES["date"], 600)
    available = min(label_max, bounds[1] - bounds[0]) if bounds else label_max
    inline_width = available - date_w - INLINE_DATE_GAP
    inline = (compact and inline_width >= 64
              and len(wrap(label, inline_width, SIZES["label"], weight, measure)) <= 3)
    label_width = available - date_w - INLINE_DATE_GAP if inline else available
    graphics = []
    for _, event_id, event, date in members:
        if date.precision not in ("day", "month", "year"):
            # Même rectangle pour une date couvrant une décennie, un siècle…
            x0, x1 = scale.x(date.t0), scale.x(date.t1)
            graphics.append(Rect(x=x0, y=-BAR_H / 2, w=x1-x0, h=BAR_H,
                                 fill=state.interval_fill, stroke=state.color,
                                 role="whisker", ref=event_id, lane=state.index))
    marker = Marker(shape=state.shape, cx=x, cy=0.0, r=r,
                    fill=state.color, stroke="ink" if unverified else "bg",
                    stroke_width=2.0 if unverified else MARKER_RING,
                    role="marker", ref=ref, lane=state.index)
    graphics.append(marker)
    return {
        "ids": ids, "ref": ref, "x": x, "r": r, "importance": importance, "weight": weight,
        "date_line": date_line, "date_w": date_w, "inline": inline, "bounds": bounds,
        "label": label, "variants": label_variants(label, label_width, SIZES["label"], weight, measure),
        "marker": marker, "graphics": graphics, "lane": state.index,
        "note_text": f"{'–'.join(dict.fromkeys(full_dates))} — {label}",
    }


def _compact_date(date, lang, approx=False):
    """Date numérique locale, en conservant précision, avant J.-C. et approximation."""
    year = str(abs(date.year))
    if date.precision == "day":
        value = (f"{date.day:02d}/{date.month:02d}/{year}" if lang == "fr"
                 else f"{year}-{date.month:02d}-{date.day:02d}")
    elif date.precision == "month":
        value = f"{date.month:02d}/{year}" if lang == "fr" else f"{year}-{date.month:02d}"
    else:
        return format_date(date, lang, approx=approx, short=True)
    if date.bc:
        value = translate("timeline.date.bc", lang, date=value)
    return translate("timeline.date.approx", lang, date=value) if approx else value


def _commit_label(state, unit, spot, lines, measure):
    anchor, ax, box = spot["anchor"], spot["ax"], spot["box"]
    top = box[1]
    if unit["inline"]:
        anchor = "start"
        ax = box[0]
        label_base = date_base = top + ASCENT * SIZES["label"]
        label_x = ax + unit["date_w"] + INLINE_DATE_GAP
    else:
        date_base = top + ASCENT * SIZES["date"]
        label_base = date_base + DESCENT * SIZES["date"] + DATE_LABEL_GAP + ASCENT * SIZES["label"]
        label_x = ax
    date_text = _text(ax, date_base, [unit["date_line"]], SIZES["date"], 600, state.date_fill, anchor,
                      measure, "event-date", unit["ref"], state.index)
    label_text = _text(label_x, label_base, lines, SIZES["label"], unit["weight"], "ink", anchor, measure,
                       "event-label", unit["ref"], state.index)
    state.prims.extend([date_text, label_text])
    state.grid.add(_union(date_text.bbox, label_text.bbox), "text")
    if spot["stem"]:
        sx = unit["x"]
        y_near, y_far = (spot["stem"][3], spot["stem"][1]) if spot["above"] else (spot["stem"][1], spot["stem"][3])
        state.prims.append(Line(x1=sx, y1=y_near, x2=sx, y2=y_far, stroke=state.color, width=1,
                                role="stem", ref=unit["ref"], lane=state.index))
        state.grid.add(spot["stem"], "stem")


def badge_diameter(label, measure):
    return max(2 * BADGE_R, measure(label, SIZES["badge"], 600) + 8)


def _badge_prims(state, ref, cx, cy, label, measure, fill, ink, bg):
    text_fill = best_text_on(fill, ["#FFFFFF", "#1D1D1F", ink, bg])
    number = _text(cx, cy + (ASCENT - DESCENT) / 2 * SIZES["badge"], [label], SIZES["badge"], 600,
                   text_fill, "middle", measure, "badge", ref, state.index)
    r = badge_diameter(label, measure) / 2
    circle = Marker(shape="circle", cx=cx, cy=cy, r=r, fill=fill, stroke=None, stroke_width=0,
                    role="badge", ref=ref, lane=state.index)
    return circle, number, r


def _place_badge(state, unit, label, measure, rank, left, right, d_first, d_step, d_limit, ink, bg,
                 required=False):
    """
    Pastille numérotée à la place de l'étiquette : renvoi vers les notes de la légende.
    `required` : la pastille doit être posée (voir _must_place).
    """
    w = badge_diameter(label, measure)
    left, right = unit.get("bounds") or (left, right)
    find = _must_place if required else _find_spot
    spot = find(state.grid, unit["x"], unit["r"], w, w, rank % 2 == 0, _badge_modes,
                left, right, d_first, d_step, d_limit)
    if not spot:
        return False
    box = spot["box"]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    circle, number, _ = _badge_prims(state, unit["ref"], cx, cy, label, measure, state.color, ink, bg)
    state.prims.extend([circle, number])
    state.grid.add(circle.bbox, "badge")
    if spot["stem"]:
        y_near, y_far = (spot["stem"][3], spot["stem"][1]) if spot["above"] else (spot["stem"][1], spot["stem"][3])
        state.prims.append(Line(x1=unit["x"], y1=y_near, x2=unit["x"], y2=y_far, stroke=state.color,
                                width=1, role="stem", ref=unit["ref"], lane=state.index))
        state.grid.add(spot["stem"], "stem")
    unit["badge"] = label
    return True


def _place_cluster(state, members, measure, left, right, d_first, d_step, d_limit, ink, bg):
    """
    Grappe : des évènements trop proches pour tenir même en pastilles partagent une
    pastille « ×N » et une accolade sur leur étendue ; leurs notes sont listées.
    """
    x0 = min(u["x"] for u in members)
    x1 = max(u["x"] for u in members)
    r = max(u["r"] for u in members)
    ref = "+".join(u["ref"] for u in members)
    distance = r + 3
    while True:
        for above in (False, True):
            y0, y1 = (-distance, -distance - 3) if above else (distance, distance + 3)
            brace = Path(points=(("M", x0, y0), ("L", x0, y1), ("L", x1, y1), ("L", x1, y0)),
                         stroke=state.color, width=1.5, role="brace", ref=ref, lane=state.index)
            if not state.grid.hits(brace.bbox, kinds=("text", "badge"), gap=TEXT_GAP):
                break
        else:
            distance += d_step
            continue
        break
    state.grid.add(brace.bbox, "brace")
    state.prims.append(brace)
    label = f"×{len(members)}"
    w = badge_diameter(label, measure)
    cx_stem = (x0 + x1) / 2
    spot = _must_place(state.grid, cx_stem, max(abs(y0), abs(y1)) + 1, w, w, above, _badge_modes,
                       left, right, d_first, d_step, d_limit)
    box = spot["box"]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    circle, number, _ = _badge_prims(state, ref, cx, cy, label, measure, state.color, ink, bg)
    state.prims.extend([circle, number])
    state.grid.add(circle.bbox, "badge")
    for unit in members:
        unit["cluster"] = ref


def _pack_event_blocks(prims):
    """Aligner en haut les blocs disjoints en x, sans déplacer leurs dates en x.

    Un évènement, son marqueur et ses traits restent solidaires. Deux blocs
    séparés horizontalement peuvent partager la même hauteur sans collision.
    """
    by_ref = defaultdict(list)
    for prim in prims:
        by_ref[prim.ref].append(prim)
    blocks = []
    for ref, items in by_ref.items():
        box = items[0].bbox
        for prim in items[1:]:
            box = _union(box, prim.bbox)
        blocks.append((box, ref))
    components = []
    for box, ref in sorted(blocks, key=lambda b: (b[0][0], b[0][2], b[1])):
        if components and box[0] < components[-1][0][2] + LABEL_MARGIN:
            components[-1][0] = _union(components[-1][0], box)
            components[-1][1].append(ref)
        else:
            components.append([box, [ref]])
    offsets = {ref: -box[1] for box, refs in components for ref in refs}
    return [_shift(prim, offsets[prim.ref], prim.lane) for prim in prims]


def _assemble_lane(state, label_lines, measure, density, numbers, ink, bg, secondary, theme):
    """Primitives de la piste dans son repère, plus ses bornes verticales (haut, bas)."""
    prims = [_resolve_colors(prim, ink, bg) for prim in state.prims]
    if density["pack"]:
        prims = _pack_event_blocks(prims)
    extents = [p.bbox for p in prims]
    if state.units:
        top = min(b[1] for b in extents) if density["pack"] else min([-12.0] + [b[1] for b in extents])
        bottom = max(b[3] for b in extents) if density["pack"] else max([12.0] + [b[3] for b in extents])
    else:
        top = bottom = 0.0                # piste sans évènement : pas de zone vide
    middle = (top + bottom) / 2 if density["pack"] else 0.0
    # Périodes : rangées au-dessus de la zone des évènements.
    if state.period_rows:
        row_heights = [max(e["height"] for e in state.periods if e["row"] == r)
                       for r in range(state.period_rows)]
        block_bottom = top - 8 if state.units else 0.0
        block_top = block_bottom - sum(row_heights) - (state.period_rows - 1) * density["row_gap"]
        row_offsets = [sum(row_heights[:r]) + r * density["row_gap"]
                       for r in range(state.period_rows)]
        for entry in state.periods:
            y = block_top + row_offsets[entry["row"]]
            prims.extend(_period_prims(state, entry, y, measure, numbers, ink, bg, theme))
        top = block_top
        if not state.units:
            middle = (block_top + block_bottom) / 2
    # Libellé de la piste, centré sur la ligne de base (ou sur ses périodes), dans la gouttière.
    if label_lines:
        h = _text_height(SIZES["lane"], len(label_lines))
        label_top = middle - h / 2
        label = _text(MARGIN + 4, label_top + ASCENT * SIZES["lane"], label_lines, SIZES["lane"], 600,
                      readable(state.color, [bg], 4.5), "start", measure, "lane-label",
                      state.track["id"], state.index)
        prims.append(label)
        top = min(top, label.bbox[1])
        bottom = max(bottom, label.bbox[3])
    pad = density["lane_pad"]
    return prims, top - pad, bottom + pad


def _period_prims(state, entry, y, measure, numbers, ink, bg, theme):
    period = entry["period"]
    ref = period["id"]
    x0, x1 = entry["x0"], entry["x1"]
    body_fill = mix(bg, state.color, 0.20 if theme == "dark" else 0.10)
    header_fill = mix(bg, state.color, 0.30 if theme == "dark" else 0.16)
    out = [Rect(x=x0, y=y, w=x1-x0, h=entry["height"],
                fill=None if theme == "print" else body_fill,
                stroke=ink if ref in state.marked else mix(bg, state.color, 0.40),
                role="period-container", ref=ref, lane=state.index),
           Rect(x=x0, y=y, w=x1-x0, h=entry["header_h"],
                fill=None if theme == "print" else header_fill,
                role="period-header", ref=ref, lane=state.index),
           Rect(x=x0, y=y, w=x1-x0, h=3, fill=state.color,
                role="period-accent", ref=ref, lane=state.index)]
    baseline = y + BAR_PAD + ASCENT * SIZES["label"]
    if entry["mode"] == "inside":
        fill = readable(state.color, [header_fill, bg], 4.5)
        out.append(_text(x0 + BAR_PAD, baseline, entry["title_lines"], SIZES["label"], entry["weight"], fill,
                         "start", measure, "period-label", ref, state.index))
    else:
        diameter = badge_diameter(str(numbers[ref]), measure)
        circle, number, _ = _badge_prims(state, ref, x0 + BAR_PAD + diameter / 2,
                                        y + BAR_PAD + BADGE_R, str(numbers[ref]), measure,
                                        state.color, ink, bg)
        out.extend([circle, number])
    if entry["date_inside"]:
        date_y = y + entry["header_h"] - BAR_PAD - DESCENT * SIZES["date"]
        out.append(_text(x0 + BAR_PAD, date_y, [entry["date_line"]], SIZES["date"], 400,
                         readable(state.color, [header_fill, bg], 4.5), "start", measure,
                         "period-date", ref, state.index))
    out.extend(_shift(p, y, state.index) for p in entry["child_prims"])
    return out


def _resolve_colors(prim, ink, bg):
    if isinstance(prim, Text) and prim.fill == "ink":
        return replace(prim, fill=ink)
    if isinstance(prim, Marker):
        return replace(prim, fill=bg if prim.fill is None else prim.fill,
                       stroke=bg if prim.stroke == "bg" else ink if prim.stroke == "ink" else prim.stroke)
    return prim


def _shift(prim, dy, lane):
    """Translation verticale d'une primitive de piste, arrondie au centième de px."""
    r2 = lambda v: round(v, 2)   # noqa: E731
    if isinstance(prim, Text):
        return replace(prim, x=r2(prim.x), y=r2(prim.y + dy), lane=lane)
    if isinstance(prim, Rect):
        return replace(prim, x=r2(prim.x), y=r2(prim.y + dy), w=r2(prim.w), lane=lane)
    if isinstance(prim, Line):
        return replace(prim, x1=r2(prim.x1), y1=r2(prim.y1 + dy), x2=r2(prim.x2), y2=r2(prim.y2 + dy), lane=lane)
    if isinstance(prim, Marker):
        return replace(prim, cx=r2(prim.cx), cy=r2(prim.cy + dy), lane=lane)
    if isinstance(prim, Path):
        return replace(prim, points=tuple((c, r2(x), r2(y + dy)) for c, x, y in prim.points), lane=lane)
    return prim


def _zigzag_h(x0, x1, y, stroke):
    points, x, up = [("M", round(x0, 2), round(y, 2))], x0, True
    step = (x1 - x0) / 4
    for i in range(1, 5):
        points.append(("L", round(x0 + i * step, 2), round(y + (-4 if up else 4) if i < 4 else y, 2)))
        up = not up
    return Path(points=tuple(points), stroke=stroke, width=1.5, role="break")


def _zigzag_v(x, y0, y1, stroke):
    points, y, left = [("M", round(x, 2), round(y0, 2))], y0, True
    while y + 12 < y1:
        y += 12
        points.append(("L", round(x + (-3 if left else 3), 2), round(y, 2)))
        left = not left
    points.append(("L", round(x, 2), round(y1, 2)))
    return Path(points=tuple(points), stroke=stroke, width=1, role="break")


def _thin_ticks(ticks, scale, baseline, measure, left, right, fill):
    """Libellés de graduation sans chevauchement : un sur deux, puis un sur quatre…"""
    size = SIZES["tick"]
    candidates = []
    for i, (t, label) in enumerate(ticks):
        x = scale.x(t)
        w = measure(label, size, 400)
        if x - w / 2 < left - 8 or x + w / 2 > right:
            continue
        if any(bx0 - 2 < x + w / 2 and x - w / 2 < bx1 + 2 for _, _, bx0, bx1 in scale.breaks):
            continue
        candidates.append((i, x, w, label))
    keep = 1
    while True:
        kept = [c for c in candidates if c[0] % keep == 0]
        if all(b[1] - b[2] / 2 - (a[1] + a[2] / 2) >= 12 for a, b in zip(kept, kept[1:])):
            break
        keep *= 2
    return [Text(x=round(x, 2), y=round(baseline, 2), lines=(label,), size=size, weight=400, fill=fill,
                 anchor="middle", line_height=size * LINE_HEIGHT, widths=(round(w, 3),), role="tick-label")
            for _, x, w, label in kept]


def _legend(doc, tracks, lane_states, notes, numbers, scale, y, width, measure, lang_text, ink,
            secondary, bg, events, periods):
    """Pistes (couleur + forme), symboles, puis notes numérotées en colonnes."""
    prims = []
    size = SIZES["legend"]
    right = width - MARGIN
    note_rows = {}
    # Pistes : utile quand la couleur ne suffit pas (impression, daltonisme).
    if len(tracks) >= 2:
        x = MARGIN
        line_h = 20
        for state in lane_states:
            label = state.track["label"]
            w = measure(label, size, 400)
            if x + 16 + w > right and x > MARGIN:
                x, y = MARGIN, y + line_h
            prims.append(Marker(shape=state.shape, cx=round(x + 6, 2), cy=round(y + 8, 2), r=5, fill=state.color,
                                stroke=None, stroke_width=0, role="legend", ref=state.track["id"]))
            prims.append(_text(round(x + 16, 2), round(y + 8 + (ASCENT - DESCENT) / 2 * size, 2), [label],
                               size, 400, ink, "start", measure, "legend", state.track["id"]))
            x += 16 + w + 20
        y += line_h + 4
    symbols = []
    if any(e.get("origin") == "model" for e, _ in events) or any(p.get("origin") == "model" for p, _, _ in periods):
        symbols.append(lang_text("timeline.legend.off_course"))
    marked = lane_states[0].marked if lane_states else frozenset()
    if any(e["id"] in marked for e, _ in events if e.get("origin") != "model")             or any(p["id"] in marked for p, _, _ in periods):
        symbols.append(lang_text("timeline.legend.unverified"))
    if scale.breaks:
        symbols.append(lang_text("timeline.legend.axis_break"))
    if symbols:
        text = "   ".join(symbols)
        lines = wrap(text, right - MARGIN, size, 400, measure)
        prims.append(_text(MARGIN, round(y + ASCENT * size, 2), lines, size, 400, secondary, "start",
                           measure, "legend"))
        y += _text_height(size, len(lines)) + 8
    if notes:
        texts = {}
        for note in notes:
            texts[note["ref"]] = _note_text(note["ref"], lane_states)
        col_w = min(420, max(measure(t, size, 400) for t in texts.values()))
        cell_w = col_w + 2 * BADGE_R + 8
        columns = max(1, int((right - MARGIN + 24) // (cell_w + 24)))
        rows = [notes[i:i + columns] for i in range(0, len(notes), columns)]
        for row in rows:
            row_h = 0
            for c, note in enumerate(row):
                x = MARGIN + c * (cell_w + 24)
                lines = wrap(texts[note["ref"]], col_w, size, 400, measure)
                h = max(2 * BADGE_R, _text_height(size, len(lines)))
                state = lane_states[note["lane"]]
                circle, number, r = _badge_prims(state, note["ref"], round(x + BADGE_R, 2), round(y + BADGE_R, 2),
                                                 str(note["number"]), measure, state.color, ink, bg)
                prims.extend([replace(circle, lane=None), replace(number, lane=None)])
                prims.append(_text(round(x + 2 * BADGE_R + 8, 2), round(y + ASCENT * size + 1, 2), lines, size, 400,
                                   ink, "start", measure, "note", note["ref"]))
                note_rows[note["ref"]] = texts[note["ref"]]
                row_h = max(row_h, h)
            y += row_h + 8
    return prims, y, note_rows


def _note_text(ref, lane_states):
    for state in lane_states:
        for unit in state.units:
            if unit["ref"] == ref:
                return unit["note_text"]
        for entry in state.periods:
            if entry["period"]["id"] == ref:
                return entry.get("note_text") or entry["label"]
            for unit in entry["child"].units:
                if unit["ref"] == ref:
                    return unit["note_text"]
    return ref


def _describe(doc, eras, periods, events, lang):
    tracks = {t["id"]: t["label"] for t in doc.get("tracks") or []}
    out = []
    for era, start, end in eras:
        out.append(f"{format_range(start, end, lang, approx=era.get('approx', False))} — {era['label']}")
    for period, start, end in periods:
        track = tracks.get(period.get("track"))
        suffix = f" ({track})" if track else ""
        out.append(f"{format_range(start, end, lang, approx=period.get('approx', False))} — "
                   f"{period['label']}{suffix}")
    for event, date in sorted(events, key=lambda e: (e[1].t0, e[0]["id"])):
        track = tracks.get(event.get("track"))
        suffix = f" ({track})" if track else ""
        out.append(f"{format_date(date, lang, approx=event.get('approx', False))} — {event['label']}{suffix}")
    return tuple(out)


# ──────────────────────────────────────────────────────────────
# Invariants (§7.8)
# ──────────────────────────────────────────────────────────────
OBSTACLE_ROLES = ("marker", "stem", "period-bar", "badge", "whisker", "brace")
TEXT_ON_OWN_GRAPHIC = {"period-label": ("period-bar",), "badge": ("badge", "period-bar")}
LABEL_ROLES = ("event-label", "period-label", "era-label", "note")


def check_layout(layout) -> list:
    """
    Violations des invariants I1–I9 (I8, le déterminisme, se vérifie en comparant
    deux mises en page). Liste vide : la display list peut être livrée.
    """
    found = []
    prims = layout.primitives
    texts = [p for p in prims if isinstance(p, Text)]
    graphics = [p for p in prims if not isinstance(p, Text) and p.role in OBSTACLE_ROLES]

    # I1 — deux textes à moins de 2 px.
    grid = _Grid()
    for i, text in enumerate(texts):
        box = text.bbox
        for key in grid._keys(_inflate(box, TEXT_GAP)):
            for other_box, j in grid.cells.get(key, ()):
                if j != i and _intersects(box, other_box, TEXT_GAP - EPS):
                    pair = tuple(sorted((j, i)))
                    found.append(Violation("I1", f"textes trop proches : {texts[pair[0]].lines[0]!r} / "
                                                 f"{texts[pair[1]].lines[0]!r}",
                                           (texts[pair[0]].ref, texts[pair[1]].ref)))
        grid.add(box, i)
    # Une paire trouvée depuis plusieurs cases n'est signalée qu'une fois.
    found = list({(v.invariant, v.message): v for v in found}.values())

    # I2 / I3 — texte contre marqueur, tige, barre, pastille, moustache.
    ggrid = _Grid()
    for g in graphics:
        ggrid.add(g.bbox, g)
    for text in texts:
        box = text.bbox
        seen = set()
        for key in ggrid._keys(box):
            for gbox, g in ggrid.cells.get(key, ()):
                if id(g) in seen or not _intersects(box, gbox, -EPS):
                    continue
                seen.add(id(g))
                if text.ref and g.ref == text.ref and g.role in TEXT_ON_OWN_GRAPHIC.get(text.role, ()):
                    continue
                if g.role == "stem":
                    found.append(Violation("I3", f"tige {g.ref} à travers {text.lines[0]!r}", (g.ref, text.ref)))
                found.append(Violation("I2", f"{text.role} {text.lines[0]!r} touche {g.role} {g.ref}",
                                       (text.ref, g.ref)))

    # I4 — tout dans le canevas.
    for p in prims:
        x0, y0, x1, y1 = p.bbox
        if x0 < -EPS or y0 < -EPS or x1 > layout.width + EPS or y1 > layout.height + EPS:
            found.append(Violation("I4", f"{p.role} {p.ref} hors du canevas {tuple(round(v, 1) for v in p.bbox)}",
                                   (p.ref,)))

    # I5 — chaque primitive dans sa piste ; pistes disjointes.
    for i, (a0, a1) in enumerate(layout.lanes):
        for b0, b1 in layout.lanes[i + 1:]:
            if a0 < b1 - EPS and b0 < a1 - EPS:
                found.append(Violation("I5", f"pistes superposées ({a0}, {a1}) / ({b0}, {b1})"))
    for p in prims:
        if p.lane is not None and p.lane < len(layout.lanes):
            y0, y1 = layout.lanes[p.lane]
            if p.bbox[1] < y0 - EPS or p.bbox[3] > y1 + EPS:
                found.append(Violation("I5", f"{p.role} {p.ref} déborde de la piste {p.lane}", (p.ref,)))

    # I6 — marqueur d'un évènement non groupé à scale(position) ± 0,5 px.
    if layout.scale is not None:
        markers = {p.ref: p for p in prims if isinstance(p, Marker) and p.role == "marker"}
        for element_id, t in layout.anchors:
            marker = markers.get(element_id)
            if marker is None or abs(marker.cx - layout.scale.x(t)) > 0.5:
                found.append(Violation("I6", f"marqueur de {element_id} hors de sa date", (element_id,)))

    # I7 — chaque élément étiqueté, en note ou dans une grappe listée.
    represented = set()
    for text in texts:
        if text.role in LABEL_ROLES:
            represented.update(refs_of(text.ref))
    for element_id in layout.elements:
        if element_id not in represented:
            found.append(Violation("I7", f"élément {element_id} absent de la frise", (element_id,)))

    # I9 — aucune rupture d'axe dans une période ou une ère.
    if layout.scale is not None:
        for t0, t1, _, _ in layout.scale.breaks:
            for element_id, a, b in layout.spans:
                if a < t1 and t0 < b:
                    found.append(Violation("I9", f"rupture d'axe dans {element_id}", (element_id,)))
    return found
