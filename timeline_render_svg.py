#!/usr/bin/env python3
"""
timeline_render_svg.py — Display list → SVG autonome.

Le SVG est à la fois l'aperçu de l'app et l'export : il n'existe pas de second
chemin de rendu côté navigateur. Il doit donc être autonome (couleurs en
littéraux hexadécimaux, aucune variable CSS de la page) et dessiner le texte aux
largeurs que la mise en page a mesurées :

  * la famille est « Ankigen Inter » (spec D3), déclarée par la page de l'app ou
    incorporée en base64 à l'export ;
  * crénage et ligatures sont désactivés : le navigateur dessine alors à la
    largeur de la table d'avances à ±0,1 px près (spec S7) ;
  * les ancres (`text-anchor`, ligne de base alphabétique) sont celles du raster.

Tout texte est échappé ; toute couleur est revérifiée (#RRGGBB) même si le schéma
l'a déjà fait : une couleur finit dans un attribut, c'est une surface d'injection.

Bibliothèque standard uniquement.
"""

import base64
import logging
import math
import re
from dataclasses import dataclass, replace
from xml.sax.saxutils import escape

from timeline_fonts import FAMILY, default_fonts, weight_key
from timeline_layout import WIDTH_MAX, LayoutOptions, Line, Marker, Path, Rect, Text, _num, check_layout
from timeline_layout import layout as layout_document

log = logging.getLogger(__name__)

