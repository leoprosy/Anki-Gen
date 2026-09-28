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


PROBES = {
    "pillow_roundtrip": _pillow_roundtrip,
    "docx_and_lxml": _docx_and_lxml,
    "server_stack": _server_stack,
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
