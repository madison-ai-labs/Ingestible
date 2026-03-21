# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the `ingest` CLI binary."""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Heavy packages that need full collection (data files, binaries, submodules)
collected = {}
for pkg in [
    "sentence_transformers",
    "transformers",
    "tokenizers",
    "chromadb",
    "docling",
    "torch",
    "tqdm",
    "pydantic",
    "tiktoken",
    "httpx",
    "httpcore",
    "anyio",
    "certifi",
]:
    datas, binaries, hiddenimports = collect_all(pkg)
    collected.setdefault("datas", []).extend(datas)
    collected.setdefault("binaries", []).extend(binaries)
    collected.setdefault("hiddenimports", []).extend(hiddenimports)

# Additional hidden imports that PyInstaller misses
extra_hidden = [
    *collect_submodules("ingestible"),
    *collect_submodules("uvicorn"),
    *collect_submodules("fastapi"),
    *collect_submodules("starlette"),
    *collect_submodules("pymupdf4llm"),
    *collect_submodules("markdownify"),
    *collect_submodules("ebooklib"),
    *collect_submodules("openpyxl"),
    *collect_submodules("pptx"),
    *collect_submodules("docutils"),
    *collect_submodules("rank_bm25"),
    *collect_submodules("numpy"),
    *collect_submodules("structlog"),
    "anthropic",
    "openai",
    "portalocker",
    "slowapi",
    "gunicorn",
    "prometheus_fastapi_instrumentator",
    "aiofiles",
    "jinja2",
    "multipart",
    "dotenv",
]

a = Analysis(
    ["src/ingestible/cli.py"],
    pathex=["src"],
    binaries=collected.get("binaries", []),
    datas=collected.get("datas", []),
    hiddenimports=collected.get("hiddenimports", []) + extra_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused backends to reduce size
        "tkinter",
        "matplotlib",
        "PIL",
        "IPython",
        "notebook",
        "scipy",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ingest",
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