HEX = re.compile(r"#[0-9A-Fa-f]{6}")
FONT_STACK = f"'{FAMILY}', Inter, 'Segoe UI', sans-serif"
ATTR = {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"}

# Ordre de dessin : les fonds, puis la grille, puis les barres et les traits, puis
# les marqueurs, et le texte en dernier. Rien ne se chevauche entre texte et
# graphismes ; l'ordre ne règle que les graphismes entre eux.
LAYER = {"lane-bg": 0, "era-band": 1, "gridline": 2, "axis": 3, "tick": 3, "break": 3,
         "period-bar": 4, "whisker": 4, "brace": 4, "stem": 4, "marker": 5, "badge": 5, "legend": 5}


def _layer(prim):
    if isinstance(prim, Text):
        return 6
    return LAYER.get(prim.role, 4)


def _color(value, fallback):
    return value if isinstance(value, str) and HEX.fullmatch(value) else fallback


def _attr(value):
    return escape(str(value), ATTR)


def _points(points):
    return " ".join(f"{_num(x)},{_num(y)}" for x, y in points)


def marker_points(shape, cx, cy, r):
    """Sommets d'un marqueur polygonal ; ils tiennent tous dans le cercle de rayon r (bbox)."""
    if shape == "diamond":
        return [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    if shape == "triangle":
        return [(cx, cy - r), (cx + r * 0.94, cy + r * 0.72), (cx - r * 0.94, cy + r * 0.72)]
    if shape == "hexagon":
        return [(cx + r * math.cos(math.pi / 6 + i * math.pi / 3), cy + r * math.sin(math.pi / 6 + i * math.pi / 3))
                for i in range(6)]
    if shape == "square":
        s = r * 0.86
        return [(cx - s, cy - s), (cx + s, cy - s), (cx + s, cy + s), (cx - s, cy + s)]
    return None


def fade_stops(prim):
    """Arrêts (offset, opacité) du fondu d'une barre : aux deux bouts, ou au bout seulement."""
    if not prim.fade or prim.w <= 0:
        return None
    edge = min(0.45, 24 / prim.w)
    if prim.fade == "end":
        return [(0.0, 1.0), (1 - edge, 1.0), (1.0, 0.15)]
    return [(0.0, 0.3), (edge, 1.0), (1 - edge, 1.0), (1.0, 0.3)]


def _element(prim, theme, defs, prefix, index):
    ink, bg = theme.get("ink", "#000000"), theme.get("bg", "#FFFFFF")
    if isinstance(prim, Text):
        anchor = {"start": "start", "middle": "middle", "end": "end"}.get(prim.anchor, "start")
        spans = []
        for i, line in enumerate(prim.lines):
            dy = "0" if i == 0 else _num(prim.line_height)
            spans.append(f'<tspan x="{_num(prim.x)}" dy="{dy}">{escape(line)}</tspan>')
        return (f'<text x="{_num(prim.x)}" y="{_num(prim.y)}" font-size="{_num(prim.size)}" '
                f'font-weight="{weight_key(prim.weight)}" fill="{_color(prim.fill, ink)}" '
                f'text-anchor="{anchor}">{"".join(spans)}</text>')
    if isinstance(prim, Rect):
        fill = _color(prim.fill, "none")
        stops = fade_stops(prim)
        if stops and fill != "none":
            gid = f"{prefix}-g{index}"
            defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{_num(prim.x)}" '
                        f'y1="0" x2="{_num(prim.x + prim.w)}" y2="0">'
                        + "".join(f'<stop offset="{_num(o)}" stop-color="{fill}" stop-opacity="{_num(a)}"/>'
                                  for o, a in stops) + "</linearGradient>")
            fill = f"url(#{gid})"
        extra = f' opacity="{_num(prim.opacity)}"' if prim.opacity < 1 else ""
        stroke = f' stroke="{_color(prim.stroke, ink)}"' if prim.stroke else ""
        return (f'<rect x="{_num(prim.x)}" y="{_num(prim.y)}" width="{_num(prim.w)}" height="{_num(prim.h)}" '
                f'rx="{_num(prim.rx)}" fill="{fill}"{stroke}{extra}/>')
    if isinstance(prim, Line):
        dash = f' stroke-dasharray="{_attr(prim.dash)}"' if re.fullmatch(r"[0-9. ]+", prim.dash or "") else ""
        return (f'<line x1="{_num(prim.x1)}" y1="{_num(prim.y1)}" x2="{_num(prim.x2)}" y2="{_num(prim.y2)}" '
                f'stroke="{_color(prim.stroke, ink)}" stroke-width="{_num(prim.width)}" '
                f'stroke-linecap="round"{dash}/>')
    if isinstance(prim, Path):
        fill = _color(prim.fill, "none")
        return (f'<path d="{_attr(prim.d)}" fill="{fill}" stroke="{_color(prim.stroke, ink)}" '
                f'stroke-width="{_num(prim.width)}" stroke-linejoin="round" stroke-linecap="round"/>')
    if isinstance(prim, Marker):
        fill = _color(prim.fill, bg)
        stroke = _color(prim.stroke, "none") if prim.stroke else "none"
        style = ""
        if prim.dashed:
            # Date approximative : contour pointillé dans la couleur, fond atténué.
            stroke = fill if fill != bg else stroke
            style = ' fill-opacity="0.45" stroke-dasharray="2 1.5"'
        width = f' stroke-width="{_num(prim.stroke_width)}"' if stroke != "none" else ""
        points = marker_points(prim.shape, prim.cx, prim.cy, prim.r)
        if points is None:
            return (f'<circle cx="{_num(prim.cx)}" cy="{_num(prim.cy)}" r="{_num(prim.r)}" fill="{fill}" '
                    f'stroke="{stroke}"{width}{style}/>')
        return f'<polygon points="{_points(points)}" fill="{fill}" stroke="{stroke}"{width}{style}/>'
    return ""


def _font_face(fonts, weights):
    faces = []
    for weight in sorted(weights):
        data = base64.b64encode(fonts.font_bytes(weight)).decode("ascii")
        faces.append(f"@font-face{{font-family:'{FAMILY}';font-weight:{weight};font-style:normal;"
                     f"src:url(data:font/ttf;base64,{data}) format('truetype');}}")
    return "".join(faces)


def render_svg(layout, *, title="", embed_font=False, fonts=None, id_prefix="tl", background=True) -> str:
    """
    SVG de la display list. `embed_font` incorpore les graisses utilisées (≈ 550 Ko
    de base64 chacune) : le fichier s'affiche alors partout avec la bonne police.
    Inkscape et Illustrator gèrent mal les polices incorporées : leurs
    utilisateurs installent Inter ou exportent sans incorporation.
    """
    theme = layout.theme or {}
    prefix = re.sub(r"[^A-Za-z0-9_-]", "", id_prefix) or "tl"
    width, height = _num(layout.width), _num(layout.height)
    defs, body = [], []
    ordered = sorted(enumerate(layout.primitives), key=lambda item: (_layer(item[1]), item[0]))
    current, group = None, []

    def flush():
        if not group:
            return
        role, ref = current
        css = f"tl-{role}" if role else "tl"
        if ref:
            body.append(f'<g data-ref="{_attr(ref)}" class="{_attr(css)}">{"".join(group)}</g>')
        else:
            body.append(f'<g class="{_attr(css)}">{"".join(group)}</g>')

    for index, prim in ordered:
        key = (prim.role, prim.ref)
        if key != current:
            flush()
            current, group = key, []
        markup = _element(prim, theme, defs, prefix, index)
        if markup:
            group.append(markup)
    flush()

    weights = {weight_key(p.weight) for p in layout.primitives if isinstance(p, Text)}
    faces = _font_face(fonts or default_fonts(), weights) if embed_font else ""
    style = (f"{faces}.{prefix}-root text{{font-family:{FONT_STACK};font-kerning:none;"
             "font-variant-ligatures:none;font-feature-settings:'kern' 0,'liga' 0,'calt' 0;"
             "text-rendering:geometricPrecision;}")
    desc = "\n".join(layout.desc)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="{prefix}-root" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-labelledby="{prefix}-title {prefix}-desc">',
        f'<title id="{prefix}-title">{escape(title)}</title>',
        f'<desc id="{prefix}-desc">{escape(desc)}</desc>',
        f"<style>{style}</style>",
    ]
    if defs:
        parts.append(f"<defs>{''.join(defs)}</defs>")
    if background:
        parts.append(f'<rect width="{width}" height="{height}" fill="{_color(theme.get("bg"), "#FFFFFF")}"/>')
    parts.extend(body)
    parts.append("</svg>")
    return "".join(parts)


