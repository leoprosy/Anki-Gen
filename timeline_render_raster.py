#!/usr/bin/env python3
"""
timeline_render_raster.py — Display list → image Pillow (PNG pour l'instant).

Il consomme la MÊME display list que le SVG. Deux règles tiennent la promesse
« aucun chevauchement » jusque dans les pixels :

  * le texte est dessiné glyphe par glyphe, chaque glyphe à sa position dans la
    mise en page (somme des avances de timeline_fonts). Dessiner une chaîne
    d'un bloc laisserait le hinting l'élargir jusqu'à 8 px à 13 px (spec S5, D4) ;
  * l'anticrénelage vient d'un suréchantillonnage (×2 par défaut) suivi d'une
    réduction LANCZOS.

Phase 2 : le strict nécessaire pour la galerie de revue visuelle. La phase 5
ajoute JPEG, WebP, PDF, le plafond de surface et les options d'export.
"""

import io
import math

from PIL import Image, ImageChops, ImageDraw, ImageFont

from timeline_fonts import FONT_FILES, default_fonts, weight_key
from timeline_layout import Line, Marker, Path, Rect, Text, mix
from timeline_render_svg import LAYER, fade_stops, marker_points


def _rgb(color, fallback=(0, 0, 0)):
    if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
        return fallback
    value = int(color[1:], 16)
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


class _Painter:
    def __init__(self, layout, k, fonts):
        self.k = k
        self.fonts = fonts
        self.theme = layout.theme or {}
        self.bg = self.theme.get("bg", "#FFFFFF")
        self.ink = self.theme.get("ink", "#000000")
        size = (max(1, round(layout.width * k)), max(1, round(layout.height * k)))
        self.image = Image.new("RGBA", size, _rgb(self.bg) + (255,))
        self.draw = ImageDraw.Draw(self.image)
        self._fonts = {}

    def font(self, weight, px):
        key = (weight_key(weight), round(px, 2))
        if key not in self._fonts:
            path = self.fonts.font_dir / FONT_FILES[key[0]]
            self._fonts[key] = ImageFont.truetype(str(path), key[1], layout_engine=ImageFont.Layout.BASIC)
        return self._fonts[key]

    # ── Primitives ───────────────────────────────────────────────
    def rect(self, p):
        if not p.fill:
            return
        k = self.k
        box = [p.x * k, p.y * k, (p.x + p.w) * k, (p.y + p.h) * k]
        radius = min(p.rx * k, (box[2] - box[0]) / 2, (box[3] - box[1]) / 2)
        stops = fade_stops(p)
        if not stops and p.opacity >= 1:
            self.draw.rounded_rectangle(box, radius=radius, fill=_rgb(p.fill))
            return
        # Opacité ou fondu : masque de la forme × rampe horizontale d'opacité.
        stops = stops or [(0.0, 1.0), (1.0, 1.0)]
        mask = Image.new("L", self.image.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
        width = max(1, int(math.ceil(box[2] - box[0])))
        ramp = Image.new("L", (width, 1))
        for i in range(width):
            t = i / max(1, width - 1)
            ramp.putpixel((i, 0), round(255 * p.opacity * _interpolate(stops, t)))
        alpha = Image.new("L", self.image.size, 0)
        alpha.paste(ramp.resize((width, self.image.size[1])), (int(box[0]), 0))
        mask = ImageChops.multiply(mask, alpha)
        layer = Image.new("RGBA", self.image.size, _rgb(p.fill) + (255,))
        self.image.paste(layer, (0, 0), mask)

    def line(self, p):
        k = self.k
        width = max(1, round(p.width * k))
        color = _rgb(p.stroke, _rgb(self.ink))
        start, end = (p.x1 * k, p.y1 * k), (p.x2 * k, p.y2 * k)
        if p.dash:
            on, off = [float(v) * k for v in (p.dash.split() + ["4", "4"])[:2]]
            length = math.dist(start, end)
            t = 0.0
            while t < length:
                a = t / length
                b = min(1.0, (t + on) / length)
                self.draw.line([_lerp(start, end, a), _lerp(start, end, b)], fill=color, width=width)
                t += on + off
            return
        self.draw.line([start, end], fill=color, width=width)

    def path(self, p):
        k = self.k
        points = [(x * k, y * k) for c, x, y in p.points if c != "Z"]
        self.draw.line(points, fill=_rgb(p.stroke, _rgb(self.ink)), width=max(1, round(p.width * k)),
                       joint="curve")

    def marker(self, p):
        fill = p.fill or self.bg
        if p.dashed:
            # Contour de la couleur, fond atténué (le pointillé fin arrivera en phase 5).
            ring, inner = fill, mix(fill, self.bg, 0.55)
        else:
            ring, inner = p.stroke, fill
        half = (p.stroke_width / 2) if ring else 0
        if ring:
            self._shape(p.shape, p.cx, p.cy, p.r + half, ring)
        self._shape(p.shape, p.cx, p.cy, p.r - half, inner)

    def _shape(self, shape, cx, cy, r, color):
        if r <= 0:
            return
        k = self.k
        points = marker_points(shape, cx * k, cy * k, r * k)
        if points is None:
            self.draw.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=_rgb(color))
        else:
            self.draw.polygon(points, fill=_rgb(color))

    def text(self, p):
        k = self.k
        font = self.font(p.weight, p.size * k)
        color = _rgb(p.fill, _rgb(self.ink))
        for i, line in enumerate(p.lines):
            width = p.widths[i] if i < len(p.widths) else 0
            x = p.x - width / 2 if p.anchor == "middle" else p.x - width if p.anchor == "end" else p.x
            y = (p.y + i * p.line_height) * k
            cursor = x * k
            for ch, advance in zip(line, self.fonts.advances(line, p.size, p.weight)):
                if not ch.isspace():
                    self.draw.text((cursor, y), ch, font=font, fill=color, anchor="ls")
                cursor += advance * k


def _interpolate(stops, t):
    for (o0, a0), (o1, a1) in zip(stops, stops[1:]):
        if o0 <= t <= o1:
            return a0 + (a1 - a0) * ((t - o0) / (o1 - o0) if o1 > o0 else 0)
    return stops[-1][1]


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def render_image(layout, *, scale=1.0, supersample=2, fonts=None):
    """Image RGBA de la mise en page, à `scale` fois sa taille en px CSS."""
    fonts = fonts or default_fonts()
    painter = _Painter(layout, scale * supersample, fonts)
    ordered = sorted(enumerate(layout.primitives),
                     key=lambda item: (6 if isinstance(item[1], Text) else LAYER.get(item[1].role, 4), item[0]))
    for _, prim in ordered:
        if isinstance(prim, Rect):
            painter.rect(prim)
        elif isinstance(prim, Line):
            painter.line(prim)
        elif isinstance(prim, Path):
            painter.path(prim)
        elif isinstance(prim, Marker):
            painter.marker(prim)
        elif isinstance(prim, Text):
            painter.text(prim)
    image = painter.image
    if supersample != 1:
        size = (max(1, round(layout.width * scale)), max(1, round(layout.height * scale)))
        image = image.resize(size, Image.LANCZOS)
    return image


def render_png(layout, *, scale=1.0, supersample=2, fonts=None) -> bytes:
    buffer = io.BytesIO()
    render_image(layout, scale=scale, supersample=supersample, fonts=fonts).save(buffer, format="PNG",
                                                                                 optimize=True)
    return buffer.getvalue()
