#!/usr/bin/env python3
"""
app.py — Interface web pour le pipeline Ankigen.

Lance:
    .venv/bin/python app.py
puis ouvre http://127.0.0.1:5000
"""

import io
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)

import paths
import settings as user_settings
from build_anki_csv import ANKI_HEADER_LINES, parse_tsv_response
from i18n import DEFAULT_LANG, available_languages, catalog_for_js, translate
from parse_cours import build_prompts, parse_docx
from project_store import (
    PROJECT_VERSION,
    copy_media,
    delete_project,
    export_rows,
    list_projects,
    load_project,
    media_url_prefix,
    missing_alt_count,
    progress,
    project_path,
    project_view,
    prompt_view,
    save_project,
    set_asset_alt,
)
from render import resolve_placeholders

ROOT = paths.DATA_DIR
UPLOAD_DIR = paths.UPLOAD_DIR
PROJECTS_DIR = paths.PROJECTS_DIR
MEDIA_DIR = paths.MEDIA_DIR

paths.ensure_dirs()
paths.migrate_legacy_data()

SAFE_MEDIA_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")

# Templates de Skill Claude proposés sur /help. Ce sont des documents de
# plusieurs dizaines de lignes : les garder en fichiers les rend relisibles et
# modifiables sans toucher au HTML, et le rendu Jinja les échappe, donc le
# HTML des cartes d'exemple s'affiche en clair au lieu d'être interprété.
SKILL_TEMPLATE_DIR = paths.APP_DIR / "skill_templates"

