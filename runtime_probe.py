#!/usr/bin/env python3
"""
runtime_probe.py — Ce que le code de l'app attend de l'exécutable qui le fait tourner.

Importer un module ne prouve pas qu'il marche : Pillow s'importe très bien sans
FreeType, et un encodeur absent n'échoue qu'au premier `save()`. Ce module
exerce donc, pour de vrai, les capacités dont l'app a besoin.

Il voyage dans app.zip avec le code, pas dans l'exécutable : quand une
fonctionnalité réclame une nouvelle capacité, on l'ajoute ici, et
`flask-server.exe --self-check` la vérifie aussi bien sur l'exe neuf que sur
l'exe de la release précédente (voir scripts/check_runtime_compat.py).

Règle : ce module ne lève jamais. Chaque sonde renvoie un message d'échec ou None.
"""

import io


def _pillow_roundtrip():
    """media_store.py : lecture, conversion RGBA, redimensionnement, PNG et JPEG."""
    from PIL import Image

    image = Image.new("RGB", (64, 48), (0, 113, 227))
    for fmt in ("BMP", "TIFF"):
        buffer = io.BytesIO()
        image.save(buffer, format=fmt)
        with Image.open(io.BytesIO(buffer.getvalue())) as reopened:
            reopened.convert("RGBA").resize((32, 24), Image.LANCZOS).save(
                io.BytesIO(), format="PNG", optimize=True)
    image.save(io.BytesIO(), format="JPEG", quality=85, optimize=True)


def _docx_and_lxml():
    """parse_cours.py / docx_blocks.py : lecture d'un .docx et XPath lxml."""
    import docx  # noqa: F401
    from lxml import etree

    etree.fromstring(b"<w:p xmlns:w='urn:x'><w:r/></w:p>").xpath("//*[local-name()='r']")


def _server_stack():
    """launcher.py / app.py : WSGI et rendu de template."""
    import waitress  # noqa: F401
    from flask import Flask, render_template_string

    with Flask(__name__).app_context():
        render_template_string("{{ 1 + 1 }}")


def _timeline_raster():
    """
    timeline_render_raster.py : Inter par FreeType (moteur de mise en page basique,
    celui des mesures), texte accentué aux trois ancres, réduction LANCZOS,
    composition alpha, puis PNG, JPEG, WebP (avec et sans perte) et PDF.
    """
    from pathlib import Path

    from PIL import Image, ImageDraw, ImageFont

    fonts = Path(__file__).resolve().parent / "static" / "fonts"
    basic = ImageFont.Layout.BASIC
    regular = ImageFont.truetype(str(fonts / "Inter-Regular.ttf"), 39, layout_engine=basic)
    semibold = ImageFont.truetype(str(fonts / "Inter-SemiBold.ttf"), 39, layout_engine=basic)
    width = regular.getlength("Traité Cobden-Chevalier — août 1971")
    if not 400 < width < 800:
        raise ValueError(f"largeur de texte inattendue : {width}")
    image = Image.new("RGBA", (900, 120), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([10, 60, 600, 90], radius=15, fill=(0, 114, 178, 255))
    for anchor, font in (("ls", regular), ("ms", semibold), ("rs", regular)):
        draw.text((450, 50), "Élément «œuvre» — XVIe s.", font=font, fill=(29, 29, 31, 255), anchor=anchor)
    if image.getbbox() is None:
        raise ValueError("rien n'a été dessiné")
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([700, 70, 720, 90], fill=(213, 94, 0, 115))
    small = Image.alpha_composite(image, layer).resize((300, 40), Image.LANCZOS)
    small.save(io.BytesIO(), format="PNG", optimize=True)
    small.convert("RGB").save(io.BytesIO(), format="JPEG", quality=90, subsampling=0)
    small.save(io.BytesIO(), format="WEBP", quality=90)
    small.save(io.BytesIO(), format="WEBP", lossless=True)
    buffer = io.BytesIO()
    small.convert("RGB").save(buffer, format="PDF", resolution=300.0, title="Frise", author="Ankigen")
    if not buffer.getvalue().startswith(b"%PDF"):
        raise ValueError("PDF invalide")


def _local_llm():
    """
    local_llm.py : les DLL de llama.cpp chargées depuis l'exécutable, et le schéma
    de frise compilé en grammaire (c'est elle qui force une réponse JSON conforme).
    Le modèle lui-même n'est pas chargé : il se télécharge à la demande.
    """
    import json

    import llama_cpp
    from llama_cpp.llama_grammar import LlamaGrammar, json_schema_to_gbnf

    import timeline_schema

    if b"CPU" not in llama_cpp.llama_print_system_info():
        raise ValueError("llama.cpp sans backend CPU")
    LlamaGrammar.from_string(json_schema_to_gbnf(json.dumps(timeline_schema.json_schema())), verbose=False)


PROBES = {
    "pillow_roundtrip": _pillow_roundtrip,
    "docx_and_lxml": _docx_and_lxml,
    "server_stack": _server_stack,
    "timeline_raster": _timeline_raster,
    "local_llm": _local_llm,
}


def run() -> dict:
    """{nom de la sonde: None si elle passe, sinon le message d'erreur}."""
    results = {}
    for name, probe in PROBES.items():
        try:
            probe()
            results[name] = None
        except Exception as error:  # une sonde ne doit jamais interrompre les autres
            results[name] = f"{type(error).__name__}: {error}"
    return results
