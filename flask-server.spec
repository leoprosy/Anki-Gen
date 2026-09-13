# -*- mode: python ; coding: utf-8 -*-


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
