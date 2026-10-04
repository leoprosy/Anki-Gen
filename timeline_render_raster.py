#!/usr/bin/env python3
"""
timeline_render_raster.py — Display list → images Pillow : PNG, JPEG, WebP, PDF.

Il consomme la MÊME display list que le SVG. Deux règles tiennent la promesse
« aucun chevauchement » jusque dans les pixels :

  * le texte est dessiné glyphe par glyphe, chaque glyphe à sa position dans la
    mise en page (somme des avances de timeline_fonts). Dessiner une chaîne
    d'un bloc laisserait le hinting l'élargir jusqu'à 8 px à 13 px (spec S5, D4) ;
  * l'anticrénelage vient d'un suréchantillonnage (×2 par défaut) suivi d'une
    réduction LANCZOS.

Le tampon est en RGB dès que le fond est opaque (JPEG, PDF, PNG ordinaire) : un
tiers de mémoire en moins (spec E4). Le RGBA est réservé au PNG transparent ; les
formes y sont composées par masque (alpha_composite), sinon leurs bords
anticrénelés garderaient la couleur du fond absent.

La surface suréchantillonnée est plafonnée à 60 Mpx : au-delà, on réduit d'abord
le suréchantillonnage, puis l'échelle, et le rapport le dit. Les capacités de
Pillow utilisées (FreeType, encodeurs PNG, JPEG, WebP, PDF) sont garanties par
le runtime et vérifiées par runtime_probe : pas de détection à l'appel.
"""

import io
import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from timeline_fonts import FONT_FILES, default_fonts, weight_key
from timeline_layout import Line, Marker, Path, Rect, Text
from timeline_render_svg import LAYER, fade_stops, marker_points

FORMATS = ("png", "jpeg", "webp", "pdf")
MIME_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp", "pdf": "application/pdf"}
EXTENSIONS = {"png": "png", "jpeg": "jpg", "webp": "webp", "pdf": "pdf"}
MAX_PIXELS = 60_000_000             # surface suréchantillonnée, tous formats
MAX_SIDE = {"jpeg": 65_535, "webp": 16_383}
CSS_DPI = 96                        # 1 px de la mise en page = 1/96 de pouce
PDF_DPI = 300
PAGE_SIZES_MM = {"a4": (210.0, 297.0), "a3": (297.0, 420.0)}   # portrait
SMALL_PRINT = 0.5                   # en deçà, le texte imprimé devient trop petit
# Avertissements d'export ; chacun a sa clé i18n `timeline.export.<code>` (test).
WARNING_CODES = ("scale_reduced_side", "scale_reduced_pixels", "pdf_small_print", "pdf_dpi_reduced")

# Poids moyen d'un pixel encodé, mesuré sur les fixtures (octets par pixel) : sert
# à annoncer un ordre de grandeur dans la modale d'export, pas à le garantir.
BYTES_PER_PIXEL = {"png": 0.07, "jpeg": 0.065, "webp": 0.025, "webp_lossless": 0.033, "pdf": 0.07}

APPROX_OPACITY = 0.45               # remplissage d'un marqueur approximatif (comme le SVG)
APPROX_DASH = (2.0, 1.5)


def _rgb(color, fallback=(0, 0, 0)):
    if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
        return fallback
    value = int(color[1:], 16)
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


