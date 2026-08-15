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

# The per-source URL registry. Without it the packaged app has no per-field
# targeting at all: every board falls back to "no mapping — skipping", so the
# desktop build quietly searches nothing while the dev checkout works fine.
_registry = os.path.join(SPECPATH, "sources", "url_registry.yaml")
if os.path.isfile(_registry):
    datas.append((_registry, "sources"))

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


# SIZE. The desktop bundle was 330 MB, and three optional dependencies were
# most of it. Each is excluded here and each degrades gracefully at runtime —
# verified, not assumed:
#
#   playwright  142 MB  headless-browser fallback for JS/Cloudflare pages.
#                       core.deps sets _HAVE_PLAYWRIGHT=False when absent and
#                       the fetch chain falls back to requests + curl_cffi.
#                       (FindAPhD, its main consumer, is Cloudflare-403 from
#                       most proxy exits anyway.)
#   litellm     111 MB  the LLM profile extractor. Phase 3 replaced it as the
#                       primary path with core.cv_extract (deterministic, no
#                       API key), and core.llm imports it lazily behind a
#                       clear error.
#   pandas +     103 MB only ever used to write CSVs, now done by core.csvout
#   numpy               on the standard library, plus one date-parsing
#                       fallback in core.utils that is already try/excepted.
#
# A user who installs from requirements.txt still gets all three — this only
# trims what is BUNDLED into the downloadable app.
EXCLUDES = [
    "playwright", "litellm",
    "pandas", "numpy", "numpy.f2py",

    # TRANSITIVE PASSENGERS. Excluding a package does not drop the things it
    # dragged into the graph, and these were the real weight — measured from
    # the build, not guessed. NOTHING in this codebase imports any of them.
    "pyarrow",          # 144 MB (!) — a pandas extra, the single biggest item
    "openai",           #   6 MB — litellm's client
    "hf_xet",           #  12 MB — litellm -> huggingface
    "huggingface_hub", "tokenizers", "transformers",
    "aiohttp",          #   6 MB — async HTTP for the above; we use requests/httpx
    "tiktoken", "tiktoken_ext",      # 3 MB — the OpenAI tokenizer
    "regex",                         # 3 MB — only here for tiktoken

    # Not used by the DESKTOP build specifically. A server install still gets
    # these from requirements.txt; the Tauri shell always runs on SQLite.
    "psycopg2", "psycopg2-binary",   # 8 MB — PostgreSQL driver
    "uvloop",                        # 16 MB — uvicorn speed extra; it falls
                                     # back to asyncio, and this serves one user

    # Never reachable from a headless API.
    "matplotlib", "scipy", "IPython", "tkinter", "PyQt5", "PySide6",
    "pytest", "_pytest",
]

a = Analysis(
    ['api/run.py'],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
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
    # Strip debug symbols from the bundled shared objects. Saves tens of MB
    # on Linux/macOS and costs nothing: this is a shipped binary, and a
    # traceback still names the Python frames, which is what we debug from.
    strip=True,
    # UPX compresses further if it is installed; harmless when it is not.
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
