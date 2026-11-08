"""Stable JSON fingerprints and atomic local artifact publication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def entity_data(entity: Any) -> dict[str, Any]:
    return {column.name: getattr(entity, column.name) for column in entity.__table__.columns}
