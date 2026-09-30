#!/usr/bin/env python3
"""
timeline_fonts.py — La police des frises, et la mesure de son texte.

« Zéro chevauchement » ne vaut que si la mesure est celle du dessin. Les deux
moteurs de rendu utilisent donc la même police (Inter 4.1, embarquée dans
static/fonts/) et les mêmes avances :

  * Pillow est forcé en moteur BASIC : sans crénage ni ligatures, la largeur d'un
    texte est exactement la somme des avances de ses caractères. Un Pillow
    compilé avec raqm changerait sinon les mesures sans le dire ;
  * les avances sont lues une fois, à 1000 px, puis mises à l'échelle : c'est
    exact (le hinting arrondit les avances aux petites tailles, pas à 1000 px)
    et environ 80 fois plus rapide que `getlength` (spec, S3) ;
  * le SVG désactive crénage et ligatures pour dessiner à ces mêmes largeurs (S7) ;
  * un caractère absent de la police (idéogrammes, emoji) est compté pour 1 em,
    la borne haute : le navigateur le dessinera avec une autre police, Pillow
    avec le glyphe .notdef, et aucun des deux ne débordera.

La table `cmap` est lue à la main (formats 4 et 12) : la bibliothèque standard
suffit, sans fontTools.
"""

import struct
from bisect import bisect_right
from pathlib import Path

FONT_DIR = Path(__file__).parent / "static" / "fonts"
FONT_FILES = {400: "Inter-Regular.ttf", 600: "Inter-SemiBold.ttf"}
# Nom de famille propre à l'app (spec D3) : l'interface charge une autre version
# d'Inter depuis Google Fonts, qui ne doit jamais servir à dessiner une frise.
FAMILY = "Ankigen Inter"
REF_SIZE = 1000
MISSING_ADVANCE_EM = 1.0
# La mise en page mesure les mêmes libellés des dizaines de fois (variantes de
# coupure, candidats de placement) : leurs largeurs sont gardées, dans une limite.
WIDTH_CACHE_MAX = 50_000


def weight_key(weight) -> int:
    """Deux fichiers seulement : 400, et 600 pour tout ce qui est gras."""
    return 600 if weight >= 500 else 400


# ──────────────────────────────────────────────────────────────
# Table cmap
# ──────────────────────────────────────────────────────────────
def _tables(data):
    if len(data) < 12:
        raise ValueError("pas une police TrueType/OpenType")
    version, count = struct.unpack(">IH", data[:6])
    if version not in (0x00010000, 0x4F54544F) or 12 + 16 * count > len(data):
        raise ValueError("pas une police TrueType/OpenType")
    tables = {}
    for i in range(count):
        tag, _, offset, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        tables[tag.decode("latin-1")] = (offset, length)
    return tables


def _format4(data, base):
    seg_count = struct.unpack(">H", data[base + 6:base + 8])[0] // 2
    ends = struct.unpack(f">{seg_count}H", data[base + 14:base + 14 + 2 * seg_count])
    starts_at = base + 16 + 2 * seg_count
    starts = struct.unpack(f">{seg_count}H", data[starts_at:starts_at + 2 * seg_count])
    deltas_at = starts_at + 2 * seg_count
    deltas = struct.unpack(f">{seg_count}h", data[deltas_at:deltas_at + 2 * seg_count])
    offsets_at = deltas_at + 2 * seg_count
    offsets = struct.unpack(f">{seg_count}H", data[offsets_at:offsets_at + 2 * seg_count])
    covered = []
    for i, (start, end) in enumerate(zip(starts, ends)):
        if start == 0xFFFF:
            continue
        for code in range(start, end + 1):
            if offsets[i] == 0:
                glyph = (code + deltas[i]) & 0xFFFF
            else:
                at = offsets_at + 2 * i + offsets[i] + 2 * (code - start)
                glyph = struct.unpack(">H", data[at:at + 2])[0]
                glyph = (glyph + deltas[i]) & 0xFFFF if glyph else 0
            if glyph:
                covered.append(code)
    return _ranges(covered)


