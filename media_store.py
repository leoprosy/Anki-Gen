#!/usr/bin/env python3
"""
media_store.py — Stockage des images extraites d'un .docx.

Responsabilités :
  * écrire chaque image dans media/<project_id>/
  * dédoublonner par SHA-1 (une image répétée dans le cours = un seul fichier)
  * normaliser les formats qu'Anki ne sait pas afficher (emf/wmf/tiff/bmp → png)
  * réduire les images trop grandes (une collection Anki se synchronise…)

Les noms de fichiers sont préfixés par le projet : `collection.media` d'Anki est
un espace de noms PLAT et GLOBAL, un `image1.png` écraserait celui d'un autre cours.
"""

import io
import re
from pathlib import Path

# Formats affichables directement par Anki (desktop + AnkiDroid + AnkiMobile)
ANKI_SAFE_EXT = {"png", "jpg", "jpeg", "gif", "svg", "webp"}
# Formats convertibles en PNG via Pillow
CONVERTIBLE_EXT = {"tif", "tiff", "bmp", "emf", "wmf", "ico", "ppm", "tga"}

MAX_PX_WIDTH = 1200          # au-delà, on redimensionne
JPEG_QUALITY = 85


def slugify(value: str, maxlen: int = 24) -> str:
    """Slug court et sûr pour un nom de fichier Anki (a-z0-9_)."""
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return (value[:maxlen].strip("_")) or "cours"


class MediaStore:
    """Accumule les images d'un document et les écrit sur disque."""

    def __init__(self, project_id: str, media_dir: Path, max_px_width: int = MAX_PX_WIDTH):
        self.project_id = project_id
        self.prefix = f"ag_{slugify(project_id)}"
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.max_px_width = max_px_width
        self.assets: dict[str, dict] = {}      # asset_id -> asset
        self._by_sha: dict[str, str] = {}      # sha1 -> asset_id
        self.warnings: list[str] = []

    # ── API ───────────────────────────────────────────────────
    def add(self, image, alt: str | None = None, width_cm: float | None = None) -> dict:
        """
        Ajoute une `docx.image.image.Image`. Retourne l'asset (dict).
        Un même contenu binaire renvoie toujours le même asset.
        """
        sha = image.sha1
        if sha in self._by_sha:
            asset = self.assets[self._by_sha[sha]]
            # Une occurrence ultérieure peut porter l'alt text que la première n'avait pas
            if alt and not asset.get("alt"):
                asset["alt"] = alt
                asset["alt_source"] = "docx"
            asset["occurrences"] = asset.get("occurrences", 1) + 1
            return asset

        asset_id = f"img_{len(self.assets) + 1}"
        ext = (image.ext or "").lower().lstrip(".")
        blob = image.blob
        px_width = getattr(image, "px_width", None)
        px_height = getattr(image, "px_height", None)
        note = None

        # 1. Normalisation du format
        if ext not in ANKI_SAFE_EXT:
            converted = self._convert_to_png(blob)
            if converted is None:
                note = f"format {ext or '?'} non convertible"
                self.warnings.append(
                    f"{asset_id}: image au format '{ext or '?'}' illisible, ignorée"
                )
                asset = {
                    "id": asset_id,
                    "file": None,
                    "ext": ext,
                    "sha1": sha,
                    "alt": alt or "",
                    "alt_source": "docx" if alt else None,
                    "width_cm": width_cm,
                    "px_width": px_width,
                    "px_height": px_height,
                    "bytes": len(blob),
                    "occurrences": 1,
                    "missing": True,
                    "note": note,
                }
                self.assets[asset_id] = asset
                self._by_sha[sha] = asset_id
                return asset
            blob, px_width, px_height = converted
            ext = "png"

        # 2. Réduction si trop large
        if px_width and px_width > self.max_px_width and ext != "svg":
            resized = self._resize(blob, ext, self.max_px_width)
            if resized:
                blob, ext, px_width, px_height = resized

        filename = f"{self.prefix}_{sha[:10]}.{ext}"
        (self.media_dir / filename).write_bytes(blob)

        asset = {
            "id": asset_id,
            "file": filename,
            "ext": ext,
            "sha1": sha,
            "alt": alt or "",
            "alt_source": "docx" if alt else None,
            "width_cm": width_cm,
            "px_width": px_width,
            "px_height": px_height,
            "bytes": len(blob),
            "occurrences": 1,
            "missing": False,
            "note": note,
        }
        self.assets[asset_id] = asset
        self._by_sha[sha] = asset_id
        return asset

    # ── Helpers Pillow (import paresseux : Pillow reste optionnel) ──
    @staticmethod
    def _pil():
        try:
            from PIL import Image as PILImage
            return PILImage
        except Exception:
            return None

    def _convert_to_png(self, blob: bytes):
        PILImage = self._pil()
        if PILImage is None:
            return None
        try:
            with PILImage.open(io.BytesIO(blob)) as im:
                im.load()
                if im.mode not in ("RGB", "RGBA", "L"):
                    im = im.convert("RGBA")
                out = io.BytesIO()
                im.save(out, format="PNG", optimize=True)
                return out.getvalue(), im.width, im.height
        except Exception:
            return None

    def _resize(self, blob: bytes, ext: str, max_width: int):
        PILImage = self._pil()
        if PILImage is None:
            return None
        try:
            with PILImage.open(io.BytesIO(blob)) as im:
                im.load()
                if im.width <= max_width:
                    return None
                ratio = max_width / float(im.width)
                size = (max_width, max(1, int(im.height * ratio)))
                im = im.resize(size, PILImage.LANCZOS)
                out = io.BytesIO()
                if ext in ("jpg", "jpeg"):
                    im.convert("RGB").save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                    new_ext = "jpg"
                elif ext == "gif":
                    # on ne retouche pas les GIF (animation)
                    return None
                else:
                    im.save(out, format="PNG", optimize=True)
                    new_ext = "png"
                return out.getvalue(), new_ext, im.width, im.height
        except Exception:
            return None
