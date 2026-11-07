#!/usr/bin/env python3
"""
mcp_server.py — Ankigen exposé à Claude comme serveur MCP (stdio, sans dépendance).

Lancé par `flask-server.exe --mcp` (voir launcher.py) ou, en dev, `python launcher.py --mcp`.
Chaque outil appelle une route de l'app via `app.test_client()` : même validation,
même stockage que l'interface, sans serveur HTTP ni port à découvrir. Le code vit
dans APP_DIR, donc les outils évoluent avec les mises à jour de l'app.

Protocole : JSON-RPC 2.0, un message par ligne sur stdin/stdout. Seul le sous-ensemble
« tools » est implémenté (initialize, ping, tools/list, tools/call).
"""

import json
import sys
from pathlib import Path
from urllib.parse import unquote

import paths

PROTOCOL_VERSION = "2025-06-18"
INSTRUCTIONS = (
    "Ankigen turns .docx courses into Anki decks and builds timelines. "
    "Before writing cards or a timeline, call `guide` once for the expected format. "
    "Cards: import_docx → get_paragraphs → save_cards per paragraph → export_project. "
    "Timelines: create_timeline with a JSON document; fix it with update_timeline if the report has errors."
)

_client = None


def client():
    global _client
    if _client is None:
        from app import app
        _client = app.test_client()
    return _client


def _result(resp):
    """
    Réponse d'une route → (texte pour Claude, is_error).

    `resp` est une réponse Flask de test : `resp.status_code`, `resp.get_json(silent=True)`
    (None si ce n'est pas du JSON), `resp.get_data(as_text=True)`.
    """
    body = resp.get_json(silent=True)
    if body is None:   # page HTML d'erreur, texte brut…
        return f"HTTP {resp.status_code}: {resp.get_data(as_text=True)[:500]}", resp.status_code >= 400
    # Le JSON entier : le `report` d'une frise invalide est ce qui permet à Claude de se corriger.
    return json.dumps(body, ensure_ascii=False), resp.status_code >= 400 or body.get("ok") is False


def _saved(resp, fallback_name):
    """Export binaire : chemin de la copie faite par l'app, sinon copie dans EXPORT_DIR."""
    if resp.status_code != 200:
        return _result(resp)
    path = unquote(resp.headers.get("X-Export-Path", ""))
    if not path:
        paths.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        target = paths.EXPORT_DIR / fallback_name
        target.write_bytes(resp.data)
        path = str(target)
    return json.dumps({"ok": True, "path": path}), False


# ── Outils ─────────────────────────────────────────────────────

def guide(kind):
    import app as web
    lang = web.current_lang()
    if kind == "timeline":
        import timeline_prompt
        return timeline_prompt.skill_text(lang), False
    return web.load_skill_template(lang), False


def list_projects():
    from project_store import list_projects as projects
    return json.dumps(projects(), ensure_ascii=False), False


def import_docx(path, deck_prefix=""):
    source = Path(path)
    if source.suffix.lower() != ".docx" or not source.is_file():
        return f"Not a readable .docx file: {path}", True
    with source.open("rb") as handle:
        resp = client().post("/upload", data={"docx": (handle, source.name), "deck_prefix": deck_prefix},
                             content_type="multipart/form-data")
    if resp.status_code == 302:   # succès : redirection vers /work/<id>
        return json.dumps({"ok": True, "project_id": unquote(resp.headers["Location"].rsplit("/", 1)[-1])}), False
    return f"Import failed (HTTP {resp.status_code})", True


def get_paragraphs(project_id, only_pending=False):
    resp = client().get(f"/api/state/{project_id}")
    body = resp.get_json()
    if not body["prompts"]:
        return f"Unknown project: {project_id}", True
    # Le texte du prompt suffit à Claude : l'aperçu HTML et les URL d'images sont pour l'UI.
    keep = ("id", "deck", "prompt", "status", "response")
    items = [{k: p[k] for k in keep} for p in body["prompts"]
             if not only_pending or p["status"] != "done"]
    return json.dumps({"progress": body["progress"], "paragraphs": items}, ensure_ascii=False), False


