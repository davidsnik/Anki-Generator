"""Local discovery commands. No content is parsed or sent to an external service."""

from pathlib import Path
from typing import Annotated

import typer

from anki_generator.config import load_settings
from anki_generator.ingestion.discovery import discover_documents
from anki_generator.output import validate_output_directory, write_manifest

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)


@app.callback()
def main() -> None:
    """Build evidence-based Anki flashcards. Phase 0: local file discovery only."""


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
