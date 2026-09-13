# -*- mode: python ; coding: utf-8 -*-

# version.json est généré ici, depuis tauri.conf.json, au lieu d'embarquer le
# fichier de la racine : celui-ci est gitignoré et dérive silencieusement (il est
# resté à 1.0.0 pendant que l'app passait en 1.2.0, si bien que l'application
# packagée annonçait une version fausse et que l'updater se croyait en retard).
# Le workflow de release fait l'équivalent pour app.zip à partir du tag.
import json as _json
from pathlib import Path as _Path

_conf = _json.loads(_Path("src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
_version = _conf["version"]
_Path("version.json").write_text(
    _json.dumps({"version": _version}, indent=2) + "\n", encoding="utf-8"
)
print(f"[spec] version.json généré : {_version}")



a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app.py', 'app_bundle'),
        ('launcher.py', 'app_bundle'),
        ('parse_cours.py', 'app_bundle'),
        ('build_anki_csv.py', 'app_bundle'),
        ('docx_blocks.py', 'app_bundle'),
        ('media_store.py', 'app_bundle'),
        ('render.py', 'app_bundle'),
        ('paths.py', 'app_bundle'),
        ('project_store.py', 'app_bundle'),
        ('updater.py', 'app_bundle'),
        ('settings.py', 'app_bundle'),
        ('i18n.py', 'app_bundle'),
        ('version.json', 'app_bundle'),
        ('templates', 'app_bundle/templates'),
        ('static', 'app_bundle/static'),
        ('locales', 'app_bundle/locales'),
        ('skill_templates', 'app_bundle/skill_templates'),
    ],
    hiddenimports=[
        'waitress', 'flask', 'jinja2.ext', 'docx', 'lxml', 'lxml._elementpath', 'lxml.etree',
        # Conversion / redimensionnement des images extraites du .docx
        'PIL', 'PIL._imaging', 'PIL.Image', 'PIL.PngImagePlugin', 'PIL.JpegImagePlugin',
        'PIL.BmpImagePlugin', 'PIL.TiffImagePlugin', 'PIL.WmfImagePlugin',
    ],
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
