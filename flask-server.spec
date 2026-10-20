# -*- mode: python ; coding: utf-8 -*-

# version.json est généré ici, depuis tauri.conf.json, au lieu d'embarquer le
# fichier de la racine : celui-ci est gitignoré et dérive silencieusement (il est
# resté à 1.0.0 pendant que l'app passait en 1.2.0, si bien que l'application
# packagée annonçait une version fausse et que l'updater se croyait en retard).
# Le workflow de release fait l'équivalent pour app.zip à partir du tag.
#
# Le commit est inclus pour la même raison que dans app.zip (voir updater.py /
# is_update_available) : sans lui, un installeur reconstruit sur la même
# version que la dernière release ne serait jamais détecté comme différent.
import json as _json
import os as _os
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, _os.path.join(SPECPATH, "scripts"))
from build_app_payload import build_payload, current_commit, tauri_version  # noqa: E402
from runtime_contract import runtime_import_names, stdlib_modules  # noqa: E402
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules  # noqa: E402

_version = tauri_version()
_commit = current_commit()
# Copie à la racine pour le mode dev (`python app.py` lit la version ici).
_Path("version.json").write_text(
    _json.dumps({"version": _version, "commit": _commit}, indent=2) + "\n", encoding="utf-8"
)
print(f"[spec] version.json généré : {_version} ({_commit[:7] if _commit else 'commit inconnu'})")

# ── Contenu : rien n'est listé à la main ─────────────────────────────────────
# Le code de l'app est embarqué comme données (`app_bundle/`), puis déployé sous
# %APPDATA% et remplaçable par app.zip. Son contenu est calculé par
# scripts/build_app_payload.py à partir des imports réels, exactement comme
# app.zip dans les workflows : les deux livraisons ne peuvent plus diverger.
#
# Comme ce code n'est pas analysé par PyInstaller, l'exécutable embarque TOUTE
# la bibliothèque standard et TOUS les sous-modules des dépendances runtime.
# Un nouvel import dans l'app n'exige donc jamais de nouvel exécutable ; seule
# une nouvelle dépendance le fait, et runtime.json le signale (voir
# scripts/runtime_contract.py).
_bundle_dir = _Path(SPECPATH) / "build" / "app_bundle"
_manifest = build_payload(_bundle_dir, _version, _commit)
print(f"[spec] app_bundle : {len(_manifest['modules'])} modules, runtime {_manifest['requires_runtime']}")


def _is_test_module(name):
    parts = name.split(".")
    return any(part in ("test", "tests", "testing", "conftest") for part in parts[1:])


_hidden = list(stdlib_modules())
for _package in runtime_import_names():
    _hidden += collect_submodules(_package, filter=lambda n: not _is_test_module(n),
                                  on_error="ignore")
print(f"[spec] hiddenimports : {len(_hidden)} modules")

a = Analysis(
    ['launcher.py'],
    pathex=[],
    # llama_cpp charge ses DLL par ctypes depuis llama_cpp/lib : aucune analyse
    # d'import ne les voit, et pyinstaller-hooks-contrib n'a pas de hook pour lui.
    binaries=collect_dynamic_libs("llama_cpp"),
    datas=[
        (str(_bundle_dir), 'app_bundle'),
        # Identité du runtime : lue par launcher --self-check et par l'updater.
        ('runtime.json', '.'),
    ],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='flask-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
