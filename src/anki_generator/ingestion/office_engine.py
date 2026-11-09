"""Optional faithful Office rendering in a network-disabled, filesystem-isolated engine."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from anki_generator.ingestion.contracts import ExtractionOptions

PROFILE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
</oor:items>"""


def render_office_pdf(
    path: Path, destination: Path, options: ExtractionOptions
) -> tuple[bool, str]:
    """Never fall back to launching an unrestricted Office document process."""
    engine, isolation = shutil.which("libreoffice"), shutil.which("bwrap")
    if not engine or not isolation:
        return False, "Native Office rendering unavailable: LibreOffice and bubblewrap are required"
    with tempfile.TemporaryDirectory(prefix=".office-render-", dir=destination.parent) as temp:
        root = Path(temp)
        profile, output = root / "profile", root / "output"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(PROFILE)
        output.mkdir()
        command = [
            isolation,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--ro-bind",
            "/usr",
            "/usr",
            "--symlink",
            "usr/bin",
            "/bin",
            "--symlink",
            "usr/sbin",
            "/sbin",
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib64",
            "/lib64",
            "--dir",
            "/etc",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/work",
            "--ro-bind",
            str(path.absolute()),
            "/work/input" + path.suffix.lower(),
            "--bind",
            str(output),
            "/work/output",
            "--bind",
            str(profile),
            "/work/profile",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "SAL_USE_VCLPLUGIN",
            "svp",
            "--setenv",
            "LC_ALL",
            "C.UTF-8",
        ]
        if Path("/etc/fonts").is_dir():
            command += ["--ro-bind", "/etc/fonts", "/etc/fonts"]
        if Path("/etc/ld.so.cache").is_file():
            command += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
        command += [
            engine,
            "-env:UserInstallation=file:///work/profile",
            "--headless",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            "/work/output",
            "/work/input" + path.suffix.lower(),
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                process.wait(timeout=options.office_timeout_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return (
                    False,
                    "Office rendering timed out; native extraction retained",
                )
            converted = output / "input.pdf"
            if process.returncode != 0 or not converted.is_file() or converted.stat().st_size == 0:
                return (
                    False,
                    "Isolated Office rendering failed; native extraction remains partial",
                )
            if converted.stat().st_size > options.max_file_bytes:
                return (
                    False,
                    "Office rendering exceeded output-byte limit; native extraction retained",
                )
            converted.replace(destination)
            return True, "LibreOffice (isolated, network disabled, macros disabled)"
        except OSError:
            return False, "Isolated Office rendering could not start; native extraction retained"
