# -*- mode: python ; coding: utf-8 -*-
#
# Builds the FastAPI sidecar bundle used by the Tauri desktop app.
# `pyinstaller cik-api.spec` from the phd_aggregator/ directory.
#
# datas: config.yaml + fields/*.yaml + seeds.txt are extracted next to the
# modules inside the onefile (_MEIPASS), where core.config._script_dir()
# looks for them. Without these the packaged API serves only the built-in
# default profile and every field filter returns nothing.

import glob
import os

datas = []
for src in ("config.yaml", "seeds.txt"):
    p = os.path.join(SPECPATH, src)
    if os.path.isfile(p):
        datas.append((p, "."))
field_files = glob.glob(os.path.join(SPECPATH, "fields", "*.yaml"))
for p in field_files:
    datas.append((p, "fields"))

# CV parsers are imported LAZILY inside core.cv (so a missing one degrades
# instead of breaking startup), which means PyInstaller's static analysis
# cannot see them. Without naming them here the packaged desktop app ships
# with no PDF/DOCX support at all — the very "PDF support needs a parser"
# failure this project already hit once. Listed as optional: a build on a
# machine that lacks one still succeeds, it just cannot read that format.
CV_PARSERS = ["pdfplumber", "pdfminer", "pdfminer.high_level", "docx"]
hiddenimports = []
for module in CV_PARSERS:
    try:
        __import__(module)
    except ImportError:
        print(f"[cik-api.spec] WARNING: {module} is not installed — the "
              f"bundled app will not be able to read that CV format. "
              f"Install requirements.txt before building.")
    else:
        hiddenimports.append(module)


a = Analysis(
    ['api/run.py'],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='cik-api',
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
