#!/usr/bin/env python3
"""
project_store.py — Lecture / écriture / export des projets Anki-Gen.

Format v2 (objet) :
{
  "version": 2,
  "deck_prefix": "Economics",
  "source": "CH8_ La croissance économique.docx",
  "assets": {"img_1": {...}},
  "prompts": [{"id", "deck", "blocks", "assets", "prompt",
               "status", "response"}]
}

Les projets créés avant l'ouverture au public portent un champ `system` (l'ancien
prompt ESH embarqué). Il est conservé tel quel sur disque et simplement ignoré :
le flux repose désormais sur un Skill Claude côté utilisateur, décrit dans /help.

Les projets v1 (simple liste de prompts, sans médias) sont migrés à la volée :
chaque prompt devient un bloc texte unique. Ils restent donc ouvrables.
"""

import json
import shutil
from pathlib import Path
from urllib.parse import quote

from build_anki_csv import parse_tsv_response
from i18n import DEFAULT_LANG
from paths import MEDIA_DIR, PROJECTS_DIR, project_media_dir
from render import render_preview_html, render_prompt_text, resolve_placeholders

PROJECT_VERSION = 2

# Nom de deck de dernier recours pour une ligne TSV : Anki refuse un champ deck
# vide. Ce n'est pas de la copie d'interface mais un identifiant de deck, donc il
# n'est pas traduit — sinon un même projet exporté dans deux langues créerait
# deux decks différents dans Anki.
DEFAULT_DECK_NAME = "Ankigen"


# ──────────────────────────────────────────────────────────────
# Chemins
# ──────────────────────────────────────────────────────────────
def project_path(project_id: str) -> Path:
    return PROJECTS_DIR / f"{project_id}.json"


def media_url_prefix(project_id: str) -> str:
    """URL de base des médias du projet (les ids contiennent souvent des espaces)."""
    return "/media/" + quote(project_id, safe="")


# ──────────────────────────────────────────────────────────────
# Normalisation / migration
# ──────────────────────────────────────────────────────────────
def normalize(data) -> dict:
    """Ramène n'importe quel format de projet connu au format v2."""
    if isinstance(data, list):          # v1 : liste de prompts
        project = {
            "version": PROJECT_VERSION,
            "deck_prefix": (data[0].get("deck", "").split("::")[0] if data else ""),
            "source": None,
            "assets": {},
            "prompts": data,
            "migrated_from": 1,
        }
    else:
        project = dict(data)
        project.setdefault("version", PROJECT_VERSION)
        project.setdefault("assets", {})
        project.setdefault("prompts", [])
        project.setdefault("deck_prefix", "")
        project.setdefault("source", None)

    for prompt in project["prompts"]:
        if not prompt.get("blocks"):
            # v1 : le prompt était du texte brut → un unique bloc texte
            prompt["blocks"] = (
                [{"type": "text", "text": prompt.get("prompt", "")}]
                if prompt.get("prompt") else []
            )
        prompt.setdefault("assets", [])
        prompt.setdefault("status", "pending")
        prompt.setdefault("response", "")
    project["version"] = PROJECT_VERSION
    return project


def load_project_file(path: Path):
    path = Path(path)
    if not path.exists():
        return None
    return normalize(json.loads(path.read_text(encoding="utf-8")))