# ──────────────────────────────────────────────────────────────
# Dessin
# ──────────────────────────────────────────────────────────────
class _Painter:
    def __init__(self, layout, k, fonts, transparent=False):
        self.k = k
        self.fonts = fonts
        theme = layout.theme or {}
        self.bg = theme.get("bg", "#FFFFFF")
        self.ink = theme.get("ink", "#000000")
        self.transparent = transparent
        size = (max(1, round(layout.width * k)), max(1, round(layout.height * k)))
        if transparent:
            self.image = Image.new("RGBA", size, (0, 0, 0, 0))
        else:
            self.image = Image.new("RGB", size, _rgb(self.bg))
        self.draw = ImageDraw.Draw(self.image)
        self._fonts = {}

    def font(self, weight, px):
        key = (weight_key(weight), round(px, 2))
        if key not in self._fonts:
            path = self.fonts.font_dir / FONT_FILES[key[0]]
            self._fonts[key] = ImageFont.truetype(str(path), key[1], layout_engine=ImageFont.Layout.BASIC)
        return self._fonts[key]

    # ── Composition ──────────────────────────────────────────────
    def paint(self, box, color, draw, alpha=1.0, ramp=None):
        """
        Dessine une forme : `draw(ImageDraw, ox, oy, fill)` la trace décalée de (ox, oy).

        Opaque sur fond opaque : directement dans l'image. Sinon, dans un masque
        limité à la boîte de la forme, pondéré par `alpha` et par `ramp` (opacité
        par colonne, pour les fondus), puis composé.
        """
        if alpha >= 1 and ramp is None and not self.transparent:
            draw(self.draw, 0.0, 0.0, _rgb(color))
            return
        width, height = self.image.size
        x0, y0 = max(0, math.floor(box[0]) - 2), max(0, math.floor(box[1]) - 2)
        x1, y1 = min(width, math.ceil(box[2]) + 2), min(height, math.ceil(box[3]) + 2)
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        draw(ImageDraw.Draw(mask), float(x0), float(y0), 255)
        if ramp is not None:
            columns = Image.new("L", (x1 - x0, 1))
            columns.putdata([round(255 * ramp(x0 + i)) for i in range(x1 - x0)])
            mask = Image.composite(mask, Image.new("L", mask.size, 0),
                                   columns.resize(mask.size, Image.NEAREST))
        if alpha < 1:
            mask = mask.point(lambda v: round(v * alpha))
        self._composite(mask, (x0, y0), color)

    def _composite(self, mask, origin, color):
        if self.transparent:
            x0, y0 = origin
            region = self.image.crop((x0, y0, x0 + mask.size[0], y0 + mask.size[1]))
            layer = Image.new("RGBA", mask.size, _rgb(color) + (0,))
            layer.putalpha(mask)
            self.image.paste(Image.alpha_composite(region, layer), origin)
        else:
            self.image.paste(Image.new("RGB", mask.size, _rgb(color)), origin, mask)

    # ── Primitives ───────────────────────────────────────────────
    def rect(self, p):
        k = self.k
        box = [p.x * k, p.y * k, (p.x + p.w) * k, (p.y + p.h) * k]
        radius = max(0.0, min(p.rx * k, (box[2] - box[0]) / 2, (box[3] - box[1]) / 2))
        if p.fill:
            stops = fade_stops(p)
            ramp = None
            if stops:
                span = max(1e-9, box[2] - box[0])
                ramp = lambda x: _interpolate(stops, min(1.0, max(0.0, (x + 0.5 - box[0]) / span)))  # noqa: E731

            def shape(draw, ox, oy, fill):
                draw.rounded_rectangle([box[0] - ox, box[1] - oy, box[2] - ox, box[3] - oy],
                                       radius=radius, fill=fill)
            self.paint(box, p.fill, shape, alpha=p.opacity, ramp=ramp)
        if p.stroke:
            width = max(1, round(k))

            def outline(draw, ox, oy, fill):
                draw.rounded_rectangle([box[0] - ox, box[1] - oy, box[2] - ox, box[3] - oy],
                                       radius=radius, outline=fill, width=width)
            self.paint(box, p.stroke, outline)

    def line(self, p):
        k = self.k
        width = max(1, round(p.width * k))
        color = p.stroke if _rgb(p.stroke, None) else self.ink
        start, end = (p.x1 * k, p.y1 * k), (p.x2 * k, p.y2 * k)
        if p.dash:
            parts = [float(v) * k for v in (p.dash.split() + ["4", "4"])[:2]]
            segments = _dashes([start, end], parts[0], parts[1])
        else:
            segments = [(start, end)]
        box = _bounds([start, end], width)

        def draw_segments(draw, ox, oy, fill):
            for a, b in segments:
                draw.line([(a[0] - ox, a[1] - oy), (b[0] - ox, b[1] - oy)], fill=fill, width=width)
        self.paint(box, color, draw_segments)

    def path(self, p):
        k = self.k
        points = [(x * k, y * k) for c, x, y in p.points if c != "Z"]
        width = max(1, round(p.width * k))
        color = p.stroke if _rgb(p.stroke, None) else self.ink

        def draw_path(draw, ox, oy, fill):
            draw.line([(x - ox, y - oy) for x, y in points], fill=fill, width=width, joint="curve")
        self.paint(_bounds(points, width), color, draw_path)

    def marker(self, p):
        k = self.k
        fill = p.fill or self.bg
        box = _bounds([((p.cx - p.r) * k, (p.cy - p.r) * k), ((p.cx + p.r) * k, (p.cy + p.r) * k)],
                      p.stroke_width * k + 2)
        if p.dashed:
            # Date approximative : fond atténué, contour pointillé dans la couleur (comme le SVG).
            self.paint(box, fill, self._shape(p.shape, p.cx, p.cy, p.r), alpha=APPROX_OPACITY)
            outline = _outline(p.shape, p.cx * k, p.cy * k, p.r * k)
            width = max(1, round(p.stroke_width * k))
            segments = _dashes(outline, APPROX_DASH[0] * k, APPROX_DASH[1] * k)

            def dashed(draw, ox, oy, color):
                for a, b in segments:
                    draw.line([(a[0] - ox, a[1] - oy), (b[0] - ox, b[1] - oy)], fill=color, width=width)
            self.paint(box, fill, dashed)
            return
        half = p.stroke_width / 2 if p.stroke else 0
        if p.stroke:
            self.paint(box, p.stroke, self._shape(p.shape, p.cx, p.cy, p.r + half))
        self.paint(box, fill, self._shape(p.shape, p.cx, p.cy, p.r - half))

    def _shape(self, shape, cx, cy, r):
        k = self.k

        def draw_shape(draw, ox, oy, fill):
            if r <= 0:
                return
            points = marker_points(shape, cx * k - ox, cy * k - oy, r * k)
            if points is None:
                draw.ellipse([(cx - r) * k - ox, (cy - r) * k - oy, (cx + r) * k - ox, (cy + r) * k - oy],
                             fill=fill)
            else:
                draw.polygon(points, fill=fill)
        return draw_shape

    def text(self, p):
        k = self.k
        font = self.font(p.weight, p.size * k)
        color = p.fill if _rgb(p.fill, None) else self.ink
        glyphs = []
        for i, line in enumerate(p.lines):
            width = p.widths[i] if i < len(p.widths) else 0
            x = p.x - width / 2 if p.anchor == "middle" else p.x - width if p.anchor == "end" else p.x
            y = (p.y + i * p.line_height) * k
            cursor = x * k
            for ch, advance in zip(line, self.fonts.advances(line, p.size, p.weight)):
                if not ch.isspace():
                    glyphs.append((cursor, y, ch))
                cursor += advance * k
        x0, y0, x1, y1 = p.bbox
        box = (x0 * k - p.size * k, y0 * k - p.size * k, x1 * k + p.size * k, y1 * k + p.size * k)

        def draw_text(draw, ox, oy, fill):
            for x, y, ch in glyphs:
                draw.text((x - ox, y - oy), ch, font=font, fill=fill, anchor="ls")
        self.paint(box, color, draw_text)


