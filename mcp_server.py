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
    "Cards: import_docx (optional deck_prefix; change it later with set_deck_prefix) → get_paragraphs "
    "→ save_cards per paragraph → push_to_anki (straight into the running Anki, only the paragraphs "
    "you name: use it to update a deck without duplicates) or export_project (.zip to import by hand). "
    "To write each paragraph's cards, use the `anki-flashcard-apprentissage` skill when your client has it "
    "(its Recto<TAB>Verso output and {{IMG:n}}/{{TABLE:n}} markers are what save_cards expects; "
    "its CSS classes need the 'ESH Basic' note type in Anki); otherwise follow `guide`. "
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


def import_docx(path, deck_prefix=None):
    source = Path(path)
    if source.suffix.lower() != ".docx" or not source.is_file():
        return f"Not a readable .docx file: {path}", True
    if deck_prefix is None:   # comme le formulaire d'import : préfixe des réglages par défaut
        from settings import load_settings
        deck_prefix = load_settings()["deck_prefix"]
    with source.open("rb") as handle:
        resp = client().post("/upload", data={"docx": (handle, source.name), "deck_prefix": deck_prefix},
                             content_type="multipart/form-data")
    if resp.status_code == 302:   # succès : redirection vers /work/<id>
        return json.dumps({"ok": True, "project_id": unquote(resp.headers["Location"].rsplit("/", 1)[-1])}), False
    return f"Import failed (HTTP {resp.status_code})", True


def set_deck_prefix(project_id, deck_prefix):
    """Remplace le préfixe en tête du deck de chaque paragraphe (« ESH::CH1::I » → « Éco::CH1::I »)."""
    from project_store import load_project, save_project
    from timeline_prompt import deck_segments
    project = load_project(project_id)
    if not project:
        return f"Unknown project: {project_id}", True
    old, new = deck_segments(project.get("deck_prefix")), deck_segments(deck_prefix)
    for p in project["prompts"]:
        segments = deck_segments(p.get("deck"))
        if segments[:len(old)] == old:
            segments = segments[len(old):]
        p["deck"] = "::".join(new + segments)
    project["deck_prefix"] = "::".join(new)
    save_project(project_id, project)
    decks = sorted({p["deck"] for p in project["prompts"]})
    return json.dumps({"ok": True, "deck_prefix": project["deck_prefix"], "decks": decks}, ensure_ascii=False), False


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


ANKICONNECT_URL = "http://127.0.0.1:8765"


def anki(action, **params):
    """Un appel AnkiConnect (module complémentaire 2055492159, Anki ouvert)."""
    import urllib.request
    request = urllib.request.Request(ANKICONNECT_URL, json.dumps(
        {"action": action, "version": 6, "params": params}).encode("utf-8"))
    with urllib.request.urlopen(request, timeout=30) as resp:
        body = json.loads(resp.read())
    if body.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {body['error']}")
    return body["result"]


def push_to_anki(project_id, paragraph_ids, tags=None, note_type="ESH Basic"):
    """
    Envoie dans Anki (via AnkiConnect) les cartes des seuls paragraphes indiqués, avec leurs
    images, dans leurs sous-decks. Les cartes déjà présentes (même recto, même deck) sont
    sautées : renvoyer un paragraphe n'ajoute que ses cartes nouvelles ou modifiées.
    """
    from project_store import export_rows, load_project
    from paths import project_media_dir
    project = load_project(project_id)
    if not project:
        return f"Unknown project: {project_id}", True
    wanted = {int(i) for i in paragraph_ids}
    chosen = [p for p in project["prompts"] if p["id"] in wanted]
    if missing := sorted(wanted - {p["id"] for p in chosen}):
        return f"Unknown paragraph id(s): {missing}", True
    rows, report = export_rows({**project, "prompts": chosen}, with_tags=True)
    if not rows:
        return "No cards saved for these paragraphs.", True

    try:
        fields = anki("modelFieldNames", modelName=note_type)
    except OSError:
        return "Anki is not reachable: open Anki with the AnkiConnect add-on (code 2055492159).", True
    if len(fields) < 2:
        return f"Note type {note_type!r} not found in Anki (or has fewer than 2 fields).", True

    media_dir = project_media_dir(project_id)
    for name in report["media"]:   # noms = SHA-1 du contenu : réécrire le même fichier est sans risque
        if (media_dir / name).is_file():
            anki("storeMediaFile", filename=name, path=str((media_dir / name).resolve()))
    for deck in sorted({row[0] for row in rows}):
        anki("createDeck", deck=deck)

    notes = [{"deckName": deck, "modelName": note_type,
              "fields": {fields[0]: q, fields[1]: a},
              "tags": tag_line.split() + list(tags or []),
              "options": {"allowDuplicate": False, "duplicateScope": "deck"}}
             for deck, q, a, tag_line in rows]
    addable = anki("canAddNotes", notes=notes)
    new = [n for n, ok in zip(notes, addable) if ok]
    added = anki("addNotes", notes=new) if new else []
    return json.dumps({"ok": True, "added": sum(1 for i in added if i), "skipped_duplicates": len(notes) - len(new),
                       "decks": sorted({row[0] for row in rows}), "images": len(report["media"]),
                       "unknown_placeholders": report["unknown_placeholders"]}, ensure_ascii=False), False


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
    "import_docx": (import_docx, "Import a .docx course from an absolute path; returns the new project_id. "
                                 "deck_prefix defaults to the app's setting; pass \"\" for none.",
                    _schema(["path"], path=_S, deck_prefix=_S)),
    "set_deck_prefix": (set_deck_prefix, "Change the deck prefix of an imported project (\"\" removes it); "
                                         "rewrites every paragraph's deck and returns the new deck list.",
                        _schema(["project_id", "deck_prefix"], project_id=_S, deck_prefix=_S)),
    "get_paragraphs": (get_paragraphs, "Paragraphs of a project (id, deck, prompt text, status, saved cards).",
                       _schema(["project_id"], project_id=_S, only_pending=_B)),
    "save_cards": (save_cards, "Save the cards of one paragraph as TSV lines (question<TAB>answer[<TAB>tags]); "
                               "the optional 3rd column holds space-separated Anki tags (e.g. the level). "
                               "Empty tsv resets it.",
                   _schema(["project_id", "paragraph_id", "tsv"], project_id=_S, paragraph_id=_I, tsv=_S)),
    "push_to_anki": (push_to_anki, "Send the saved cards of the given paragraphs straight into the running Anki "
                                   "(AnkiConnect add-on), with their images, into their sub-decks. Cards already "
                                   "in the deck are skipped. tags are added to every card, after each card's own tags.",
                     _schema(["project_id", "paragraph_ids"], project_id=_S,
                             paragraph_ids={"type": "array", "items": _I},
                             tags={"type": "array", "items": _S}, note_type=_S)),
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
