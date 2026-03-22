# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the `ingest` CLI binary."""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

# Packages that need their data files and binaries collected.
# Torch is handled separately to exclude unused distributed/quantization modules.
collected = {}
for pkg in [
    "sentence_transformers",
    "transformers",
    "tokenizers",
    "chromadb",
    "docling",
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

# Torch: collect data files and binaries, then strip the fat.
# collect_all("torch") includes torch.distributed, CUDA kernels, quantization
# libs etc. that add >2GB and blow past PyInstaller's 4GB --onefile limit.
torch_datas, torch_binaries, _ = collect_all("torch")

# Filter out massive libraries we don't need
_torch_exclude_patterns = [
    # Training / distributed
    "distributed",
    "nccl",
    # Compilation stack
    "inductor",
    "_dynamo",
    "compiler",
    "functorch",
    "nvfuser",
    "triton",
    "export",
    "fx/",
    # Quantization / profiling / testing
    "ao/",
    "testing",
    "profiler",
    "tensorboard",
    "bottleneck",
    "benchmark",
    # Legacy / interop
    "onnx",
    "caffe2",
    # CUDA shared libraries (>2GB on Linux, not needed for CPU/MPS inference)
    "libtorch_cuda",
    "libc10_cuda",
    "libcudnn",
    "libcublas",
    "libcufft",
    "libcurand",
    "libcusparse",
    "libcusolver",
    "libnvrtc",
    "libnvjitlink",
    "libnvfuser",
    "libnccl",
    "cuda_runtime",
    "nvidia/",
]

def _torch_keep(entry):
    """Return True if this binary/data entry should be kept."""
    path = entry[0] if isinstance(entry, tuple) else str(entry)
    path_lower = path.lower().replace("\\", "/")
    return not any(pat in path_lower for pat in _torch_exclude_patterns)

torch_binaries = [b for b in torch_binaries if _torch_keep(b)]
torch_datas = [d for d in torch_datas if _torch_keep(d)]

collected["datas"].extend(torch_datas)
collected["binaries"].extend(torch_binaries)

# Only the torch submodules we actually need
torch_hidden = [
    "torch",
    "torch.nn",
    "torch.nn.functional",
    "torch.utils",
    "torch.utils.data",
    "torch.autograd",
    "torch.cuda",
    "torch.backends",
    "torch.backends.mps",
    "torch.backends.cudnn",
]

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
    hiddenimports=collected.get("hiddenimports", []) + extra_hidden + torch_hidden,
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
        # Torch submodules we don't need (distributed training, quantization, profiling)
        "torch.distributed",
        "torch.ao",
        "torch.testing",
        "torch.utils.tensorboard",
        "torch.utils.bottleneck",
        "torch.utils.benchmark",
        "torch.profiler",
        "torch.onnx",
        "torch.jit",
        "torch.fx",
        "torch.export",
        "torch.compiler",
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