def _bounds(points, pad):
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _outline(shape, cx, cy, r):
    """Contour fermé d'un marqueur (un cercle devient un polygone fin, pour le pointillé)."""
    points = marker_points(shape, cx, cy, r)
    if points is None:
        steps = max(24, int(2 * math.pi * r / 2))
        points = [(cx + r * math.cos(2 * math.pi * i / steps), cy + r * math.sin(2 * math.pi * i / steps))
                  for i in range(steps)]
    return points + [points[0]]


def _dashes(points, on, off):
    """Segments « trait » d'une ligne brisée pointillée (les pointillés sont dessinés à la main)."""
    segments, drawing, left = [], True, on
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        t = 0.0
        while t < length - 1e-9:
            step = min(left, length - t)
            if drawing:
                segments.append((_lerp(a, b, t / length), _lerp(a, b, (t + step) / length)))
            t += step
            left -= step
            if left <= 1e-9:
                drawing = not drawing
                left = on if drawing else off
    return segments


def _interpolate(stops, t):
    for (o0, a0), (o1, a1) in zip(stops, stops[1:]):
        if o0 <= t <= o1:
            return a0 + (a1 - a0) * ((t - o0) / (o1 - o0) if o1 > o0 else 0)
    return stops[-1][1]


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def render_image(layout, *, scale=1.0, supersample=2, fonts=None, transparent=False):
    """Image de la mise en page à `scale` fois sa taille en px CSS : RGB, ou RGBA si transparente."""
    fonts = fonts or default_fonts()
    painter = _Painter(layout, scale * supersample, fonts, transparent=transparent)
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
    """PNG opaque : la galerie de revue visuelle."""
    buffer = io.BytesIO()
    render_image(layout, scale=scale, supersample=supersample, fonts=fonts).save(buffer, format="PNG")
    return buffer.getvalue()


