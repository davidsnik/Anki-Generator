# PyInstaller one-folder backend. Build from scripts/build-desktop.sh.
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

root = Path(SPECPATH).resolve().parent

# Migrations execute their Python files from disk; templates/frontend are resources.
datas = collect_data_files(
    "anki_generator",
    includes=["database/migrations/**", "prompts/**", "web_assets/**"],
    include_py_files=True,
)
datas += collect_data_files("certifi")
datas += collect_data_files("docx")
datas += collect_data_files("pptx")
datas += copy_metadata("keyring", recursive=True)
datas += copy_metadata("anki-generator")

# Keyring uses distribution entry points; parsers/workers use delayed imports.
hiddenimports = collect_submodules("anki_generator")
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.pysqlite",
]

analysis = Analysis(
    [str(root / "packaging/desktop_entry.py")],
    pathex=[str(root / "src")],
    binaries=collect_dynamic_libs("pymupdf"),
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "ruff", "tkinter", "IPython", "anki"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="anki-generator-backend",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="anki-generator-backend",
)
