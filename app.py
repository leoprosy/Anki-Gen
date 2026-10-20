#!/usr/bin/env python3
"""
app.py — Interface web pour le pipeline Ankigen.

Lance:
    .venv/bin/python app.py
puis ouvre http://127.0.0.1:5000
"""

import io
import json
import re
import time
import zipfile
from dataclasses import replace
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
from i18n import DEFAULT_LANG, LANGUAGES, available_languages, catalog_for_js, translate
from parse_cours import build_prompts, parse_docx
from project_store import (
    PROJECT_VERSION,
    copy_files,
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
from telemetry import client as analytics

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


@app.after_request
def record_app_activity(response):
    # Les sondages updater et API ne prouvent pas une utilisation de l'interface.
    if request.method == "GET" and response.status_code == 200 and request.endpoint in {
        "index", "work", "settings_page", "help_page",
    }:
        analytics.track("app_opened")
    return response


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


@app.template_filter("ago")
def ago(timestamp):
    """Durée écoulée depuis `timestamp`, en clair (« il y a 2 h »)."""
    seconds = max(0, time.time() - timestamp)
    if seconds < 60:
        return tr("upload.ago_now")
    for unit, size in (("days", 86400), ("hours", 3600), ("minutes", 60)):
        if seconds >= size:
            return tr(f"upload.ago_{unit}", n=int(seconds // size))


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
    return render_template("upload.html", projects=list_projects(), timelines=_timeline_summaries(),
                           timeline_i18n=catalog_for_js(current_lang(), prefix="timeline.ui."))


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
    analytics.track("project_created", chunk_count=len(project["prompts"]))
    return redirect(url_for("work", project_id=project_id))


@app.route("/work/<project_id>")
def work(project_id):
    project = load_project(project_id)
    if not project:
        return redirect(url_for("index"))
    course_timelines = [t for t in _timeline_summaries() if t.get("project_id") == project_id]
    return render_template(
        "work.html",
        project_id=project_id,
        prompts=project_view(project, project_id),
        progress=progress(project),
        missing_alt=missing_alt_count(project),
        warnings=project.get("warnings", []),
        timeline_i18n=catalog_for_js(current_lang(), prefix="timeline.ui."),
        linked_timelines=len(course_timelines),
        course_timelines=course_timelines, course_id=project_id,
        course_url=url_for("work", project_id=project_id), course_page="course",
        current_chunk=_course_chunk(project, request.args.get("chunk_id")),
    )


@app.route("/settings")
def settings_page():
    import local_llm
    return render_template("settings.html", local_model=local_llm.status())


def load_skill_template(lang):
    """Template de Skill dans la langue demandée, avec repli sur l'anglais."""
    for candidate in (lang, DEFAULT_LANG):
        try:
            return (SKILL_TEMPLATE_DIR / f"{candidate}.md").read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def _timeline_skill_text(lang):
    """Le Skill frise de l'aide ; une frise cassée ne doit pas empêcher l'aide de s'afficher."""
    try:
        import timeline_prompt
        return timeline_prompt.skill_text(lang)
    except Exception:           # noqa: BLE001 — l'aide passe avant la frise
        app.logger.exception("Skill frise illisible")
        return ""


@app.route("/help")
def help_page():
    return render_template("help.html",
                           skill_template=load_skill_template(current_lang()),
                           timeline_skill=_timeline_skill_text(current_lang()))


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify(user_settings.load_settings())
    data = request.get_json(silent=True) or {}
    saved = analytics.save_preferences(data)
    return jsonify(ok=True, settings=saved)


@app.route("/api/settings/check-dir", methods=["POST"])
def api_settings_check_dir():
    """Dit à l'interface si un dossier candidat tient debout, sans rien enregistrer."""
    data = request.get_json(silent=True) or {}
    ok, message_key = user_settings.check_dir(data.get("path") or "")
    return jsonify(ok=ok, message=tr(message_key))


# ──────────────────────────────────────────────────────────────
# Modèle local (local_llm.py)
# ──────────────────────────────────────────────────────────────
@app.route("/api/local-model", methods=["GET", "POST", "DELETE"])
def api_local_model():
    """GET : état. POST : lance le téléchargement. DELETE : supprime le modèle."""
    import local_llm
    if request.method == "POST":
        local_llm.start_download()
    elif request.method == "DELETE":
        local_llm.delete()
    return jsonify(ok=True, **local_llm.status())


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
            changed = response != (p.get("response") or "").strip()
            p["response"] = response
            if response and mark_done:
                p["status"] = "done"
            elif not response:
                p["status"] = "pending"
            save_project(project_id, project)
            cards = parse_tsv_response(response) if response else []
            if changed and cards:
                analytics.track("cards_saved", card_count=len(cards))
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
    # « Inclure les cartes des frises liées » : désactivé par défaut (§10.4).
    if request.args.get("timelines") == "1":
        for timeline_rows, _, _ in _linked_timeline_exports(project_id, render_media=False):
            rows += timeline_rows
    data = tsv_bytes(rows)
    filename = f"{project_id}_export.tsv"

    response = send_file(
        io.BytesIO(data),
        mimetype="text/tab-separated-values; charset=utf-8",
        as_attachment=True,
        download_name=filename,
    )
    response = _with_export_headers(response, filename, data)
    analytics.track("export_completed", card_count=len(rows), format="tsv")
    return response


@app.route("/export.zip/<project_id>")
def export_zip(project_id):
    """TSV + images utilisées, dans une archive prête à décompresser."""
    project = require_project(project_id)
    only_done = request.args.get("only_done") == "1"

    rows, report = export_rows(project, only_done=only_done)
    media_dir = MEDIA_DIR / project_id
    media = [(media_dir, name) for name in report["media"]]
    if request.args.get("timelines") == "1":
        for timeline_rows, directory, names in _linked_timeline_exports(project_id):
            rows += timeline_rows
            media += [(directory, name) for name in names]
        report["cards"] = len(rows)
        report["media"] = [name for _, name in media]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{project_id}_export.tsv", tsv_bytes(rows))
        for directory, name in media:
            src = directory / name
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
    response = _with_export_headers(response, filename, data)
    analytics.track("export_completed", card_count=len(rows), format="zip")
    return response


@app.route("/api/export/report/<project_id>")
def api_export_report(project_id):
    """Rapport d'export (cartes, images utilisées, placeholders orphelins)."""
    project = require_project(project_id)
    only_done = request.args.get("only_done") == "1"
    _, report = export_rows(project, only_done=only_done)
    if request.args.get("timelines") == "1":
        # Le rapport compte les cartes et les images des frises sans les dessiner.
        for timeline_rows, _, names in _linked_timeline_exports(project_id, render_media=False):
            report["cards"] += len(timeline_rows)
            report["media"] = report["media"] + names
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
    linked = _linked_timeline_exports(project_id) if data.get("timelines") else []
    if not report["media"] and not any(names for _, _, names in linked):
        return jsonify(ok=True, result={"copied": [], "identical": [], "conflicts": [],
                                        "missing": [], "destination": destination},
                       message=tr("api.no_media_used"))

    result = copy_media(project_id, report["media"], Path(destination))
    for _, directory, names in linked:
        more = copy_files(directory, names, Path(destination))
        for key in ("copied", "identical", "conflicts", "missing"):
            result[key] += more[key]
    return jsonify(ok=True, result=result)


@app.route("/delete/<project_id>", methods=["POST"], endpoint="delete_project")
def delete_project_route(project_id):
    delete_project(project_id)
    return redirect(url_for("index"))

# ──────────────────────────────────────────────────────────────
# Frises chronologiques
# ──────────────────────────────────────────────────────────────
# Les modules timeline_* sont importés DANS les routes : une frise cassée ne doit
# jamais empêcher l'app de démarrer ni l'accueil de s'afficher.
# (build_app_payload suit ces imports : ils partent quand même dans app.zip.)
TIMELINE_THEMES = ("light", "dark", "print")


def _timeline_summaries():
    """Frises du tableau de bord ; une erreur ici laisse l'accueil s'afficher sans elles."""
    try:
        from timeline_store import list_timelines
        return list_timelines()
    except Exception:           # noqa: BLE001 — l'accueil passe avant la frise
        app.logger.exception("liste des frises illisible")
        return []


def _timeline_error(key, status, **params):
    return jsonify(ok=False, error=tr(key, **params)), status


def _load_timeline_or_error(tid):
    """(enregistrement, None) ou (None, réponse d'erreur JSON)."""
    import timeline_store
    try:
        record = timeline_store.load_timeline(tid)
    except timeline_store.TimelineIdError:
        return None, _timeline_error("timeline.api.not_found", 404)
    except timeline_store.TimelineStoreError:
        app.logger.exception("frise illisible : %s", tid)
        return None, _timeline_error("timeline.api.unreadable", 500)
    if record is None:
        return None, _timeline_error("timeline.api.not_found", 404)
    return record, None


def _render_options(raw):
    """Options de rendu venues du navigateur : tout ce qui n'est pas reconnu est ignoré."""
    from timeline_layout import WIDTH_MAX, WIDTH_MIN, LayoutOptions
    raw = raw if isinstance(raw, dict) else {}
    theme = raw.get("theme") if raw.get("theme") in TIMELINE_THEMES else "light"
    density = raw.get("density") if raw.get("density") in ("comfortable", "compact") else "compact"
    width_mode = "fixed" if raw.get("width_mode") == "fixed" else "auto"
    try:
        width_px = min(WIDTH_MAX, max(WIDTH_MIN, int(raw.get("width_px") or 1200)))
    except (TypeError, ValueError):
        width_px = 1200
    stored = {"theme": theme, "density": density, "width_mode": width_mode, "width_px": width_px}
    return LayoutOptions(theme=theme, density=density, width_mode=width_mode, width_px=width_px), stored


def _validated(payload, default_lang):
    """Rapport de validation d'un `{raw}` (texte collé) ou d'un `{data}` (objet édité)."""
    import timeline_schema
    if isinstance(payload.get("raw"), str):
        return timeline_schema.validate_raw(payload["raw"], default_lang=default_lang)
    if "data" in payload:
        size = len(json.dumps(payload["data"], ensure_ascii=False).encode("utf-8"))
        if size > timeline_schema.MAX_DOCUMENT_BYTES:
            return timeline_schema.validate_raw("x" * (timeline_schema.MAX_DOCUMENT_BYTES + 1))
        return timeline_schema.validate(payload["data"], default_lang=default_lang)
    return timeline_schema.validate_raw("", default_lang=default_lang)


def _with_messages(report):
    import timeline_schema
    return timeline_schema.with_messages(report, current_lang())


def _date_labels(doc, lang):
    """Date affichée de chaque élément, pour les lignes du rail et les infobulles."""
    from timeline_dates import DateError, format_date, format_range, parse_date
    out = {}
    as_of = doc.get("as_of")
    for kind in ("eras", "periods", "events"):
        for element in doc.get(kind, []):
            try:
                approx = element.get("approx", False)
                if kind == "events":
                    date = parse_date(element["date"], element.get("precision"))
                    out[element["id"]] = format_date(date, lang, approx=approx)
                else:
                    start = parse_date(element["start"], element.get("precision"))
                    end = parse_date(element["end"], None if element["end"] == "present"
                                     else element.get("precision"), allow_present=True, as_of=as_of)
                    out[element["id"]] = format_range(start, end, lang, approx=approx)
            except (DateError, KeyError, TypeError):
                continue
    return out


def _course_chunk(project, candidate):
    """Un lien profond doit désigner un paragraphe du cours actuel, y compris le n° 0."""
    try:
        chunk_id = int(candidate)
    except (ValueError, TypeError):
        return None
    return chunk_id if any(p["id"] == chunk_id for p in project.get("prompts", [])) else None


def _timeline_course(record, candidate=None):
    """Liens vers le cours actuel, sans exposer son texte ni modifier l'instantané de la frise."""
    import timeline_quotes
    project_id = record["source"].get("project_id")
    if not project_id:
        return None
    try:
        project = load_project(project_id)
    except (OSError, ValueError):
        return None
    if not project:
        return None
    wanted = set(record["source"].get("chunk_ids") or [])
    paragraphs = [p for p in project.get("prompts", []) if p["id"] in wanted]
    chunk_id = _course_chunk(project, candidate)
    if chunk_id is None and paragraphs:
        chunk_id = paragraphs[0]["id"]

    def chunk_url(value):
        return url_for("work", project_id=project_id, chunk_id=value)

    links = [{"id": p["id"], "label": p.get("deck") or f"#{p['id']}", "url": chunk_url(p["id"])}
             for p in paragraphs]
    texts = [(p["id"], timeline_quotes.normalize(p.get("prompt") or "")) for p in paragraphs]
    source_links = {}
    data = record.get("data") or {}
    for kind in ("eras", "periods", "events"):
        for item in data.get(kind) or []:
            quote_text = timeline_quotes.normalize(item.get("source_quote") or "")
            matches = [i for i, text in texts if quote_text and quote_text in text]
            if len(matches) == 1:
                source_links[item["id"]] = chunk_url(matches[0])
    return {"id": project_id, "url": chunk_url(chunk_id), "chunk_id": chunk_id, "paragraphs": links,
            "element_links": source_links}


def _timeline_view(record, course_chunk=None):
    """Ce que la page reçoit : l'enregistrement, sans le texte source (jusqu'à 200 000 caractères)."""
    import timeline_prompt
    source, extraction = record["source"], record["extraction"]
    text = record.get("source_text") or ""
    chunks = []
    if extraction["strategy"] == "per_chunk":
        # La section Sources : un paragraphe par ligne, avec son état.
        for chunk_id, start, end in source.get("spans") or []:
            heading = timeline_prompt.chunk_heading(text, source["spans"], chunk_id)
            entry = extraction["per_chunk"].get(str(chunk_id)) or {}
            chunks.append({"id": chunk_id, "heading": heading, "title": heading.split(" › ")[-1],
                           "status": entry.get("status") or "pending", "chars": end - start,
                           "mentions": timeline_prompt.date_mentions(text[start:end])})
    project_id = source.get("project_id")
    return {
        "id": record["id"],
        "title": (record.get("data") or {}).get("title") or record.get("title") or "",
        "lang": (record.get("data") or {}).get("lang") or record.get("lang") or current_lang(),
        "source": source,
        "course": _timeline_course(record, course_chunk),
        "has_source_text": bool(text),
        "source_chars": len(text),
        # §11 : un projet supprimé laisse ses frises intactes ; l'interface le signale.
        "project_exists": bool(project_id) and project_path(project_id).exists(),
        "data": record.get("data"),
        "last_raw": (record.get("raw_responses") or [None])[-1],
        "render_options": record.get("render_options") or {},
        "extraction": {key: extraction[key] for key in ("mode", "strategy", "skill")},
        "chunks": chunks,
        "merge": extraction["merge"].get("report"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _with_quotes(report, record):
    """Statuts des citations d'un document valide, vérifiées contre l'instantané du texte source."""
    import timeline_quotes
    return timeline_quotes.annotate(report, record.get("source_text"))


def _remerge(record, lang, *, force):
    """
    Refait la frise depuis les réponses des paragraphes (paragraphe par paragraphe).

    Si le document a été retouché depuis la dernière fusion, rien n'est écrasé
    sans `force` : l'interface demande d'abord confirmation.
    """
    import timeline_extract
    merge = record["extraction"]["merge"]
    current = record.get("data")
    edited = bool(current) and (merge.get("hash") is None
                                or timeline_extract.document_hash(current) != merge["hash"])
    if edited and not force:
        return {"merged": False, "edited": True, "report": None}
    report, merge_report = timeline_extract.merge_record(record, lang=lang)
    merge["report"] = merge_report
    if report is None:              # aucun paragraphe utile : la frise reste vide
        record["data"], merge["hash"] = None, None
        return {"merged": True, "edited": False, "report": None}
    if report["ok"]:
        record["data"] = report["normalized"]
        merge["hash"] = timeline_extract.document_hash(record["data"])
    return {"merged": report["ok"], "edited": False, "report": report}


def _merge_payload(record, result):
    report = result.get("report")
    view = _timeline_view(record)
    return {
        "merged": result["merged"],
        "edited": result["edited"],
        "data": record.get("data"),
        "merge": record["extraction"]["merge"].get("report"),
        "document_report": _with_messages(_with_quotes(report, record)) if report else None,
        "chunks": view["chunks"],
        "course": view["course"],
        "updated_at": record.get("updated_at"),
    }


def _chunk_source(record, chunk_arg):
    """(identifiant, texte du paragraphe) d'un chunk de la frise ; ValueError s'il n'en fait pas partie."""
    import timeline_prompt
    try:
        chunk_id = int(chunk_arg)
        return chunk_id, timeline_prompt.chunk_text(record.get("source_text") or "",
                                                    record["source"].get("spans"), chunk_id)
    except (TypeError, ValueError, KeyError):
        raise ValueError(chunk_arg) from None


@app.route("/timeline/<tid>")
def timeline_page(tid):
    import local_llm
    record, error = _load_timeline_or_error(tid)
    if error:
        return redirect(url_for("index"))
    view = _timeline_view(record, request.args.get("chunk_id"))
    course = view["course"]
    return render_template(
        "timeline.html",
        timeline=view,
        timeline_i18n=catalog_for_js(current_lang(), prefix="timeline."),
        course_id=course["id"] if course else None,
        course_url=course["url"] if course else None, course_page="timeline",
        course_timelines=[t for t in _timeline_summaries() if course and t.get("project_id") == course["id"]],
        # Faux sur un exécutable antérieur, qui n'embarque pas llama.cpp.
        local_model=local_llm.available(),
    )


@app.route("/timeline/new", methods=["POST"])
def timeline_new():
    """
    Nouvelle frise, depuis un JSON (`{json, force?}`) ou un texte (`{text, title, lang}`).

    Un JSON invalide est refusé avec son rapport ; `force` crée quand même une frise
    vide qui garde le collage, pour le corriger dans l'onglet JSON.
    """
    import timeline_schema
    import timeline_store
    payload = request.get_json(silent=True) or {}
    lang = current_lang()
    try:
        if isinstance(payload.get("scope"), dict):
            return _timeline_from_scope(payload, lang)
        if isinstance(payload.get("json"), str):
            raw = payload["json"]
            report = timeline_schema.validate_raw(raw, default_lang=lang)
            if report["ok"]:
                data = report["normalized"]
                tid, record = timeline_store.create_timeline(
                    title=data["title"], lang=data["lang"], data=data, source={"kind": "import"})
            elif payload.get("force"):
                title = tr("timeline.ui.untitled")
                record = timeline_store.new_record(title=title, lang=lang, source={"kind": "import"})
                timeline_store.push_raw_response(record, raw)
                tid = timeline_store.new_timeline_id(title)
                record = timeline_store.save_timeline(tid, record)
            else:
                return jsonify(ok=False, report=_with_messages(report)), 422
        elif isinstance(payload.get("text"), str):
            title = (payload.get("title") or "").strip()
            if not title:
                return _timeline_error("timeline.api.title_required", 400)
            text_lang = payload.get("lang") if payload.get("lang") in ("en", "fr") else lang
            tid, record = timeline_store.create_timeline(
                title=title[:120], lang=text_lang, source={"kind": "text"}, source_text=payload["text"])
        else:
            return _timeline_error("timeline.api.bad_request", 400)
    except ValueError:
        return _timeline_error("timeline.api.text_too_long", 400,
                               max=timeline_store.MAX_SOURCE_CHARS)
    return jsonify(ok=True, id=tid, url=url_for("timeline_page", tid=tid))


def _timeline_from_scope(payload, lang):
    """
    Frise d'une portée de la vue de travail (`{scope: {kind, project_id, deck_path,
    chunk_ids}, title?, lang?, mode?, strategy?}`) : le texte source est figé tout de suite.
    """
    import timeline_prompt
    import timeline_store
    scope = payload["scope"]
    project_id = scope.get("project_id")
    project = load_project(project_id) if isinstance(project_id, str) else None
    if not project:
        return _timeline_error("api.project_not_found", 404)
    try:
        chunks = timeline_prompt.scope_chunks(project, scope)
    except (TypeError, ValueError):
        return _timeline_error("timeline.api.scope_empty", 400)
    text, spans = timeline_prompt.build_source(chunks, project.get("deck_prefix"))
    if not text:
        return _timeline_error("timeline.api.scope_empty", 400)
    title = (payload.get("title") or "").strip() if isinstance(payload.get("title"), str) else ""
    title = title or timeline_prompt.scope_title(project, scope) or tr("timeline.ui.untitled")
    strategy = payload.get("strategy")
    if strategy not in timeline_store.EXTRACTION_STRATEGIES:
        strategy = timeline_prompt.default_strategy(len(text))
    mode = payload.get("mode") if payload.get("mode") in timeline_store.EXTRACTION_MODES else "strict"
    tid, _ = timeline_store.create_timeline(
        title=title[:120],
        lang=payload.get("lang") if payload.get("lang") in ("en", "fr") else timeline_prompt.guess_lang(text, lang),
        source={"kind": scope["kind"], "project_id": project_id,
                "deck_path": timeline_prompt.scope_deck(project, scope),
                "chunk_ids": [span[0] for span in spans], "spans": spans},
        source_text=text, extraction={"mode": mode, "strategy": strategy})
    return jsonify(ok=True, id=tid, url=url_for("timeline_page", tid=tid))


@app.route("/timeline/<tid>/delete", methods=["POST"])
def timeline_delete(tid):
    import timeline_store
    try:
        timeline_store.delete_timeline(tid)
    except timeline_store.TimelineIdError:
        abort(404)
    return redirect(url_for("index"))


@app.route("/api/timelines")
def api_timelines():
    return jsonify(timelines=_timeline_summaries())


@app.route("/api/timeline/<tid>", methods=["GET", "POST"])
def api_timeline(tid):
    """GET : la frise et le rapport de son document. POST : `{data}` ou `{raw}` → validation, enregistrement."""
    import timeline_schema
    import timeline_store
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    view = _timeline_view(record)
    if request.method == "GET":
        report = timeline_schema.validate(record["data"], default_lang=view["lang"]) if record["data"] else None
        return jsonify(ok=True, timeline=view,
                       report=_with_messages(_with_quotes(report, record)) if report else None)

    payload = request.get_json(silent=True) or {}
    extraction = payload.get("extraction")
    if isinstance(extraction, dict):
        if extraction.get("mode") in timeline_store.EXTRACTION_MODES:
            record["extraction"]["mode"] = extraction["mode"]
        if isinstance(extraction.get("skill"), bool):
            record["extraction"]["skill"] = extraction["skill"]
    if "options" in payload:
        record["render_options"] = _render_options(payload["options"])[1]
    if isinstance(payload.get("raw"), str) and payload.get("chunk_id") is not None:
        return _save_chunk_response(tid, record, payload, view["lang"])
    if not isinstance(payload.get("raw"), str) and "data" not in payload:
        # Réglages seuls (mode d'extraction, Skill, options de rendu).
        record = timeline_store.save_timeline(tid, record)
        return jsonify(ok=True, updated_at=record["updated_at"])

    report = _with_quotes(_validated(payload, view["lang"]), record)
    if isinstance(payload.get("raw"), str):
        timeline_store.push_raw_response(record, payload["raw"])
    if report["ok"]:
        data = report["normalized"]
        record["data"] = data
        record["title"] = data["title"]
        record["lang"] = data["lang"]
    record = timeline_store.save_timeline(tid, record)
    status = 200 if report["ok"] else 422
    return jsonify(ok=report["ok"], report=_with_messages(report),
                   course=_timeline_course(record),
                   updated_at=record["updated_at"]), status


def _save_chunk_response(tid, record, payload, lang):
    """
    Collage d'un paragraphe (paragraphe par paragraphe) : il est validé seul, gardé
    brut, puis la frise est refaite par fusion. Un paragraphe sans date est un
    état normal (`empty`), pas une erreur.
    """
    import timeline_extract
    import timeline_store
    try:
        chunk_id, text = _chunk_source(record, payload["chunk_id"])
    except ValueError:
        return _timeline_error("timeline.api.chunk_unknown", 404)
    raw = payload["raw"]
    _, report = timeline_extract.ManualExtractor().parse_response(raw, lang=lang, source_text=text, chunk=True)
    record["extraction"]["per_chunk"][str(chunk_id)] = {"status": report["status"], "raw": raw}
    timeline_store.push_raw_response(record, raw)
    result = {"merged": False, "edited": False, "report": None}
    if report["status"] != "error":
        result = _remerge(record, lang, force=bool(payload.get("replace_edits")))
    record = timeline_store.save_timeline(tid, record)
    ok = report["status"] != "error"
    return jsonify(ok=ok, chunk={"id": chunk_id, "status": report["status"]},
                   report=_with_messages(report), **_merge_payload(record, result)), 200 if ok else 422


@app.route("/api/timeline/<tid>/merge", methods=["POST"])
def api_timeline_merge(tid):
    """
    Refait la fusion des paragraphes : `{separate: clé}` annule la fusion d'un groupe
    de doublons, `{join: clé}` la rétablit, `{force: true}` accepte d'écraser les
    retouches faites depuis la dernière fusion.
    """
    import timeline_store
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    keep = record["extraction"]["merge"]["keep_separate"]
    if isinstance(payload.get("separate"), str) and payload["separate"] not in keep:
        keep.append(payload["separate"])
    if isinstance(payload.get("join"), str) and payload["join"] in keep:
        keep.remove(payload["join"])
    result = _remerge(record, _timeline_view(record)["lang"], force=bool(payload.get("force")))
    if result["edited"]:
        return jsonify(ok=False, **_merge_payload(record, result)), 409
    record = timeline_store.save_timeline(tid, record)
    return jsonify(ok=True, **_merge_payload(record, result))


def _extraction_source(record, chunk_arg):
    """
    (texte à extraire, pistes à réutiliser) : toute la frise, ou un paragraphe.
    ValueError si le paragraphe n'en fait pas partie.
    """
    if not chunk_arg and chunk_arg != 0:
        return record.get("source_text") or "", ()
    _, text = _chunk_source(record, chunk_arg)
    # Le modèle réutilise les pistes déjà présentes : la fusion reste lisible.
    return text, [{"id": t["id"], "label": t["label"]} for t in (record.get("data") or {}).get("tracks") or []]


@app.route("/api/timeline/<tid>/local", methods=["POST"])
def api_timeline_local(tid):
    """
    `{chunk_id?, mode?}` → `{raw, parts, failed}` : le modèle local extrait la
    frise, ou un paragraphe, et corrige lui-même ses réponses refusées. Un texte
    dont le prompt dépasse sa fenêtre est coupé en morceaux, extraits un à un puis
    fusionnés. La réponse repart côté client par le chemin d'un collage : rien
    n'est enregistré ici.
    """
    import local_llm
    import timeline_extract
    import timeline_prompt
    import timeline_store
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    if not record.get("source_text"):
        return _timeline_error("timeline.api.no_source", 404)
    payload = request.get_json(silent=True) or {}
    chunk_arg = payload.get("chunk_id")
    try:
        text, tracks = _extraction_source(record, chunk_arg)
    except ValueError:
        return _timeline_error("timeline.api.chunk_unknown", 404)
    view = _timeline_view(record)
    mode = payload.get("mode") if payload.get("mode") in timeline_store.EXTRACTION_MODES else record["extraction"]["mode"]

    def build_prompt(piece, chunk):
        return timeline_prompt.extraction_prompt(piece, lang=view["lang"], mode=mode, title=view["title"],
                                                 chunk=chunk, tracks=tracks)
    extractor = timeline_extract.LocalExtractor(local_llm.complete, too_long=local_llm.PromptTooLong)
    try:
        raw, parts = extractor.extract(text, build_prompt, lang=view["lang"], title=view["title"],
                                       chunk=chunk_arg is not None, on_part=local_llm.set_part)
    except local_llm.ModelMissing:
        return _timeline_error("local_model.missing", 409)
    except local_llm.PromptTooLong as error:     # un mot de plusieurs milliers de jetons…
        return _timeline_error("local_model.too_long", 413, tokens=error.tokens)
    except Exception:           # noqa: BLE001 — llama.cpp absent, modèle illisible, mémoire…
        app.logger.exception("modèle local en échec")
        return _timeline_error("local_model.failed", 500)
    finally:
        local_llm.set_part()
    return jsonify(ok=True, raw=raw, **parts)


@app.route("/api/timeline/<tid>/prompt")
def api_timeline_prompt(tid):
    """Prompt d'extraction : de toute la frise, ou d'un paragraphe (`?chunk_id=`), `?mode=`, `?skill=1`."""
    import timeline_extract
    import timeline_store
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    text = record.get("source_text") or ""
    if not text:
        return _timeline_error("timeline.api.no_source", 404)
    view = _timeline_view(record)
    extraction = record["extraction"]
    mode = request.args.get("mode")
    mode = mode if mode in timeline_store.EXTRACTION_MODES else extraction["mode"]
    skill = request.args.get("skill") == "1" if "skill" in request.args else extraction["skill"]
    chunk_arg = request.args.get("chunk_id")
    try:
        text, tracks = _extraction_source(record, chunk_arg)
    except ValueError:
        return _timeline_error("timeline.api.chunk_unknown", 404)
    built = timeline_extract.ManualExtractor().build_request(
        text, view["lang"], mode, title=view["title"], skill=skill, chunk=bool(chunk_arg), tracks=tracks)
    return jsonify(ok=True, prompt=built["prompt"], chars=built["chars"], tokens=built["tokens"],
                   mode=mode, skill=skill)


@app.route("/api/timeline/<tid>/correction-prompt")
def api_timeline_correction_prompt(tid):
    """Prompt de correction du dernier collage (de la frise, ou d'un paragraphe : `?chunk_id=`)."""
    import timeline_extract
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    lang = _timeline_view(record)["lang"]
    chunk_arg = request.args.get("chunk_id")
    if chunk_arg:
        try:
            chunk_id, text = _chunk_source(record, chunk_arg)
        except ValueError:
            return _timeline_error("timeline.api.chunk_unknown", 404)
        raw = (record["extraction"]["per_chunk"].get(str(chunk_id)) or {}).get("raw")
    else:
        text, raw = record.get("source_text"), (record.get("raw_responses") or [None])[-1]
    if not raw:
        return _timeline_error("timeline.api.nothing_to_fix", 404)
    extractor = timeline_extract.ManualExtractor()
    _, report = extractor.parse_response(raw, lang=lang, source_text=text, chunk=bool(chunk_arg))
    built = extractor.correction_request(report, lang=lang, include_warnings=request.args.get("warnings") == "1")
    if not built["prompt"]:
        return _timeline_error("timeline.api.nothing_to_fix", 404)
    return jsonify(ok=True, **built)


@app.route("/api/timeline/scopes/<project_id>")
def api_timeline_scopes(project_id):
    """Portées proposées depuis la vue de travail pour le chunk courant : taille, tokens, stratégie."""
    import timeline_prompt
    project = load_project(project_id)
    if not project or not project["prompts"]:
        return _timeline_error("api.project_not_found", 404)
    try:
        chunk_id = int(request.args.get("chunk_id"))
    except (TypeError, ValueError):
        chunk_id = project["prompts"][0]["id"]
    lang = current_lang()

    def summary(scope):
        try:
            result = timeline_prompt.scope_summary(project, scope, lang)
        except ValueError:
            return None
        return result if result["chars"] else None

    chapters = []
    for level in timeline_prompt.chapter_levels(project, chunk_id):
        found = summary({"kind": "chapter", "deck_path": level["deck_path"]})
        if found:
            chapters.append(dict(found, label=level["label"], path=level["path"], depth=level["depth"]))
    return jsonify(
        ok=True, lang=lang, threshold=timeline_prompt.SINGLE_PROMPT_MAX_CHARS, chunk_id=chunk_id,
        chunk=summary({"kind": "chunk", "chunk_ids": [chunk_id]}), chapters=chapters,
        project=summary({"kind": "project"}),
        timelines=[t for t in _timeline_summaries() if t["project_id"] == project_id],
    )


@app.route("/timeline/skill.md")
def timeline_skill():
    """Le Skill « Frise chronologique Ankigen », à copier dans un fichier SKILL.md."""
    import timeline_prompt
    lang = request.args.get("lang") if request.args.get("lang") in ("en", "fr") else current_lang()
    return app.response_class(timeline_prompt.skill_text(lang), mimetype="text/markdown")


@app.route("/api/timeline/validate", methods=["POST"])
def api_timeline_validate():
    payload = request.get_json(silent=True) or {}
    lang = payload.get("lang") if payload.get("lang") in ("en", "fr") else current_lang()
    return jsonify(_with_messages(_validated(payload, lang)))


@app.route("/api/timeline/<tid>/render", methods=["POST"])
def api_timeline_render(tid):
    """
    `{data?, options}` → `{svg, width, height, warnings, stats, notes, dates}`.

    Alimente l'aperçu : on y envoie le document NON enregistré en cours d'édition ;
    sans `data`, c'est le document enregistré qui est dessiné.
    """
    from timeline_render_svg import render
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    lang = _timeline_view(record)["lang"]
    report = _validated(payload, lang) if "data" in payload else None
    if report is not None and not report["ok"]:
        return jsonify(ok=False, report=_with_messages(report)), 422
    doc = report["normalized"] if report else record.get("data")
    if not doc:
        return _timeline_error("timeline.api.empty", 404)
    import timeline_quotes
    quotes, _ = timeline_quotes.check_document(doc, record.get("source_text"))
    options, _ = _render_options(payload.get("options"))
    # L'aperçu montre les citations introuvables ; l'export ne le fera que sur option.
    options = replace(options, unverified=tuple(sorted(i for i, s in quotes.items() if s == "not_found")))
    result = render(doc, options, id_prefix="tl-preview")
    warnings = [dict(w, message=tr(f"timeline.warn.{w['code']}", **w.get("params", {})))
                for w in result.warnings]
    return jsonify(
        ok=True, svg=result.svg, width=result.width, height=result.height,
        warnings=warnings, stats=result.stats, notes=list(result.layout.notes),
        dates=_date_labels(doc, doc["lang"]), quotes=quotes,
        report=_with_messages(_with_quotes(report, record)) if report else None,
    )


# ── Exports (§9) ───────────────────────────────────────────────
TIMELINE_EXPORT_FORMATS = ("png", "jpeg", "webp", "pdf", "svg", "json")


def _export_options(source, record):
    """Options d'export venues de la requête : toute valeur inconnue reprend son défaut."""
    from timeline_layout import WIDTH_MAX, WIDTH_MIN
    stored = record.get("render_options") or {}

    def number(name, default, low, high, cast=float):
        try:
            return min(high, max(low, cast(source.get(name))))
        except (TypeError, ValueError):
            return default

    def flag(name, default):
        value = source.get(name)
        return default if value is None else str(value).lower() in ("1", "true")

    density = source.get("density")
    return {
        # L'export est en clair par défaut, quel que soit le thème de l'interface (§8.4).
        "theme": source.get("theme") if source.get("theme") in TIMELINE_THEMES else "light",
        "density": density if density in ("comfortable", "compact") else stored.get("density", "compact"),
        "width_mode": "fixed" if source.get("width_mode") == "fixed" else "auto",
        "width_px": number("width_px", 1200, WIDTH_MIN, WIDTH_MAX, int),
        "scale": number("scale", 2.0, 1.0, 4.0),
        "transparent": flag("transparent", False),
        "quality": number("quality", 90, 1, 100, int),
        "lossless": flag("lossless", False),
        "embed_font": flag("embed_font", True),
        "page": source.get("page") if source.get("page") in ("fit", "a4", "a3") else "fit",
        "orientation": "portrait" if source.get("orientation") == "portrait" else "landscape",
        "margin": number("margin", 10.0, 0.0, 30.0),
        # Le marquage des citations introuvables est désactivé par défaut à l'export (§6.5).
        "unverified": flag("unverified", False),
    }


def _export_render(record, doc, options, **svg_options):
    """Mise en page (et SVG) d'un export, avec ses options de rendu."""
    import timeline_quotes
    from timeline_render_svg import render
    layout_options, _ = _render_options(options)
    if options["unverified"]:
        quotes, _ = timeline_quotes.check_document(doc, record.get("source_text"))
        layout_options = replace(layout_options, unverified=tuple(sorted(
            i for i, status in quotes.items() if status == "not_found")))
    else:
        layout_options = replace(layout_options, show_unverified=False)
    return render(doc, layout_options, **svg_options)


def _export_warnings(warnings):
    return [dict(w, message=tr(f"timeline.export.{w['code']}", **w.get("params", {}))) for w in warnings]


@app.route("/export/timeline/<tid>.<fmt>")
def export_timeline(tid, fmt):
    """
    Frise enregistrée → fichier. Comme l'export des cartes : téléchargement, copie dans
    le dossier d'export (X-Export-Path), sauf pour le presse-papiers (`?to=clipboard`).
    """
    import timeline_render_raster
    import timeline_store
    if fmt not in TIMELINE_EXPORT_FORMATS:
        abort(404)
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    doc = record.get("data")
    if not doc:
        return _timeline_error("timeline.api.empty", 404)
    options = _export_options(request.args, record)
    warnings = []
    if fmt == "json":
        data = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        mimetype, extension = "application/json", "json"
    elif fmt == "svg":
        rendered = _export_render(record, doc, options, embed_font=options["embed_font"])
        data = ('<?xml version="1.0" encoding="UTF-8"?>\n' + rendered.svg + "\n").encode("utf-8")
        mimetype, extension = "image/svg+xml", "svg"
    else:
        rendered = _export_render(record, doc, options)
        exported = timeline_render_raster.export(
            rendered.layout, fmt, scale=options["scale"], transparent=options["transparent"],
            quality=options["quality"], lossless=options["lossless"], page=options["page"],
            orientation=options["orientation"], margin_mm=options["margin"], title=doc.get("title", ""))
        data, mimetype, extension = exported.data, exported.mimetype, exported.extension
        warnings = _export_warnings(exported.warnings)
    filename = f"{timeline_store.slugify_title(doc.get('title'))}.{extension}"
    response = send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=filename)
    if warnings:
        response.headers["X-Export-Warning"] = quote(" ".join(w["message"] for w in warnings))
    if request.args.get("to") != "clipboard":
        response = _with_export_headers(response, filename, data)
    return response


@app.route("/api/timeline/<tid>/export-preview", methods=["POST"])
def api_timeline_export_preview(tid):
    """Ce que la modale d'export annonce : miniature, dimensions finales, poids estimé, avertissements."""
    import timeline_render_raster
    import timeline_store
    from timeline_render_svg import render_svg
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    doc = record.get("data")
    if not doc:
        return _timeline_error("timeline.api.empty", 404)
    payload = request.get_json(silent=True) or {}
    fmt = payload.get("fmt") if payload.get("fmt") in TIMELINE_EXPORT_FORMATS else "png"
    options = _export_options(payload.get("options") if isinstance(payload.get("options"), dict) else {}, record)
    rendered = _export_render(record, doc, options, id_prefix="tl-thumb")
    layout = rendered.layout
    if fmt in timeline_render_raster.FORMATS:
        output = timeline_render_raster.estimate(
            layout, fmt, scale=options["scale"], lossless=options["lossless"], page=options["page"],
            orientation=options["orientation"], margin_mm=options["margin"])
        extension = timeline_render_raster.EXTENSIONS[fmt]
    elif fmt == "svg":
        size = len(render_svg(layout, title=doc.get("title", ""), embed_font=options["embed_font"]).encode("utf-8"))
        output = {"width": round(layout.width), "height": round(layout.height), "bytes": size, "warnings": []}
        extension = "svg"
    else:
        size = len(json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8"))
        output = {"bytes": size, "warnings": []}
        extension = "json"
    warnings = _export_warnings(output.pop("warnings"))
    return jsonify(ok=True, svg=rendered.svg, width=layout.width, height=layout.height, output=output,
                   warnings=warnings, filename=f"{timeline_store.slugify_title(doc.get('title'))}.{extension}")


# ── Cartes Anki (§10) ──────────────────────────────────────────
def _card_state(record):
    """(document, cartes, types choisis, mise en page des images ou None) de la frise enregistrée."""
    import timeline_cards
    from timeline_render_svg import render
    doc = record.get("data")
    options = record.get("card_options") or {}
    wanted = options.get("types", timeline_cards.DEFAULT_TYPES)
    types = [kind for kind in timeline_cards.CARD_TYPES if kind in (wanted or ())]
    if not doc:
        return None, [], types, None
    layout_options = timeline_cards.card_layout_options(record.get("render_options"))
    layout = None
    if {"whole_image", "masked_image"} & set(types):
        layout = render(doc, layout_options).layout
    cards = timeline_cards.generate(
        doc, types=types, layout=layout,
        media_prefix=timeline_cards.media_prefix(record["id"], record["source"].get("project_id")),
        render_key=f"{layout_options.theme}/{layout_options.density}")
    return doc, cards, types, layout


def _scope_base_deck(record):
    """Deck de la portée : enregistré à la création, retrouvé dans le projet, sinon le titre."""
    import timeline_prompt
    from timeline_store import display_title
    source = record["source"]
    if source.get("deck_path"):
        return source["deck_path"]
    project = load_project(source["project_id"]) if source.get("project_id") else None
    if project and source["kind"] in ("chunk", "project"):
        try:
            return timeline_prompt.scope_deck(project, {"kind": source["kind"],
                                                        "chunk_ids": (source.get("chunk_ids") or [])[:1]})
        except (ValueError, TypeError):
            pass
    return display_title(record).replace("::", ":")


def _cards_deck(record):
    """
    (deck, fixé à l'instant ?) Le deck est figé dans la frise à la première génération :
    jamais retraduit, pour la même raison que DEFAULT_DECK_NAME dans project_store.
    """
    import timeline_cards
    if record.get("cards_deck"):
        return record["cards_deck"], False
    lang = (record.get("data") or {}).get("lang") or record.get("lang") or current_lang()
    record["cards_deck"] = timeline_cards.default_deck(_scope_base_deck(record), lang)
    return record["cards_deck"], True


def _enabled_cards(record):
    """(cartes actives, mise en page) : les cartes désactivées une à une restent hors des exports."""
    _, cards, _, layout = _card_state(record)
    disabled = set(record.get("disabled_cards") or [])
    return [card for card in cards if card.id not in disabled], layout


def _card_media(cards):
    names = []
    for card in cards:
        for name in card.media:
            if name not in names:
                names.append(name)
    return names


def _timeline_card_export(record, *, render_media=True):
    """(lignes TSV, dossier des images, noms des images) des cartes actives d'une frise."""
    import timeline_cards
    import timeline_store
    deck, fixed = _cards_deck(record)
    if fixed:
        timeline_store.save_timeline(record["id"], record)
    cards, layout = _enabled_cards(record)
    directory = paths.timeline_media_dir(record["id"])
    if render_media and layout is not None:
        timeline_cards.ensure_media(cards, layout, directory)
    return [[deck, card.front, card.back] for card in cards], directory, _card_media(cards)


def _linked_timeline_exports(project_id, *, render_media=True):
    """Cartes des frises tirées d'un projet, pour « Inclure les cartes des frises liées »."""
    import timeline_store
    out = []
    for summary in _timeline_summaries():
        if summary.get("project_id") != project_id:
            continue
        try:
            record = timeline_store.load_timeline(summary["id"])
        except timeline_store.TimelineStoreError:
            continue
        if record and record.get("data"):
            rows, directory, names = _timeline_card_export(record, render_media=render_media)
            if rows:
                out.append((rows, directory, names))
    return out


def _card_view(card, tid, disabled):
    """Carte pour l'aperçu : les images pointent vers la route qui les rend à la demande."""
    base = url_for("timeline_card_media", tid=tid, filename="__NAME__")
    front, back = card.front, card.back
    for name in card.media:
        url = base.replace("__NAME__", name)
        front = front.replace(f'src="{name}"', f'src="{url}" loading="lazy" alt=""')
        back = back.replace(f'src="{name}"', f'src="{url}" loading="lazy" alt=""')
    return {"id": card.id, "type": card.type, "ref": card.ref, "front": front, "back": back,
            "enabled": card.id not in disabled}


@app.route("/api/timeline/<tid>/cards", methods=["POST"])
def api_timeline_cards(tid):
    """
    Aperçu des cartes de la frise enregistrée. `{types}` choisit les types, `{deck}`
    renomme le deck, `{toggle: {id, enabled}}` active ou désactive une carte.
    """
    import timeline_cards
    import timeline_store
    record, error = _load_timeline_or_error(tid)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    changed = False
    if isinstance(payload.get("types"), list):
        record["card_options"]["types"] = [k for k in timeline_cards.CARD_TYPES if k in payload["types"]]
        changed = True
    if isinstance(payload.get("deck"), str) and payload["deck"].strip():
        deck = " ".join(payload["deck"].split())[:200]
        record["cards_deck"] = "::".join(part.strip() for part in deck.split("::") if part.strip())
        changed = bool(record["cards_deck"]) or changed
    toggle = payload.get("toggle")
    if isinstance(toggle, dict) and isinstance(toggle.get("id"), str):
        disabled = set(record.get("disabled_cards") or [])
        (disabled.discard if toggle.get("enabled") else disabled.add)(toggle["id"])
        record["disabled_cards"] = sorted(disabled)
        changed = True
    deck, fixed = _cards_deck(record) if record.get("data") else (record.get("cards_deck"), False)
    if changed or fixed:
        record = timeline_store.save_timeline(tid, record)
    doc, cards, types, _ = _card_state(record)
    disabled = set(record.get("disabled_cards") or [])
    views = [_card_view(card, tid, disabled) for card in cards]
    return jsonify(ok=True, has_data=bool(doc), deck=deck, types=types, cards=views,
                   counts={kind: sum(1 for c in cards if c.type == kind) for kind in timeline_cards.CARD_TYPES},
                   enabled=sum(1 for view in views if view["enabled"]),
                   anki_profiles=paths.anki_media_dirs())


@app.route("/media/timeline/<tid>/<filename>")
def timeline_card_media(tid, filename):
    """Image d'une carte : rendue à la première demande, puis servie depuis le disque."""
    import timeline_cards
    import timeline_store
    if not timeline_store.valid_id(tid) or not SAFE_MEDIA_NAME.match(filename):
        abort(404)
    directory = paths.timeline_media_dir(tid)
    if not (directory / filename).is_file():
        record, error = _load_timeline_or_error(tid)
        if error:
            abort(404)
        _, cards, _, layout = _card_state(record)
        owners = [card for card in cards if filename in card.media]
        if not owners or layout is None:
            abort(404)
        timeline_cards.ensure_media(owners, layout, directory, names={filename})
    return send_from_directory(directory, filename, max_age=3600)


def _timeline_card_file(tid, extension):
    """(frise, lignes, dossier, noms, nom de fichier) ou (None, réponse d'erreur)."""
    import timeline_store
    record, error = _load_timeline_or_error(tid)
    if error:
        return None, error
    if not record.get("data"):
        return None, _timeline_error("timeline.api.empty", 404)
    rows, directory, names = _timeline_card_export(record, render_media=extension != "tsv")
    filename = f"{timeline_store.slugify_title(timeline_store.display_title(record))}-cards.{extension}"
    return (record, rows, directory, names, filename), None


@app.route("/export/timeline/<tid>/cards.tsv")
def export_timeline_cards_tsv(tid):
    found, error = _timeline_card_file(tid, "tsv")
    if error:
        return error
    _, rows, _, _, filename = found
    data = tsv_bytes(rows)
    response = send_file(io.BytesIO(data), mimetype="text/tab-separated-values; charset=utf-8",
                         as_attachment=True, download_name=filename)
    return _with_export_headers(response, filename, data)


@app.route("/export/timeline/<tid>/cards.zip")
def export_timeline_cards_zip(tid):
    """TSV + images des cartes, dans une archive prête à décompresser (comme l'export du projet)."""
    import timeline_store
    found, error = _timeline_card_file(tid, "zip")
    if error:
        return error
    record, rows, directory, names, filename = found
    title = timeline_store.display_title(record)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename[:-4] + ".tsv", tsv_bytes(rows))
        for name in names:
            if (directory / name).is_file():
                archive.write(directory / name, f"media/{name}")
        archive.writestr(tr("export.readme_filename"), "\r\n".join([
            tr("export.readme_title", project=title), "",
            tr("export.readme_counts", cards=len(rows), images=len(names)), "",
            tr("export.readme_step_media"), tr("export.readme_step_media_path"),
            tr("export.readme_step_import"), tr("export.readme_step_header"), "",
            tr("export.readme_tip"),
        ]))
    data = buffer.getvalue()
    response = send_file(io.BytesIO(data), mimetype="application/zip", as_attachment=True, download_name=filename)
    return _with_export_headers(response, filename, data)


@app.route("/api/timeline/<tid>/anki-media", methods=["POST"])
def api_timeline_anki_media(tid):
    """Copie les images des cartes dans le collection.media d'un profil Anki choisi (même contrôle)."""
    payload = request.get_json(silent=True) or {}
    destination = (payload.get("path") or "").strip()
    if destination not in {p["path"] for p in paths.anki_media_dirs()}:
        return jsonify(error=tr("api.unknown_media_dir")), 400
    found, error = _timeline_card_file(tid, "zip")
    if error:
        return error
    _, _, directory, names, _ = found
    if not names:
        return jsonify(ok=True, result={"copied": [], "identical": [], "conflicts": [], "missing": [],
                                        "destination": destination}, message=tr("api.no_media_used"))
    return jsonify(ok=True, result=copy_files(directory, names, Path(destination)))


@app.route("/api/timeline/date")
def api_timeline_date():
    """Aperçu en direct d'une date du tiroir d'édition : « 1971-08-15 » → « 15 août 1971 »."""
    from timeline_dates import DateError, format_date, parse_date
    value = (request.args.get("value") or "").strip()
    precision = request.args.get("precision") or None
    lang = request.args.get("lang") if request.args.get("lang") in ("en", "fr") else current_lang()
    try:
        date = parse_date(value, precision, allow_present=request.args.get("end") == "1",
                          as_of=request.args.get("as_of") or None)
    except DateError as error:
        return jsonify(ok=False, message=tr(f"timeline.err.{error.code}", **error.params))
    if date.present:
        return jsonify(ok=True, text=tr("timeline.ui.present"))
    return jsonify(ok=True, text=format_date(date, lang, approx=request.args.get("approx") == "1"))


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
            get_local_runtime,
            get_local_version,
            get_staged_version,
            is_update_available,
            runtime_supports,
        )
        staged = get_staged_version()
        if staged:
            return jsonify({
                "update_available": False,
                "restart_required": True,
                "remote_version": staged,
                "message": tr("update.staged", version=staged),
            })
        release = fetch_latest_release()
        local = get_local_version()
        manifest = fetch_remote_manifest(release)
        remote = (manifest or {}).get("version") or release["tag_name"].lstrip("v")
        available = is_update_available(manifest, local, get_local_commit())
        if available and not runtime_supports(manifest, get_local_runtime()):
            # Le nouveau code a besoin d'un exécutable plus récent : app.zip ne
            # suffit pas, on oriente vers l'installateur au lieu de le préparer.
            return jsonify({
                "update_available": False,
                "installer_required": True,
                "local_version": local,
                "remote_version": remote,
                "message": tr("update.installer_required", version=remote),
            })
        return jsonify({
            "update_available": available,
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


@app.route("/api/update/open-installer", methods=["POST"])
def api_update_open_installer():
    """
    Ouvre la page de l'installateur dans le navigateur par défaut.

    C'est le serveur qui l'ouvre : la fenêtre Tauri n'a pas le droit d'ouvrir un
    lien externe, et le serveur tourne de toute façon sur la machine de
    l'utilisateur. L'URL est une constante, jamais reçue de la requête.
    """
    import webbrowser

    from updater import INSTALLER_PAGE_URL
    return jsonify(ok=webbrowser.open(INSTALLER_PAGE_URL))


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
