#!/usr/bin/env python3
"""
app.py — Interface web pour le pipeline Anki ESH.

Lance:
    .venv/bin/python app.py
puis ouvre http://127.0.0.1:5000
"""

import csv
import io
import json
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from build_anki_csv import parse_tsv_response
from parse_cours import SYSTEM_PROMPT, build_prompts, parse_docx

ROOT = Path(__file__).parent.resolve()
UPLOAD_DIR = ROOT / "uploads"
PROMPTS_PATH = ROOT / "prompts.json"
CSV_PATH = ROOT / "anki_export.csv"

UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


def load_prompts():
    if not PROMPTS_PATH.exists():
        return None
    return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))


def save_prompts(prompts):
    PROMPTS_PATH.write_text(
        json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def progress(prompts):
    total = len(prompts)
    done = sum(1 for p in prompts if p.get("status") == "done")
    return {"total": total, "done": done, "pending": total - done}


@app.route("/")
def index():
    prompts = load_prompts()
    if prompts:
        return redirect(url_for("work"))
    return render_template("upload.html")


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("docx")
    if not file or not file.filename.lower().endswith(".docx"):
        return render_template("upload.html", error="Merci de fournir un fichier .docx."), 400

    deck_prefix = (request.form.get("deck_prefix") or "*ESH*").strip() or "*ESH*"

    saved = UPLOAD_DIR / file.filename
    file.save(saved)

    try:
        chunks = parse_docx(saved, deck_prefix)
    except Exception as e:
        return render_template("upload.html", error=f"Erreur de parsing : {e}"), 500

    if not chunks:
        return (
            render_template(
                "upload.html",
                error="Aucun chunk détecté dans ce document.",
            ),
            400,
        )

    prompts = build_prompts(chunks)
    save_prompts(prompts)
    return redirect(url_for("work"))


@app.route("/work")
def work():
    prompts = load_prompts()
    if not prompts:
        return redirect(url_for("index"))
    return render_template(
        "work.html",
        prompts=prompts,
        system_prompt=SYSTEM_PROMPT,
        progress=progress(prompts),
    )


@app.route("/api/save", methods=["POST"])
def api_save():
    prompts = load_prompts()
    if not prompts:
        return jsonify(error="Aucun prompts.json en cours."), 404

    data = request.get_json(silent=True) or {}
    try:
        chunk_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify(error="id manquant ou invalide"), 400

    response = (data.get("response") or "").strip()
    mark_done = bool(data.get("mark_done", True))

    for p in prompts:
        if p["id"] == chunk_id:
            p["response"] = response
            if response and mark_done:
                p["status"] = "done"
            elif not response:
                p["status"] = "pending"
            save_prompts(prompts)
            cards = parse_tsv_response(response) if response else []
            return jsonify(
                ok=True,
                id=chunk_id,
                status=p["status"],
                cards_detected=len(cards),
                progress=progress(prompts),
            )

    return jsonify(error=f"chunk {chunk_id} introuvable"), 404


@app.route("/api/state")
def api_state():
    prompts = load_prompts()
    if not prompts:
        return jsonify(prompts=[], progress={"total": 0, "done": 0, "pending": 0})
    return jsonify(prompts=prompts, progress=progress(prompts))


@app.route("/export.csv")
def export_csv():
    prompts = load_prompts()
    if not prompts:
        abort(404)

    only_done = request.args.get("only_done") == "1"

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
    total = 0
    for p in prompts:
        response = (p.get("response") or "").strip()
        if not response:
            continue
        if only_done and p.get("status") != "done":
            continue
        for question, reponse in parse_tsv_response(response):
            writer.writerow([p.get("deck", "ESH"), question, reponse])
            total += 1

    buf.seek(0)
    data = buf.getvalue().encode("utf-8")
    CSV_PATH.write_bytes(data)
    return send_file(
        io.BytesIO(data),
        mimetype="text/tab-separated-values; charset=utf-8",
        as_attachment=True,
        download_name="anki_export.csv",
    )


@app.route("/reset", methods=["POST"])
def reset():
    if PROMPTS_PATH.exists():
        PROMPTS_PATH.unlink()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