app = Flask(
    __name__,
    template_folder=str(paths.APP_DIR / "templates"),
    static_folder=str(paths.APP_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


# ──────────────────────────────────────────────────────────────
# Langue et préférences
# ──────────────────────────────────────────────────────────────
def current_lang():
    return user_settings.load_settings()["language"]


def tr(key, **params):
    """Traduction hors template (messages JSON, en-têtes, contenus d'archive)."""
    return translate(key, current_lang(), **params)


@app.context_processor
def inject_i18n():
    """
    Injecte `t`, `lang` et les préférences dans tous les templates.

    Les préférences sont relues à chaque rendu : le fichier est minuscule, et un
    cache ferait diverger l'affichage juste après un changement de langue.
    """
    prefs = user_settings.load_settings()
    lang = prefs["language"]
    return {
        "t": lambda key, **params: translate(key, lang, **params),
        "lang": lang,
        "prefs": prefs,
        "js_i18n": catalog_for_js(lang),
        "languages": available_languages(),
    }


def sanitize_filename(filename):
    """Sanitize a string to be safe for filenames."""
    filename = Path(filename).stem
    filename = re.sub(r'[^A-Za-z0-9_ -]', '', filename)
    return filename.strip() or "course"


def require_project(project_id):
    project = load_project(project_id)
    if not project:
        abort(404)
    return project


def tsv_bytes(rows) -> bytes:
    import csv

    buf = io.StringIO()
    for line in ANKI_HEADER_LINES:
        buf.write(line + "\n")
    writer = csv.writer(buf, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _write_export_copy(filename, data):
    """
    Écrit une copie de l'export dans le dossier choisi par l'utilisateur.

    Retourne (chemin, None) ou (None, clé de message). Un réglage devenu invalide
    doit dégrader l'export en simple téléchargement, jamais le faire échouer :
    l'utilisateur veut son fichier, pas un message d'erreur sur un réglage.
    """
    directory = user_settings.resolve_download_dir()
    if directory is None:
        return None, "export.dir_unavailable"
    try:
        target = directory / filename
        target.write_bytes(data)
        return str(target), None
    except OSError:
        return None, "export.write_failed"


def _with_export_headers(response, filename, data):
    """
    Ajoute X-Export-Path / X-Export-Error à une réponse d'export.

    Le chemin est percent-encodé : WSGI encode les en-têtes en latin-1, et un
    dossier utilisateur peut contenir n'importe quel caractère. Le JS le repasse
    par decodeURIComponent.
    """
    path, error = _write_export_copy(filename, data)
    response.headers["X-Export-Path"] = quote(path or "")
    if error:
        response.headers["X-Export-Error"] = quote(tr(error))
    return response


# ──────────────────────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("upload.html", projects=list_projects())


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("docx")
    if not file or not file.filename.lower().endswith(".docx"):
        return render_template(
            "upload.html", error=tr("upload.error_not_docx"), projects=list_projects()
        ), 400

    deck_prefix = (request.form.get("deck_prefix") or "").strip()
    project_id = sanitize_filename(file.filename)

    # Ensure unique project_id
    base_id = project_id
    counter = 1
    while project_path(project_id).exists():
        project_id = f"{base_id}_{counter}"
        counter += 1

    # Le nom d'origine ne doit jamais servir tel quel de chemin : on repart de
    # l'identifiant assaini (le titre du chapitre en est dérivé de la même façon).
    saved = UPLOAD_DIR / f"{project_id}.docx"
    file.save(saved)

    try:
        chunks, assets, warnings = parse_docx(
            saved, deck_prefix, project_id=project_id,
            title_stem=Path(file.filename).stem, lang=current_lang(),
        )
    except Exception as e:
        return render_template(
            "upload.html", error=tr("upload.error_parsing", error=e), projects=list_projects()
        ), 500

    if not chunks:
        return (
            render_template(
                "upload.html",
                error=tr("upload.error_no_chunks"),
                projects=list_projects(),
            ),
            400,
        )

    project = {
        "version": PROJECT_VERSION,
        "deck_prefix": deck_prefix,
        "source": file.filename,
        "assets": assets,
        "warnings": warnings,
        "prompts": build_prompts(chunks, assets, current_lang()),
    }
    save_project(project_id, project)
    return redirect(url_for("work", project_id=project_id))


@app.route("/work/<project_id>")
def work(project_id):
    project = load_project(project_id)
    if not project:
        return redirect(url_for("index"))
    return render_template(
        "work.html",
        project_id=project_id,
        prompts=project_view(project, project_id),
        progress=progress(project),
        missing_alt=missing_alt_count(project),
        warnings=project.get("warnings", []),
    )


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


def load_skill_template(lang):
    """Template de Skill dans la langue demandée, avec repli sur l'anglais."""
    for candidate in (lang, DEFAULT_LANG):
        try:
            return (SKILL_TEMPLATE_DIR / f"{candidate}.md").read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


@app.route("/help")
def help_page():
    return render_template("help.html",
                           skill_template=load_skill_template(current_lang()))


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify(user_settings.load_settings())
    data = request.get_json(silent=True) or {}
    return jsonify(ok=True, settings=user_settings.save_settings(data))


@app.route("/api/settings/check-dir", methods=["POST"])
def api_settings_check_dir():
    """Dit à l'interface si un dossier candidat tient debout, sans rien enregistrer."""
    data = request.get_json(silent=True) or {}
    ok, message_key = user_settings.check_dir(data.get("path") or "")
    return jsonify(ok=ok, message=tr(message_key))


# ──────────────────────────────────────────────────────────────
# Médias
# ──────────────────────────────────────────────────────────────
@app.route("/media/<project_id>/<filename>")
def media(project_id, filename):
    """Sert une image extraite du .docx (aperçu dans l'app)."""
    if not SAFE_MEDIA_NAME.match(filename) or not SAFE_MEDIA_NAME.match(project_id.replace(" ", "_")):
        abort(404)
    directory = MEDIA_DIR / project_id
    if not directory.is_dir():
        abort(404)
    return send_from_directory(directory, filename, max_age=3600)


@app.route("/api/asset/<project_id>/<asset_id>", methods=["POST"])
def api_asset(project_id, asset_id):
    """Édition du texte alternatif d'une image → re-rend les prompts concernés."""
    project = require_project(project_id)
    data = request.get_json(silent=True) or {}
    alt = (data.get("alt") or "").strip()

    try:
        touched = set_asset_alt(project, asset_id, alt, current_lang())
    except KeyError:
        return jsonify(error=tr("api.asset_not_found", id=asset_id)), 404

    save_project(project_id, project)
    prompts = {
        p["id"]: prompt_view(project, project_id, p)
        for p in project["prompts"] if p["id"] in touched
    }
    return jsonify(
        ok=True,
        asset_id=asset_id,
        alt=alt,
        updated=sorted(touched),
        prompts=list(prompts.values()),
        missing_alt=missing_alt_count(project),
    )


# ──────────────────────────────────────────────────────────────
# API travail
# ──────────────────────────────────────────────────────────────
@app.route("/api/save/<project_id>", methods=["POST"])
def api_save(project_id):
    project = load_project(project_id)
    if not project:
        return jsonify(error=tr("api.project_not_found")), 404

    data = request.get_json(silent=True) or {}
    try:
        chunk_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify(error=tr("api.bad_id")), 400

    response = (data.get("response") or "").strip()
    mark_done = bool(data.get("mark_done", True))

    for p in project["prompts"]:
        if p["id"] == chunk_id:
            p["response"] = response
            if response and mark_done:
                p["status"] = "done"
            elif not response:
                p["status"] = "pending"
            save_project(project_id, project)
            cards = parse_tsv_response(response) if response else []
            return jsonify(
                ok=True,
                id=chunk_id,
                status=p["status"],
                cards_detected=len(cards),
                progress=progress(project),
            )

    return jsonify(error=tr("api.chunk_not_found", id=chunk_id)), 404


@app.route("/api/preview/<project_id>", methods=["POST"])
def api_preview(project_id):
    """
    Aperçu des cartes : parse la réponse TSV et résout {{IMG:n}} / {{TABLE:n}}
    avec des URL servies par l'app (et non les noms plats d'Anki).
    """
    project = require_project(project_id)
    data = request.get_json(silent=True) or {}
    try:
        chunk_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify(error=tr("api.bad_id")), 400

    prompt = next((p for p in project["prompts"] if p["id"] == chunk_id), None)
    if prompt is None:
        return jsonify(error=tr("api.chunk_not_found", id=chunk_id)), 404

    response = data.get("response")
    if response is None:
        response = prompt.get("response", "")

    assets = project.get("assets", {})
    prefix = media_url_prefix(project_id)
    cards, unknown = [], []
    for question, answer in parse_tsv_response(response):
        q, _, unk_q = resolve_placeholders(question, prompt, assets, prefix)
        a, _, unk_a = resolve_placeholders(answer, prompt, assets, prefix)
        unknown.extend(unk_q + unk_a)
        cards.append({"question": q, "answer": a})

    return jsonify(ok=True, cards=cards, count=len(cards), unknown_placeholders=unknown)


@app.route("/api/state/<project_id>")
def api_state(project_id):
    project = load_project(project_id)
    if not project:
        return jsonify(prompts=[], progress={"total": 0, "done": 0, "pending": 0})
    return jsonify(
        prompts=project_view(project, project_id),
        progress=progress(project),
        missing_alt=missing_alt_count(project),
    )


# ──────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────
@app.route("/export.tsv/<project_id>")
def export_tsv(project_id):
    project = require_project(project_id)
    only_done = request.args.get("only_done") == "1"

    rows, report = export_rows(project, only_done=only_done)
    data = tsv_bytes(rows)
    filename = f"{project_id}_export.tsv"

    response = send_file(
        io.BytesIO(data),
        mimetype="text/tab-separated-values; charset=utf-8",
        as_attachment=True,
        download_name=filename,
    )
    return _with_export_headers(response, filename, data)


@app.route("/export.zip/<project_id>")
def export_zip(project_id):
    """TSV + images utilisées, dans une archive prête à décompresser."""
    project = require_project(project_id)
    only_done = request.args.get("only_done") == "1"

    rows, report = export_rows(project, only_done=only_done)
    media_dir = MEDIA_DIR / project_id

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{project_id}_export.tsv", tsv_bytes(rows))
        for name in report["media"]:
            src = media_dir / name
            if src.exists():
                zf.write(src, f"media/{name}")
        # Le nom du fichier suit la langue : un francophone ne cherche pas README.txt.
        zf.writestr(
            tr("export.readme_filename"),
            "\r\n".join([
                tr("export.readme_title", project=project_id),
                "",
                tr("export.readme_counts",
                   cards=report["cards"], images=len(report["media"])),
                "",
                tr("export.readme_step_media"),
                tr("export.readme_step_media_path"),
                tr("export.readme_step_import"),
                tr("export.readme_step_header"),
                "",
                tr("export.readme_tip"),
            ]),
        )
    buf.seek(0)
    data = buf.getvalue()
    filename = f"{project_id}_export.zip"
    response = send_file(
        io.BytesIO(data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )
    return _with_export_headers(response, filename, data)


@app.route("/api/export/report/<project_id>")
def api_export_report(project_id):
    """Rapport d'export (cartes, images utilisées, placeholders orphelins)."""
    project = require_project(project_id)
    only_done = request.args.get("only_done") == "1"
    _, report = export_rows(project, only_done=only_done)
    report["anki_profiles"] = paths.anki_media_dirs()
    return jsonify(report)


@app.route("/api/export/anki-media/<project_id>", methods=["POST"])
def api_export_anki_media(project_id):
    """
    Copie les images utilisées dans le dossier collection.media d'un profil Anki.
    Le profil doit être choisi explicitement côté interface.
    """
    project = require_project(project_id)
    data = request.get_json(silent=True) or {}
    destination = (data.get("path") or "").strip()
    only_done = bool(data.get("only_done"))

    allowed = {p["path"] for p in paths.anki_media_dirs()}
    if destination not in allowed:
        return jsonify(error=tr("api.unknown_media_dir")), 400

    _, report = export_rows(project, only_done=only_done)
    if not report["media"]:
        return jsonify(ok=True, result={"copied": [], "identical": [], "conflicts": [],
                                        "missing": [], "destination": destination},
                       message=tr("api.no_media_used"))

    result = copy_media(project_id, report["media"], Path(destination))
    return jsonify(ok=True, result=result)


@app.route("/delete/<project_id>", methods=["POST"], endpoint="delete_project")
def delete_project_route(project_id):
    delete_project(project_id)
    return redirect(url_for("index"))

# ──────────────────────────────────────────────────────────────
# Auto-update (repris de main)
# ──────────────────────────────────────────────────────────────
@app.route("/api/update/check")
def api_update_check():
    """Vérifie si une mise à jour est disponible (sans l'appliquer)."""
    try:
        from updater import (
            fetch_latest_release,
            fetch_remote_manifest,
            get_local_commit,
            get_local_version,
            is_update_available,
        )
        release = fetch_latest_release()
        local = get_local_version()
        manifest = fetch_remote_manifest(release)
        remote = (manifest or {}).get("version") or release["tag_name"].lstrip("v")
        return jsonify({
            "update_available": is_update_available(manifest, local, get_local_commit()),
            "local_version": local,
            "remote_version": remote,
            "release_notes": release.get("body", ""),
        })
    except Exception as e:
        # Pas de release publiée, hors-ligne, quota GitHub… : ce sont des
        # conditions normales, pas des erreurs serveur. On répond 200 avec
        # update_available=False pour ne pas polluer la console du client.
        return jsonify({"update_available": False, "error": str(e)})


@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    """Applique la mise à jour depuis GitHub Releases."""
    from updater import check_and_update
    result = check_and_update()
    result["message"] = tr(result.pop("message_key"), **result.pop("message_params"))
    status_code = 200 if result["status"] != "error" else 500
    return jsonify(result), status_code


@app.route("/api/version")
def api_version():
    """Retourne la version locale courante."""
    from updater import get_local_version
    return jsonify({"version": get_local_version()})


if __name__ == "__main__":
    import os

    # ANKI_GEN_PORT permet de lancer le serveur de dev sans entrer en conflit
    # avec l'app packagée, qui occupe déjà le port 5000.
    app.run(debug=True, host="127.0.0.1", port=int(os.environ.get("ANKI_GEN_PORT", 5000)))
