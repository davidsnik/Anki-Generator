"""Launch the graphical application or use deterministic standalone discovery."""

from pathlib import Path
from typing import Annotated

import typer

from anki_generator.config import load_settings
from anki_generator.ingestion.discovery import discover_documents
from anki_generator.output import validate_output_directory, write_manifest

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)


@app.callback()
def main() -> None:
    """Generate evidence-based Anki flashcards from local course material."""


@app.command("inspect")
def inspect_course(
    course_directory: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, readable=True, help="Course input tree.")
    ],
    output: Annotated[Path, typer.Option("--output", "-o", help="Manifest output directory.")],
    config: Annotated[
        Path | None,
        typer.Option("--config", exists=True, dir_okay=False, readable=True, help="Settings TOML."),
    ] = None,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Explicitly replace an existing manifest.json.")
    ] = False,
) -> None:
    """Record file paths, types, sizes and SHA-256 hashes in manifest.json."""
    try:
        settings = load_settings(config)
        output_directory = validate_output_directory(course_directory, output, overwrite=overwrite)
        manifest = discover_documents(
            course_directory, output_directory=output_directory, settings=settings.discovery
        )
        destination = write_manifest(manifest, output_directory, overwrite=overwrite)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Discovered {len(manifest.documents)} supported file(s). Manifest: {destination}")
    typer.echo(
        f"Skipped: {manifest.skipped_unsupported} unsupported/special file(s), "
        f"{manifest.skipped_symlinks} symlink(s), "
        f"{len(manifest.excluded_directories)} excluded directory/ies."
    )
    if not manifest.documents:
        typer.echo("No supported documents found; the manifest is empty.")


@app.command()
def serve(
    data_directory: Annotated[
        Path | None, typer.Option("--data-directory", help="Local application data directory.")
    ] = None,
    host: Annotated[str, typer.Option(help="Loopback address only.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
    open_browser: Annotated[bool, typer.Option("--open-browser/--no-open-browser")] = False,
) -> None:
    """Start the local GUI, HTTP API and persistent processing worker."""
    import threading
    import time
    import urllib.error
    import urllib.request
    import webbrowser

    import uvicorn

    from anki_generator.api.app import create_app

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise typer.BadParameter(
            "The application must bind to a loopback address", param_hint="--host"
        )
    url = f"http://{'[::1]' if host == '::1' else host}:{port}"
    application = create_app(data_directory)
    if open_browser:

        def launch_browser() -> None:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(f"{url}/api/health", timeout=1):
                        webbrowser.open(url)
                        return
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)

        threading.Thread(target=launch_browser, daemon=True).start()
    typer.echo(f"Anki Generator is starting at {url}")
    uvicorn.run(application, host=host, port=port, log_level="warning", access_log=False)
