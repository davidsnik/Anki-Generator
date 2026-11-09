"""Copy the successful production frontend build into the Python package."""

import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
source = root / "frontend/dist"
destination = root / "src/anki_generator/web_assets"
if not (source / "index.html").is_file():
    raise SystemExit("Frontend build did not produce index.html")
if destination.is_symlink():
    raise SystemExit("Refusing to replace a symlink at the packaged web-assets path")
if destination.exists():
    shutil.rmtree(destination)
shutil.copytree(source, destination)