def save_project_file(path: Path, project: dict) -> None:
    Path(path).write_text(
        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_project(project_id: str):
    return load_project_file(project_path(project_id))


def save_project(project_id: str, project: dict) -> None:
    save_project_file(project_path(project_id), project)


def delete_project(project_id: str) -> None:
    path = project_path(project_id)
    if path.exists():
        path.unlink()
    media = MEDIA_DIR / project_id
    if media.is_dir():
        shutil.rmtree(media, ignore_errors=True)


def list_projects() -> list:
    out = []
    for file in sorted(PROJECTS_DIR.glob("*.json")):
        project = load_project_file(file)
        if not project or not project["prompts"]:
            continue
        images, tables = count_media(project)
        out.append({
            "id": file.stem,
            "progress": progress(project),
            "deck": project["prompts"][0].get("deck") or project.get("deck_prefix") or "",
            "source": project.get("source"),
            "images": images,
            "tables": tables,
        })
    return out


# ──────────────────────────────────────────────────────────────
# Statistiques
# ──────────────────────────────────────────────────────────────
def progress(project: dict) -> dict:
    prompts = project.get("prompts", [])
    total = len(prompts)
    done = sum(1 for p in prompts if p.get("status") == "done")
    return {"total": total, "done": done, "pending": total - done}


def count_media(project: dict):
    """(images, tableaux) — les images logées dans une cellule comptent aussi."""
    images = len({
        aid for p in project.get("prompts", []) for aid in p.get("assets", [])
    })
    tables = sum(
        1 for p in project.get("prompts", [])
        for b in p.get("blocks", []) if b.get("type") == "table"
    )
    return images, tables


def missing_alt_count(project: dict) -> int:
    """Nombre d'images sans description : ce qui manquera à Claude dans le prompt."""
    assets = project.get("assets", {})
    used = {aid for p in project.get("prompts", []) for aid in p.get("assets", [])}
    return sum(
        1 for aid in used
        if aid in assets and not (assets[aid].get("alt") or "").strip()
        and not assets[aid].get("missing")
    )


# ──────────────────────────────────────────────────────────────
# Vue pour l'interface
# ──────────────────────────────────────────────────────────────
def prompt_view(project: dict, project_id: str, prompt: dict) -> dict:
    """Prompt enrichi pour l'UI : aperçu HTML + assets détaillés."""
    assets = project.get("assets", {})
    prefix = media_url_prefix(project_id)
    blocks = prompt.get("blocks", [])
    asset_list = []
    seen = set()

    def add_asset(aid, n=None, in_table=None):
        if not aid or aid in seen:
            return
        seen.add(aid)
        asset = dict(assets.get(aid) or {})
        asset["n"] = n
        asset["in_table"] = in_table
        if asset.get("file"):
            asset["url"] = f"{prefix}/{asset['file']}"
        asset_list.append(asset)

    for block in blocks:
        if block.get("type") == "image":
            add_asset(block.get("asset"), n=block.get("n", 1))
        elif block.get("type") == "table":
            # Une image logée dans une cellule n'a pas de {{IMG:n}} propre, mais sa
            # description compte autant : elle doit rester éditable.
            for aid in block.get("assets", []):
                add_asset(aid, in_table=block.get("n", 1))

    return {
        "id": prompt["id"],
        "deck": prompt.get("deck", ""),
        "prompt": prompt.get("prompt", ""),
        "status": prompt.get("status", "pending"),
        "response": prompt.get("response", ""),
        "preview_html": render_preview_html(blocks, assets, prefix),
        "images": asset_list,
        "tables": [
            {"n": b.get("n", 1), "rows": len(b.get("rows", [])), "cols": b.get("n_cols", 0)}
            for b in blocks if b.get("type") == "table"
        ],
    }


def project_view(project: dict, project_id: str) -> list:
    return [prompt_view(project, project_id, p) for p in project.get("prompts", [])]


# ──────────────────────────────────────────────────────────────
# Édition du texte alternatif
# ──────────────────────────────────────────────────────────────
def set_asset_alt(project: dict, asset_id: str, alt: str,
                  lang: str = DEFAULT_LANG) -> list:
    """
    Met à jour le texte alternatif d'une image et re-rend les prompts concernés
    (le texte envoyé à Claude contient la description : elle doit suivre).
    Retourne les ids des prompts modifiés.
    """
    assets = project.get("assets", {})
    if asset_id not in assets:
        raise KeyError(asset_id)

    alt = (alt or "").strip()
    assets[asset_id]["alt"] = alt
    assets[asset_id]["alt_source"] = "manual" if alt else None

    touched = []
    for prompt in project.get("prompts", []):
        uses = any(
            (b.get("type") == "image" and b.get("asset") == asset_id)
            or (b.get("type") == "table" and asset_id in b.get("assets", []))
            for b in prompt.get("blocks", [])
        )
        if uses:
            prompt["prompt"] = render_prompt_text(prompt["blocks"], assets, lang)
            touched.append(prompt["id"])
    return touched


# ──────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────
def export_rows(project: dict, only_done: bool = False, media_prefix: str = ""):
    """
    Construit les lignes (deck, recto, verso) prêtes pour Anki, placeholders
    {{IMG:n}} / {{TABLE:n}} résolus.

    Retourne (rows, report) avec report = {
        "cards", "skipped", "media" (noms de fichiers utilisés),
        "unknown_placeholders", "unused_assets"
    }
    """
    assets = project.get("assets", {})
    rows = []
    used_asset_ids = set()
    unknown = []
    skipped = 0

    for prompt in project.get("prompts", []):
        response = (prompt.get("response") or "").strip()
        if not response:
            skipped += 1
            continue
        if only_done and prompt.get("status") != "done":
            skipped += 1
            continue

        deck = prompt.get("deck") or project.get("deck_prefix") or DEFAULT_DECK_NAME
        for question, answer in parse_tsv_response(response):
            q, used_q, unk_q = resolve_placeholders(question, prompt, assets, media_prefix)
            a, used_a, unk_a = resolve_placeholders(answer, prompt, assets, media_prefix)
            used_asset_ids |= used_q | used_a
            unknown.extend(f"#{prompt['id']} {u}" for u in unk_q + unk_a)
            rows.append([deck, q, a])

    media_files = sorted(
        assets[aid]["file"] for aid in used_asset_ids
        if aid in assets and assets[aid].get("file")
    )
    referenced = {
        aid for p in project.get("prompts", []) for aid in p.get("assets", [])
    }
    unused = sorted(
        aid for aid in referenced
        if aid and aid not in used_asset_ids and aid in assets
        and not assets[aid].get("missing")
    )

    return rows, {
        "cards": len(rows),
        "skipped": skipped,
        "media": media_files,
        "unknown_placeholders": unknown,
        "unused_assets": unused,
    }


def copy_media(project_id: str, filenames, destination: Path) -> dict:
    """
    Copie les images utilisées vers `destination` (dossier d'export ou
    collection.media d'Anki).

    Un fichier déjà présent avec un contenu identique est laissé tel quel (les
    noms embarquent le SHA-1, c'est le cas normal d'un réimport). Un fichier de
    même nom mais de contenu DIFFÉRENT n'est ni écrasé ni renommé : les cartes
    référencent le nom d'origine, un renommage afficherait silencieusement la
    mauvaise image. Le conflit est signalé à l'utilisateur.
    """
    src_dir = project_media_dir(project_id)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    copied, identical, conflicts, missing = [], [], [], []
    for name in filenames:
        src = src_dir / name
        if not src.exists():
            missing.append(name)
            continue
        dst = destination / name
        if dst.exists():
            if dst.stat().st_size == src.stat().st_size and dst.read_bytes() == src.read_bytes():
                identical.append(name)
            else:
                conflicts.append(name)
            continue
        shutil.copy2(src, dst)
        copied.append(name)

    return {
        "copied": copied,
        "identical": identical,
        "conflicts": conflicts,
        "missing": missing,
        "destination": str(destination),
    }