def _format12(data, base):
    groups = struct.unpack(">I", data[base + 12:base + 16])[0]
    out = []
    for i in range(groups):
        start, end, glyph = struct.unpack(">III", data[base + 16 + 12 * i:base + 28 + 12 * i])
        if glyph or start != end:
            out.append((start, end))
    return _merge(out)


def _ranges(codes):
    out = []
    for code in sorted(codes):
        if out and code == out[-1][1] + 1:
            out[-1] = (out[-1][0], code)
        else:
            out.append((code, code))
    return out


def _merge(ranges):
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(end, out[-1][1]))
        else:
            out.append((start, end))
    return out


def read_cmap(data: bytes) -> list:
    """Plages de points de code couverts par la police : [(début, fin), …], triées."""
    tables = _tables(data)
    if "cmap" not in tables:
        raise ValueError("table cmap absente")
    cmap = tables["cmap"][0]
    count = struct.unpack(">H", data[cmap + 2:cmap + 4])[0]
    subtables = {}
    for i in range(count):
        platform, encoding, offset = struct.unpack(">HHI", data[cmap + 4 + 8 * i:cmap + 12 + 8 * i])
        fmt = struct.unpack(">H", data[cmap + offset:cmap + offset + 2])[0]
        subtables[(platform, encoding, fmt)] = cmap + offset
    # Le format 12 couvre tout Unicode ; le format 4 seulement le plan de base.
    for key, parse in (((3, 10, 12), _format12), ((0, 4, 12), _format12), ((0, 6, 12), _format12),
                       ((3, 1, 4), _format4), ((0, 3, 4), _format4)):
        if key in subtables:
            return parse(data, subtables[key])
    raise ValueError("aucune sous-table cmap Unicode lisible")


# ──────────────────────────────────────────────────────────────
# Mesure
# ──────────────────────────────────────────────────────────────
class FontSet:
    """Les deux graisses d'Inter, leurs avances et leur couverture. Chargement paresseux."""

    def __init__(self, font_dir=FONT_DIR):
        self.font_dir = Path(font_dir)
        self._fonts = {}
        self._advances = {400: {}, 600: {}}
        self._widths = {400: {}, 600: {}}
        self._coverage = None

    def font(self, weight):
        from PIL import ImageFont

        key = weight_key(weight)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(
                str(self.font_dir / FONT_FILES[key]), REF_SIZE, layout_engine=ImageFont.Layout.BASIC)
        return self._fonts[key]

    def font_bytes(self, weight) -> bytes:
        return (self.font_dir / FONT_FILES[weight_key(weight)]).read_bytes()

    def covers(self, ch) -> bool:
        if self._coverage is None:
            ranges = read_cmap((self.font_dir / FONT_FILES[400]).read_bytes())
            self._coverage = ([a for a, _ in ranges], [b for _, b in ranges])
        starts, ends = self._coverage
        code = ord(ch)
        i = bisect_right(starts, code) - 1
        return i >= 0 and code <= ends[i]

    def unsupported(self, text) -> list:
        """Caractères que la police ne sait pas dessiner, dans l'ordre, sans doublon."""
        seen = []
        for ch in text:
            if not ch.isspace() and not self.covers(ch) and ch not in seen:
                seen.append(ch)
        return seen

    def _advance(self, ch, key):
        table = self._advances[key]
        if ch not in table:
            if self.covers(ch):
                table[ch] = self.font(key).getlength(ch) / REF_SIZE
            else:
                table[ch] = MISSING_ADVANCE_EM
        return table[ch]

    def advances(self, text, size, weight) -> list:
        """Avance de chaque caractère, en px : le raster place les glyphes un à un (spec D4)."""
        key = weight_key(weight)
        return [self._advance(ch, key) * size for ch in text]

    def measure(self, text, size, weight) -> float:
        """Largeur en px : la fonction que la mise en page reçoit par injection."""
        key = weight_key(weight)
        cache = self._widths[key]
        width = cache.get(text)
        if width is None:
            width = sum(self._advance(ch, key) for ch in text)
            if len(cache) >= WIDTH_CACHE_MAX:
                cache.clear()
            cache[text] = width
        return width * size


_DEFAULT = None


def default_fonts() -> FontSet:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = FontSet()
    return _DEFAULT
