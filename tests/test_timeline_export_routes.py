#!/usr/bin/env python3
"""
tests/test_timeline_export_routes.py — Exports d'une frise (phase 5, §9).

Chaque format sort de la frise enregistrée, sous le nom `<slug>.<ext>`, et, comme
l'export des cartes, en copie dans le dossier d'export de l'utilisateur
(X-Export-Path). La copie pour le presse-papiers n'écrit rien sur le disque.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import io
import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import settings  # noqa: E402
import timeline_store  # noqa: E402
from test_timeline_routes import FIXTURE, RoutesTestCase  # noqa: E402

SLUG = "la-dynamique-de-la-mondialisation-economique"


class ExportTestCase(RoutesTestCase):
    def setUp(self):
        super().setUp()
        self.exports = self.tmp / "exports"
        self.exports.mkdir()
        settings.save_settings({"download_dir": str(self.exports)})
        self.tid = self.created_id()

    def get(self, fmt, query=""):
        return self.client.get(f"/export/timeline/{self.tid}.{fmt}{'?' + query if query else ''}")

    def image(self, response):
        return Image.open(io.BytesIO(response.data))


class TestFormats(ExportTestCase):
    def test_every_format_is_downloaded_and_copied_to_the_export_folder(self):
        expected = {"png": ("image/png", "png"), "jpeg": ("image/jpeg", "jpg"), "webp": ("image/webp", "webp"),
                    "pdf": ("application/pdf", "pdf"), "svg": ("image/svg+xml", "svg"),
                    "json": ("application/json", "json")}
        for fmt, (mimetype, extension) in expected.items():
            with self.subTest(fmt=fmt):
                response = self.get(fmt, "scale=1")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, mimetype)
                filename = f"{SLUG}.{extension}"
                self.assertIn(f"filename={filename}", response.headers["Content-Disposition"])
                copy = Path(unquote(response.headers["X-Export-Path"]))
                self.assertEqual(copy, self.exports / filename)
                self.assertEqual(copy.read_bytes(), response.data)

    def test_png_options(self):
        response = self.get("png", "scale=1&theme=dark")
        image = self.image(response)
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.getpixel((1, 1)), (0x1C, 0x1C, 0x1E))
        width = image.size[0]
        doubled = self.image(self.get("png", "scale=2"))
        self.assertEqual(doubled.size[0], width * 2)
        transparent = self.image(self.get("png", "scale=1&transparent=1"))
        self.assertEqual(transparent.mode, "RGBA")
        self.assertEqual(transparent.getpixel((1, 1))[3], 0)
        fixed = self.image(self.get("png", "scale=1&width_mode=fixed&width_px=1000"))
        self.assertEqual(fixed.size[0], 1000)

    def test_out_of_range_options_fall_back(self):
        image = self.image(self.get("png", "scale=99&theme=%3Cscript%3E&width_px=-5"))
        reference = self.image(self.get("png", "scale=4"))
        self.assertEqual(image.size, reference.size)
        self.assertEqual(image.getpixel((1, 1)), (255, 255, 255))      # thème clair par défaut

    def test_jpeg_and_webp(self):
        jpeg = self.image(self.get("jpeg", "scale=1&quality=70&transparent=1"))
        self.assertEqual((jpeg.format, jpeg.mode), ("JPEG", "RGB"))
        webp = self.image(self.get("webp", "scale=1&lossless=1"))
        self.assertEqual(webp.format, "WEBP")

    def test_pdf_page_and_small_print_warning(self):
        response = self.get("pdf", "page=a4&orientation=portrait")
        self.assertTrue(response.data.startswith(b"%PDF"))
        box = [float(v) for v in re.search(rb"/MediaBox \[([^\]]+)\]", response.data).group(1).split()]
        self.assertEqual((round(box[2]), round(box[3])), (595, 842))
        warning = unquote(response.headers["X-Export-Warning"])
        self.assertIn("le texte sera très petit", warning)

    def test_svg_embeds_the_font_unless_asked_not_to(self):
        svg = self.get("svg").get_data(as_text=True)
        self.assertTrue(svg.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        ET.fromstring(svg.split("\n", 1)[1])
        self.assertIn("@font-face", svg)
        self.assertNotIn("@font-face", self.get("svg", "embed_font=0").get_data(as_text=True))

    def test_json_is_the_saved_document(self):
        exported = json.loads(self.get("json").get_data(as_text=True))
        self.assertEqual(exported, timeline_store.load_timeline(self.tid)["data"])

    def test_clipboard_copy_writes_nothing(self):
        response = self.get("png", "scale=1&to=clipboard")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("X-Export-Path", response.headers)
        self.assertEqual(list(self.exports.iterdir()), [])

    def test_unavailable_export_folder_still_downloads(self):
        settings.save_settings({"download_dir": str(self.tmp / "missing" / "file.txt")})
        (self.tmp / "missing").mkdir()
        (self.tmp / "missing" / "file.txt").write_text("x", encoding="utf-8")
        response = self.get("json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Export-Path"], "")
        self.assertTrue(response.headers["X-Export-Error"])

    def test_refusals(self):
        self.assertEqual(self.get("gif").status_code, 404)
        self.assertEqual(self.client.get("/export/timeline/absent-0000.png").status_code, 404)
        self.assertEqual(self.client.get("/export/timeline/..%5Csettings.json").status_code, 404)
        empty = self.client.post("/timeline/new", json={"text": "x", "title": "Vide"}).get_json()["id"]
        self.assertEqual(self.client.get(f"/export/timeline/{empty}.png").status_code, 404)


class TestUnverifiedMarking(ExportTestCase):
    def setUp(self):
        super().setUp()
        data = json.loads(FIXTURE)
        data["events"][0]["source_quote"] = "Une citation que le cours ne contient pas du tout"
        record = timeline_store.new_record(title="Citations", lang="fr", source={"kind": "text"},
                                           source_text="Le traité Cobden-Chevalier de 1860.", data=data)
        self.tid = "citations-0001"
        timeline_store.save_timeline(self.tid, record)

    def test_off_by_default_on_request(self):
        self.assertNotIn("Marqueur cerclé", self.get("svg", "embed_font=0").get_data(as_text=True))
        self.assertIn("Marqueur cerclé", self.get("svg", "embed_font=0&unverified=1").get_data(as_text=True))


class TestPreview(ExportTestCase):
    def preview(self, fmt, **options):
        return self.client.post(f"/api/timeline/{self.tid}/export-preview", json={"fmt": fmt, "options": options})

    def test_raster_preview_announces_the_real_size(self):
        body = self.preview("png", scale=2, theme="dark").get_json()
        self.assertTrue(body["ok"])
        self.assertIn('class="tl-thumb-root"', body["svg"])
        self.assertIn('fill="#1C1C1E"', body["svg"])
        image = self.image(self.get("png", "scale=2&theme=dark"))
        self.assertEqual((body["output"]["width"], body["output"]["height"]), image.size)
        self.assertGreater(body["output"]["bytes"], 0)
        self.assertEqual(body["filename"], f"{SLUG}.png")

    def test_pdf_preview(self):
        body = self.preview("pdf", page="a4", orientation="portrait").get_json()
        self.assertEqual(body["output"]["page_mm"], [210.0, 297.0])
        self.assertEqual(body["warnings"][0]["code"], "pdf_small_print")
        self.assertIn("très petit", body["warnings"][0]["message"])

    def test_svg_and_json_sizes(self):
        svg = self.preview("svg", embed_font=True).get_json()["output"]["bytes"]
        plain = self.preview("svg", embed_font=False).get_json()["output"]["bytes"]
        self.assertGreater(svg, plain + 300_000)          # une graisse d'Inter en base64 au moins
        body = self.preview("json").get_json()
        self.assertEqual(body["filename"], f"{SLUG}.json")
        self.assertGreater(body["output"]["bytes"], 1000)

    def test_the_page_offers_the_export(self):
        html = self.client.get(f"/timeline/{self.tid}").get_data(as_text=True)
        self.assertIn('id="tl-export"', html)
        self.assertIn("timeline-export.js", html)
        self.assertIn(f"/export/timeline/{self.tid}.FORMAT", html)


if __name__ == "__main__":
    unittest.main()
