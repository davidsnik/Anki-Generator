"""Explicit persistent desktop paths independent of the installation and cwd."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DesktopPaths:
    data: Path
    state: Path


def _xdg(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    # XDG specifies that relative environment values must be ignored.
    return Path(value) if value and Path(value).is_absolute() else fallback


def resolve_paths(data: Path | None = None, state: Path | None = None) -> DesktopPaths:
    home = Path.home()
    paths = DesktopPaths(
        (data or (_xdg("XDG_DATA_HOME", home / ".local/share") / "anki-generator")).resolve(),
        (state or (_xdg("XDG_STATE_HOME", home / ".local/state") / "anki-generator")).resolve(),
    )
    for directory in (paths.data, paths.state):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    return paths