@dataclass(frozen=True)
class Rendered:
    svg: str
    width: float
    height: float
    warnings: tuple
    stats: dict
    layout: object


def unsupported_characters(doc, fonts):
    texts = [doc.get("title", ""), doc.get("subtitle", "")]
    texts += [t["label"] for t in doc.get("tracks", [])]
    texts += [e["label"] for kind in ("eras", "periods", "events") for e in doc.get(kind, [])]
    seen = []
    for text in texts:
        for ch in fonts.unsupported(text or ""):
            if ch not in seen:
                seen.append(ch)
    return seen


def render(doc, options=None, *, fonts=None, embed_font=False, id_prefix="tl", background=True) -> Rendered:
    """
    Chaîne complète : mise en page avec la vraie police, vérification des
    invariants, SVG. Une violation n'est jamais livrée en silence : elle est
    journalisée et remonte comme avertissement visible.
    """
    fonts = fonts or default_fonts()
    options = options or LayoutOptions()
    result = layout_document(doc, options, fonts.measure)
    violations = check_layout(result)
    # Ne doit pas arriver (fixtures et fuzz le vérifient) ; si c'est le cas, on
    # repasse par les crans de repli restants avant de livrer quoi que ce soit.
    for fallback in (replace(options, density="compact"),
                     replace(options, width_mode="fixed",
                             width_px=min(WIDTH_MAX, math.ceil(result.width * 1.5)))):
        if not violations:
            break
        log.warning("frise %s : %d violation(s), nouvel essai (%s, %s)", doc.get("title"),
                    len(violations), fallback.density, fallback.width_mode)
        retry = layout_document(doc, fallback, fonts.measure)
        retry_violations = check_layout(retry)
        if len(retry_violations) < len(violations):
            result, violations = retry, retry_violations
    warnings = list(result.warnings)
    if violations:
        for violation in violations[:20]:
            log.error("frise %s : %s %s", doc.get("title"), violation.invariant, violation.message)
        warnings.append({"code": "layout_violation", "params": {"count": len(violations)}})
    missing = unsupported_characters(doc, fonts)
    if missing:
        warnings.append({"code": "label_unsupported_chars", "params": {"chars": " ".join(missing)}})
    svg = render_svg(result, title=doc.get("title", ""), embed_font=embed_font, fonts=fonts,
                     id_prefix=id_prefix, background=background)
    return Rendered(svg=svg, width=result.width, height=result.height, warnings=tuple(warnings),
                    stats=result.stats, layout=result)