def save_cards(project_id, paragraph_id, tsv):
    return _result(client().post(f"/api/save/{project_id}", json={"id": paragraph_id, "response": tsv}))


def export_project(project_id, format="zip"):
    fmt = "tsv" if format == "tsv" else "zip"
    return _saved(client().get(f"/export.{fmt}/{project_id}"), f"{project_id}_export.{fmt}")


def list_timelines():
    return _result(client().get("/api/timelines"))


def create_timeline(json_document):
    return _result(client().post("/timeline/new", json={"json": json_document}))


def update_timeline(timeline_id, json_document):
    return _result(client().post(f"/api/timeline/{timeline_id}", json={"raw": json_document}))


def export_timeline(timeline_id, format="png"):
    if format == "cards":
        return _saved(client().get(f"/export/timeline/{timeline_id}/cards.zip"), f"{timeline_id}_cards.zip")
    return _saved(client().get(f"/export/timeline/{timeline_id}.{format}"), f"{timeline_id}.{format}")


def _schema(required=(), **props):
    return {"type": "object", "properties": props, "required": list(required)}


_S, _I, _B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}

TOOLS = {
    "guide": (guide, "Format rules for Anki cards (kind=cards) or timeline JSON (kind=timeline). Read before generating.",
              _schema(["kind"], kind={"type": "string", "enum": ["cards", "timeline"]})),
    "list_projects": (list_projects, "List Ankigen course projects with their progress.", _schema()),
    "import_docx": (import_docx, "Import a .docx course from an absolute path; returns the new project_id.",
                    _schema(["path"], path=_S, deck_prefix=_S)),
    "get_paragraphs": (get_paragraphs, "Paragraphs of a project (id, deck, prompt text, status, saved cards).",
                       _schema(["project_id"], project_id=_S, only_pending=_B)),
    "save_cards": (save_cards, "Save the cards of one paragraph as TSV lines (question<TAB>answer). Empty tsv resets it.",
                   _schema(["project_id", "paragraph_id", "tsv"], project_id=_S, paragraph_id=_I, tsv=_S)),
    "export_project": (export_project, "Export a project's cards for Anki; returns the file path.",
                       _schema(["project_id"], project_id=_S, format={"type": "string", "enum": ["zip", "tsv"]})),
    "list_timelines": (list_timelines, "List saved timelines.", _schema()),
    "create_timeline": (create_timeline, "Create a timeline from a JSON document (timeline-v1). Returns its id or a validation report.",
                        _schema(["json_document"], json_document=_S)),
    "update_timeline": (update_timeline, "Replace a timeline's document with corrected JSON; returns the validation report.",
                        _schema(["timeline_id", "json_document"], timeline_id=_S, json_document=_S)),
    "export_timeline": (export_timeline, "Export a timeline as an image/PDF/SVG/JSON, or its Anki cards (format=cards).",
                        _schema(["timeline_id"], timeline_id=_S,
                                format={"type": "string", "enum": ["png", "jpeg", "webp", "pdf", "svg", "json", "cards"]})),
}


# ── Protocole ──────────────────────────────────────────────────

def handle(message):
    """Un message JSON-RPC → la réponse à renvoyer, ou None pour une notification."""
    method, params, mid = message.get("method"), message.get("params") or {}, message.get("id")
    if mid is None:
        return None
    if method == "initialize":
        # Pas `from launcher import read_version` : importer launcher relancerait son bootstrap.
        try:
            version = json.loads((paths.APP_DIR / "version.json").read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            version = "dev"
        result = {"protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "ankigen", "version": version},
                  "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": name, "description": desc, "inputSchema": schema}
                            for name, (_, desc, schema) in TOOLS.items()]}
    elif method == "tools/call":
        tool = TOOLS.get(params.get("name"))
        if tool is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool {params.get('name')}"}}
        try:
            text, is_error = tool[0](**(params.get("arguments") or {}))
        except Exception as e:   # noqa: BLE001 — l'erreur va à Claude, le serveur reste debout
            text, is_error = f"{type(e).__name__}: {e}", True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin, stdout):
    """Boucle stdio. `stdout` est le vrai canal : launcher redirige print() vers stderr."""
    for line in stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
    return 0