# ──────────────────────────────────────────────────────────────
# Plans : dimensions finales, plafonds, avertissements
# ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RasterPlan:
    scale: float            # px de sortie par px de la mise en page
    supersample: int
    width: int
    height: int
    warnings: tuple = ()


def plan_raster(width, height, *, scale=2.0, supersample=2, fmt="png", max_pixels=MAX_PIXELS) -> RasterPlan:
    """
    Échelle et suréchantillonnage tenables. On réduit d'abord le suréchantillonnage
    (l'image garde ses dimensions), puis l'échelle, et on le dit.
    """
    requested = scale
    warnings = []
    side = MAX_SIDE.get(fmt)
    by_side = side / max(width, height) if side else math.inf
    by_pixels = math.sqrt(max_pixels / (width * height))
    if min(by_side, by_pixels) < scale:
        scale = min(by_side, by_pixels)
        params = {"requested": _percent(requested), "scale": _percent(scale)}
        if by_side <= by_pixels:
            warnings.append({"code": "scale_reduced_side", "params": dict(params, format=fmt.upper(), max=side)})
        else:
            warnings.append({"code": "scale_reduced_pixels", "params": dict(params, max=max_pixels // 1_000_000)})
    while supersample > 1 and (width * scale * supersample) * (height * scale * supersample) > max_pixels:
        supersample -= 1
    return RasterPlan(scale=scale, supersample=supersample, width=max(1, round(width * scale)),
                      height=max(1, round(height * scale)), warnings=tuple(warnings))


@dataclass(frozen=True)
class PdfPlan:
    page_mm: tuple          # (largeur, hauteur) de la page
    dpi: float
    fit: float              # échelle du contenu par rapport à sa taille naturelle
    content_px: tuple       # contenu, en px de sortie
    page_px: tuple
    offset_px: tuple        # position du contenu dans la page (centré)
    supersample: int
    warnings: tuple = ()


def plan_pdf(width, height, *, page="fit", orientation="landscape", margin_mm=10.0, dpi=PDF_DPI,
             max_pixels=MAX_PIXELS) -> PdfPlan:
    """
    Page ajustée au contenu, A4 ou A3 (portrait ou paysage), avec marges. Le raster
    est à 300 dpi ; une page trop grande pour le plafond le fait baisser, et le
    rapport le dit. Sous 50 % de la taille naturelle, le texte imprimé devient trop
    petit : le rapport propose l'A3.
    """
    mm = 25.4 / CSS_DPI
    content_mm = (width * mm, height * mm)
    warnings = []
    if page in PAGE_SIZES_MM:
        short, long = PAGE_SIZES_MM[page]
        page_mm = (long, short) if orientation == "landscape" else (short, long)
        available = (page_mm[0] - 2 * margin_mm, page_mm[1] - 2 * margin_mm)
        fit = min(1.0, available[0] / content_mm[0], available[1] / content_mm[1])
        if fit < SMALL_PRINT:
            warnings.append({"code": "pdf_small_print", "params": {"percent": _percent(fit)}})
    else:
        fit = 1.0
        page_mm = (content_mm[0] + 2 * margin_mm, content_mm[1] + 2 * margin_mm)
    page_px = (page_mm[0] / 25.4 * dpi, page_mm[1] / 25.4 * dpi)
    if page_px[0] * page_px[1] > max_pixels:
        dpi = dpi * math.sqrt(max_pixels / (page_px[0] * page_px[1]))
        warnings.append({"code": "pdf_dpi_reduced", "params": {"dpi": round(dpi)}})
    scale = fit * dpi / CSS_DPI
    content_px = (max(1, round(width * scale)), max(1, round(height * scale)))
    page_px = (max(1, round(page_mm[0] / 25.4 * dpi)), max(1, round(page_mm[1] / 25.4 * dpi)))
    offset = ((page_px[0] - content_px[0]) // 2, (page_px[1] - content_px[1]) // 2)
    # À 300 dpi, le suréchantillonnage n'apporte rien ; sous 200 dpi, il lisse le texte.
    supersample = 1 if dpi >= 200 else 2
    if content_px[0] * content_px[1] * supersample ** 2 > max_pixels:
        supersample = 1
    return PdfPlan(page_mm=tuple(round(v, 1) for v in page_mm), dpi=dpi, fit=fit, content_px=content_px,
                   page_px=page_px, offset_px=offset, supersample=supersample, warnings=tuple(warnings))


def _percent(value):
    return round(value * 100)


# ──────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Exported:
    data: bytes
    mimetype: str
    extension: str
    width: int
    height: int
    warnings: tuple = ()
    info: dict = field(default_factory=dict)


def export(layout, fmt, *, scale=2.0, transparent=False, quality=90, lossless=False, page="fit",
           orientation="landscape", margin_mm=10.0, title="", fonts=None) -> Exported:
    """Mise en page → fichier. `transparent` ne vaut que pour le PNG (le JPEG n'a pas d'alpha)."""
    if fmt not in FORMATS:
        raise ValueError(f"format d'export inconnu : {fmt!r}")
    fonts = fonts or default_fonts()
    buffer = io.BytesIO()
    if fmt == "pdf":
        plan = plan_pdf(layout.width, layout.height, page=page, orientation=orientation, margin_mm=margin_mm)
        content = render_image(layout, scale=plan.content_px[0] / layout.width, supersample=plan.supersample,
                               fonts=fonts)
        content = content.resize(plan.content_px, Image.LANCZOS) if content.size != plan.content_px else content
        sheet = Image.new("RGB", plan.page_px, _rgb((layout.theme or {}).get("bg", "#FFFFFF")))
        sheet.paste(content, plan.offset_px)
        # Pillow encode la page en JPEG (qualité 75, chrominance sous-échantillonnée par
        # défaut) : pour l'impression, qualité 95 et chrominance entière, le texte coloré reste net.
        sheet.save(buffer, format="PDF", resolution=plan.dpi, title=title or "", author="Ankigen",
                   creator="Ankigen", quality=95, subsampling=0)
        info = {"page_mm": plan.page_mm, "dpi": round(plan.dpi), "fit": _percent(plan.fit)}
        return Exported(buffer.getvalue(), MIME_TYPES[fmt], EXTENSIONS[fmt], plan.page_px[0], plan.page_px[1],
                        plan.warnings, info)
    plan = plan_raster(layout.width, layout.height, scale=scale, fmt=fmt)
    image = render_image(layout, scale=plan.scale, supersample=plan.supersample, fonts=fonts,
                         transparent=transparent and fmt == "png")
    if fmt == "png":
        # `optimize` essaie tous les filtres : trop lent sur une grande frise, pour peu de gain.
        image.save(buffer, format="PNG", optimize=image.size[0] * image.size[1] <= 4_000_000)
    elif fmt == "jpeg":
        # Pas de sous-échantillonnage de la chrominance : un texte fin et coloré reste net.
        image.save(buffer, format="JPEG", quality=quality, optimize=True, subsampling=0)
    else:
        image.save(buffer, format="WEBP", quality=quality, lossless=lossless, method=4)
    info = {"scale": plan.scale, "supersample": plan.supersample}
    return Exported(buffer.getvalue(), MIME_TYPES[fmt], EXTENSIONS[fmt], plan.width, plan.height,
                    plan.warnings, info)


def estimate(layout, fmt, *, scale=2.0, lossless=False, page="fit", orientation="landscape",
             margin_mm=10.0) -> dict:
    """Dimensions finales et poids approximatif, sans rien dessiner (modale d'export)."""
    if fmt == "pdf":
        plan = plan_pdf(layout.width, layout.height, page=page, orientation=orientation, margin_mm=margin_mm)
        pixels = plan.page_px[0] * plan.page_px[1]
        return {"width": plan.page_px[0], "height": plan.page_px[1], "page_mm": plan.page_mm,
                "dpi": round(plan.dpi), "fit": _percent(plan.fit),
                "bytes": round(pixels * BYTES_PER_PIXEL["pdf"]), "warnings": list(plan.warnings)}
    plan = plan_raster(layout.width, layout.height, scale=scale, fmt=fmt)
    key = "webp_lossless" if fmt == "webp" and lossless else fmt
    return {"width": plan.width, "height": plan.height, "scale": plan.scale,
            "bytes": round(plan.width * plan.height * BYTES_PER_PIXEL[key]), "warnings": list(plan.warnings)}
