"""Loopback desktop backend. Keep module imports safe before freeze_support."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def write_startup(path: Path, payload: dict[str, Any]) -> None:
    """Publish only complete, private readiness/error metadata; never the token."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def bind_loopback() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        return listener
    except BaseException:
        listener.close()
        raise


def _ready(
    server: Any,
    origin: str,
    token: str,
    startup_file: Path,
    version: str,
    stopped: threading.Event,
    log: Any,
    *,
    timeout: float = 90,
) -> None:
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while not stopped.is_set() and not server.should_exit:
        if time.monotonic() >= deadline:
            server.should_exit = True
            log.event("readiness_failed", category="timeout")
            try:
                write_startup(
                    startup_file, {"status": "error", "pid": os.getpid(), "code": "timeout"}
                )
            except OSError:
                pass
            return
        if server.started:
            request = urllib.request.Request(
                f"{origin}/api/health", headers={"X-Desktop-Token": token}
            )
            try:
                with opener.open(request, timeout=1) as response:
                    health = json.load(response)
            except (OSError, ValueError, urllib.error.URLError):
                stopped.wait(0.05)
                continue
            if isinstance(health, dict) and health.get("status") == "ok":
                try:
                    write_startup(
                        startup_file,
                        {
                            "status": "ready",
                            "pid": os.getpid(),
                            "host": "127.0.0.1",
                            "port": int(origin.rsplit(":", 1)[1]),
                            "origin": origin,
                            "version": version,
                        },
                    )
                    log.event("ready")
                    return
                except OSError:
                    server.should_exit = True
                    log.event("readiness_failed", category="storage")
                    return
        stopped.wait(0.05)


def _watch_parent(server: Any, parent_pid: int, stopped: threading.Event, log: Any) -> None:
    while not stopped.wait(0.25):
        try:
            if os.name == "posix" and os.getppid() != parent_pid:
                raise ProcessLookupError
            if os.name != "posix":
                os.kill(parent_pid, 0)
        except ProcessLookupError:
            server.should_exit = True
            log.event("parent_exited")
            return
        except PermissionError:
            # A live process with different credentials is still a live parent.
            pass


def main(
    argv: list[str] | None = None,
    *,
    create_app_factory: Any = None,
    provider_factory: Any = None,
) -> int:
    """Injectable factories are a programmatic test seam, never CLI/environment."""
    parser = argparse.ArgumentParser(description="Private Anki Generator desktop backend")
    parser.add_argument("--data-directory", type=Path)
    parser.add_argument("--state-directory", type=Path)
    parser.add_argument("--startup-file", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int)
    arguments = parser.parse_args(argv)
    startup_file = arguments.startup_file.resolve()
    # Electron must never mistake a previous process's metadata for readiness.
    try:
        startup_file.unlink(missing_ok=True)
    except OSError:
        print("Desktop backend startup failed: storage", file=sys.stderr)
        return 1
    token = os.environ.pop("ANKI_GENERATOR_DESKTOP_TOKEN", "")
    if (
        not 32 <= len(token) <= 256
        or not token.isascii()
        or any(character.isspace() for character in token)
        or (arguments.parent_pid is not None and arguments.parent_pid <= 0)
    ):
        write_startup(
            startup_file, {"status": "error", "pid": os.getpid(), "code": "configuration"}
        )
        print("Desktop backend startup failed: configuration", file=sys.stderr)
        return 2

    from anki_generator.desktop.logs import LifecycleLog
    from anki_generator.desktop.paths import resolve_paths

    listener = None
    log = None
    monitors: list[threading.Thread] = []
    stopped = threading.Event()
    category = "storage"
    try:
        paths = resolve_paths(arguments.data_directory, arguments.state_directory)
        log = LifecycleLog(paths.state)
        log.event("starting")
        if getattr(sys, "frozen", False):
            category = "resources"
            frontend = Path(__file__).resolve().parents[1] / "web_assets"
            if not (frontend / "index.html").is_file() or not any(
                (frontend / "assets").glob("*.js")
            ):
                raise FileNotFoundError("Bundled frontend resources are missing")
        category = "database"
        if create_app_factory is None:
            from anki_generator.api.app import create_app

            create_app_factory = create_app
        application = create_app_factory(
            paths.data,
            provider_factory=provider_factory,
            desktop_token=token,
            desktop_state_directory=paths.state,
        )
        category = "bind"
        listener = bind_loopback()
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        import uvicorn

        config = uvicorn.Config(
            application,
            host="127.0.0.1",
            port=0,
            access_log=False,
            log_level="warning",
            log_config={
                "version": 1,
                "disable_existing_loggers": False,
                "filters": {"safe": {"()": "anki_generator.desktop.logs.SafeServerFilter"}},
                "handlers": {
                    "safe": {
                        "class": "logging.StreamHandler",
                        "stream": "ext://sys.stderr",
                        "filters": ["safe"],
                    }
                },
                "loggers": {
                    "uvicorn": {"handlers": ["safe"], "level": "WARNING", "propagate": False},
                    "uvicorn.error": {"handlers": ["safe"], "level": "WARNING", "propagate": False},
                },
            },
            timeout_graceful_shutdown=15,
        )
        server = uvicorn.Server(config)
        category = "runtime"
        readiness = threading.Thread(
            target=_ready,
            args=(server, origin, token, startup_file, application.version, stopped, log),
            name="desktop-readiness",
            daemon=True,
        )
        readiness.start()
        monitors.append(readiness)
        if arguments.parent_pid:
            parent_monitor = threading.Thread(
                target=_watch_parent,
                args=(server, arguments.parent_pid, stopped, log),
                name="desktop-parent-monitor",
                daemon=True,
            )
            parent_monitor.start()
            monitors.append(parent_monitor)
        server.run(sockets=[listener])
        if not server.started:
            write_startup(startup_file, {"status": "error", "pid": os.getpid(), "code": "runtime"})
        return 0 if server.started else 1
    except Exception:
        if log:
            log.event("startup_failed", category=category)
        write_startup(startup_file, {"status": "error", "pid": os.getpid(), "code": category})
        # Raw exceptions can contain source paths, credentials or database values.
        print(f"Desktop backend startup failed: {category}", file=sys.stderr)
        return 1
    finally:
        stopped.set()
        for monitor in monitors:
            monitor.join(timeout=2)
        if listener:
            listener.close()
        if log:
            log.event("stopped")
            log.close()
