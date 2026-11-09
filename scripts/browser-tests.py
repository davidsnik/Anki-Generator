"""Run Playwright with an owned, isolated offline backend on an allocated port."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="anki-browser-tests-") as temporary:
        directory = Path(temporary)
        environment = {
            **os.environ,
            "ANKI_TEST_DATA_DIR": str(directory / "workspace"),
            "OPENAI_API_KEY": "",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        }
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
            environment["ANKI_E2E_BASE_URL"] = origin
            with (directory / "backend.log").open("w+") as log:
                backend = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "tests.browser_app:create_browser_app",
                        "--factory",
                        "--fd",
                        str(listener.fileno()),
                    ],
                    cwd=ROOT,
                    env=environment,
                    pass_fds=(listener.fileno(),),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                listener.close()
                result = 1
                try:
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        if backend.poll() is not None:
                            raise RuntimeError(
                                "The isolated browser test backend stopped at startup"
                            )
                        try:
                            with urllib.request.urlopen(
                                f"{origin}/api/health", timeout=1
                            ) as response:
                                if response.status == 200:
                                    break
                        except (OSError, urllib.error.URLError):
                            time.sleep(0.1)
                    else:
                        raise RuntimeError("The isolated browser test backend did not become ready")
                    print(
                        f"Browser tests use an isolated offline workspace at {origin}", flush=True
                    )
                    result = subprocess.call(
                        [
                            environment.get("PNPM", "pnpm"),
                            "--dir",
                            "frontend",
                            "test:e2e",
                            *sys.argv[1:],
                        ],
                        cwd=ROOT,
                        env=environment,
                    )
                except (OSError, RuntimeError) as error:
                    print(error, file=sys.stderr)
                except KeyboardInterrupt:
                    result = 130
                finally:
                    if backend.poll() is None:
                        backend.terminate()
                        try:
                            backend.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            # This process owns only the disposable test workspace.
                            backend.kill()
                            backend.wait(timeout=5)
                    if result:
                        log.seek(0)
                        print(log.read()[-8000:], file=sys.stderr)
                return result if result >= 0 else 128 - result


if __name__ == "__main__":
    raise SystemExit(main())
