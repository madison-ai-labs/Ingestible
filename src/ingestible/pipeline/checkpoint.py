"""Pipeline checkpoint/resume — serialize intermediate models between stages."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

STAGE_ORDER: list[str] = [
    "parsed",
    "cleaned",
    "structure",
    "chunks",
    "validated",
    "contextual",
    "enriched",
    "indexed",
]


def _checkpoint_dir(doc_dir: Path) -> Path:
    return doc_dir / ".checkpoint"


def save_checkpoint(doc_dir: Path, stage_name: str, data: BaseModel) -> None:
    """Serialize a Pydantic model to ``{doc_dir}/.checkpoint/{stage_name}.json``."""
    cp_dir = _checkpoint_dir(doc_dir)
    cp_dir.mkdir(parents=True, exist_ok=True)
    dest = cp_dir / f"{stage_name}.json"
    dest.write_text(json.dumps(data.model_dump(), default=str), encoding="utf-8")
    logger.info("Checkpoint saved: %s", stage_name)


def load_checkpoint(doc_dir: Path, stage_name: str) -> dict[str, Any] | None:
    """Return the raw dict for *stage_name*, or ``None`` if not found."""
    cp_file = _checkpoint_dir(doc_dir) / f"{stage_name}.json"
    if not cp_file.exists():
        return None
    try:
        return json.loads(cp_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupt checkpoint %s, ignoring: %s", stage_name, exc)
        return None


def get_latest_checkpoint(doc_dir: Path) -> str | None:
    """Return the stage name of the most-advanced checkpoint, or ``None``."""
    cp_dir = _checkpoint_dir(doc_dir)
    if not cp_dir.exists():
        return None
    existing = {p.stem for p in cp_dir.glob("*.json")}
    latest: str | None = None
    for stage in STAGE_ORDER:
        if stage in existing:
            latest = stage
    return latest


def clear_checkpoints(doc_dir: Path) -> None:
    """Remove the ``.checkpoint/`` directory entirely."""
    cp_dir = _checkpoint_dir(doc_dir)
    if cp_dir.exists():
        shutil.rmtree(cp_dir)
        logger.info("Checkpoints cleared for %s", doc_dir.name)
