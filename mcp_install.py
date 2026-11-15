#!/usr/bin/env python3
"""
mcp_install.py — Enregistre le serveur MCP d'Ankigen auprès de Claude Desktop et Claude Code.

Seulement en mode packagé : depuis les sources, le README donne la commande
(`ankigen-dev`), et une installation automatique pointerait le profil utilisateur
vers un venv de développement.

Claude Desktop : on fusionne une entrée `mcpServers.ankigen` dans sa config JSON,
sans toucher au reste ; un fichier illisible n'est jamais réécrit. Claude Code :
on passe par sa CLI (`claude mcp add`), seule interface stable pour écrire sa config.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import paths

NAME = "ankigen"
# Globaux de module : les tests les redirigent vers un dossier jetable.
APPDATA = Path(os.environ.get("APPDATA") or Path.home())
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or Path.home())
CLAUDE_CODE_CONFIG = Path.home() / ".claude.json"


def command():
    """La commande que les clients lancent : l'exécutable packagé en mode --mcp."""
    return sys.executable, ["--mcp"]


def desktop_configs():
    """Configs Claude Desktop dont le dossier existe (Claude installé) : classique et Microsoft Store."""
    candidates = [APPDATA / "Claude"]
    candidates += sorted(LOCALAPPDATA.glob("Packages/Claude_*/LocalCache/Roaming/Claude"))
    return [d / "claude_desktop_config.json" for d in candidates if d.is_dir()]


def claude_cli():
    return shutil.which("claude")


def _read_json(path):
    """Contenu du fichier ; {} s'il n'existe pas. ValueError s'il est illisible."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def _registered(path):
    exe, args = command()
    try:
        entry = (_read_json(path).get("mcpServers") or {}).get(NAME) or {}
    except (OSError, ValueError):
        return False
    return entry.get("command") == exe and entry.get("args") == args


def status():
    """
    available : au moins un client détecté (et app packagée).
    installed : chaque client détecté a l'entrée à jour.
    """
    if not paths.is_frozen():
        return {"available": False, "installed": False, "clients": []}
    clients = [("claude_desktop", p) for p in desktop_configs()]
    if claude_cli():
        clients.append(("claude_code", CLAUDE_CODE_CONFIG))
    done = [_registered(p) for _, p in clients]
    return {"available": bool(clients), "installed": bool(clients) and all(done),
            "clients": sorted({name for name, _ in clients})}


def _install_desktop(path):
    data = _read_json(path)            # ValueError → on n'écrase pas un fichier qu'on ne comprend pas
    exe, args = command()
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = data["mcpServers"] = {}
    servers[NAME] = {"command": exe, "args": args}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _install_code(cli):
    exe, args = command()
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    run = lambda *a: subprocess.run([cli, "mcp", *a], capture_output=True, text=True, timeout=60, **flags)
    # `add` refuse un nom existant : on retire d'abord l'ancienne entrée (absente = échec ignoré).
    run("remove", "--scope", "user", NAME)
    result = run("add", "--scope", "user", NAME, "--", exe, *args)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())


def install():
    """Enregistre partout où c'est possible. Retourne {installed: [...], errors: {client: message}}."""
    installed, errors = [], {}
    for path in desktop_configs():
        try:
            _install_desktop(path)
            installed.append("claude_desktop")
        except (OSError, ValueError) as e:
            errors["claude_desktop"] = f"{path}: {e}"
    cli = claude_cli()
    if cli:
        try:
            _install_code(cli)
            installed.append("claude_code")
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            errors["claude_code"] = str(e)
    return {"installed": sorted(set(installed)), "errors": errors}
