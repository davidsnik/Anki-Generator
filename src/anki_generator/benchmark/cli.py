"""Developer-only inventory, experiments, annotations and reports."""

from __future__ import annotations

import json
import tempfile
from functools import wraps
from pathlib import Path
from typing import Annotated
from uuid import uuid4
from zipfile import ZipFile

import typer
from pydantic import ValidationError

from anki_generator.benchmark.contracts import BenchmarkConfig, DatasetManifest
from anki_generator.benchmark.inventory import inventory_summary, inventory_zip, write_new_json
from anki_generator.benchmark.runner import run_benchmark

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _error_summary(exc: Exception) -> str:
    # Pydantic's default message includes complete offending inputs, potentially secrets.
    if isinstance(exc, ValidationError):
        return f"Invalid benchmark schema ({exc.error_count()} errors); input values withheld"
    return str(exc)


def safe_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, KeyError) as exc:
            message = (
                "Missing required result field"
                if isinstance(exc, KeyError)
                else _error_summary(exc)
            )
            typer.echo(f"Benchmark command failed: {message}", err=True)
            raise typer.Exit(1) from None

    return wrapped


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _result(path: Path, references: Path | None = None) -> dict:
    result = read_json(path)
    if references:
        from anki_generator.benchmark.annotations import ReferenceInventory

        reference = read_json(references)
        if reference.get("dataset_sha256") != result["dataset_sha256"]:
            raise ValueError("Reference inventory belongs to another dataset revision")
        reference = ReferenceInventory.model_validate(reference).model_dump(mode="json")
        if reference["dataset_id"] != result["dataset_id"]:
            raise ValueError("Reference inventory belongs to another dataset")
        source_hashes = {source["id"]: source for source in result.get("source_manifest", [])}
        for concept in reference["concepts"]:
            for source in concept["source_refs"]:
                bound = source_hashes.get(source["source_id"])
                if not bound or bound["sha256"] != source["document_sha256"]:
                    raise ValueError("Reference target source does not match the frozen manifest")
                page_count = bound.get("metadata", {}).get("pages")
                if page_count is not None and source["page_number"] > page_count:
                    raise ValueError("Reference target page lies outside the original source")
        result = {**result, "reference_inventory": reference}
    return result


@app.callback()
def main():
    """Opt-in developer benchmarks; no graphical application or paid default tests."""


@app.command("inventory")
@safe_errors
def inventory(
    archive: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    extract_to: Annotated[Path | None, typer.Option()] = None,
):
    """Stream hashes and safe private originals into a new dataset manifest."""
    try:
        if output.exists():
            raise ValueError("Manifest output already exists; choose a new dataset revision")
        manifest = inventory_zip(archive, extract_to=extract_to)
        write_new_json(output, manifest.model_dump(mode="json"))
        summary = inventory_summary(manifest)
        typer.echo(
            f"Inventoried {summary['files']} files, {summary['supported_files']} supported, "
            f"{len(summary['courses'])} inferred course/subject groups. Manifest: {output}"
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Inventory failed: {_error_summary(exc)}", err=True)
        raise typer.Exit(1) from exc


@app.command("run")
@safe_errors
def run(
    manifest: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("data/benchmarks/runs"),
    implementation_root: Annotated[Path | None, typer.Option(exists=True, file_okay=False)] = None,
    live: bool = False,
    consent: bool = False,
):
    """Run the production extractor/pipeline on frozen sources and retain a new result."""
    try:
        result = run_benchmark(
            DatasetManifest.model_validate(read_json(manifest)),
            BenchmarkConfig.model_validate(read_json(config)),
            output,
            implementation_root=implementation_root,
            live=live,
            consent=consent,
        )
        typer.echo(f"Saved benchmark result: {result}")
        if any(course["status"] != "completed" for course in read_json(result)["courses"]):
            typer.echo("Some source/workload units failed; inspect the retained result.", err=True)
            raise typer.Exit(1)
    except (OSError, ValueError) as exc:
        typer.echo(f"Benchmark failed: {_error_summary(exc)}", err=True)
        raise typer.Exit(1) from exc


@app.command("profile")
@safe_errors
def profile(
    manifest: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    workers: Annotated[int, typer.Option(min=1, max=8)] = 2,
):
    """Inspect bounded PDF geometry and sampled native-text counters without transcription."""
    from anki_generator.benchmark.profile import profile_dataset

    data = profile_dataset(DatasetManifest.model_validate(read_json(manifest)), workers=workers)
    typer.echo(str(write_new_json(output, data)))


@app.command("reference-validate")
@safe_errors
def reference_validate(
    dataset: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
):
    """Validate portable reference concepts/card examples without importing them into generation."""
    from anki_generator.evaluation.contracts import DatasetInput

    data = DatasetInput.model_validate(read_json(dataset))
    typer.echo(
        f"Valid reference dataset: {len(data.reference_concepts)} targets, "
        f"{len(data.reference_cards)} examples; provenance {data.provenance}. "
        "Validation does not establish academic truth."
    )


@app.command("report")
@safe_errors
def report(
    result: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    annotations: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    references: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
):
    """Write a standalone report with separate evidence levels and denominators."""
    from anki_generator.benchmark.reports import write_report
    from anki_generator.benchmark.review import load_annotations

    data = _result(result, references)
    labels = load_annotations(annotations, data) if annotations else None
    typer.echo(str(write_report(data, output, annotations=labels)))


@app.command("review-export")
@safe_errors
def review_export(
    result: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    references: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    blind: bool = True,
):
    """Export source-linked Markdown plus pending structured human annotations."""
    from anki_generator.benchmark.review import export_review_package

    exported = export_review_package(_result(result, references), output, blind=blind)
    typer.echo(json.dumps(exported, default=str))


@app.command("annotations-validate")
@safe_errors
def annotations_validate(
    result: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    annotations: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    import_to: Annotated[Path | None, typer.Option()] = None,
    existing: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    references: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
):
    """Validate exact case/source bindings and optionally save an append-only import."""
    from anki_generator.benchmark.review import append_annotations, load_annotations

    data = _result(result, references)
    labels = load_annotations(annotations, data)
    if import_to:
        earlier = load_annotations(existing, data) if existing else None
        typer.echo(str(append_annotations(data, labels, import_to, existing=earlier)))
    else:
        typer.echo(f"Valid annotation bundle: {len(labels.annotations)} records")


@app.command("retrieval")
@safe_errors
def retrieval(
    result: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    annotations: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    references: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
):
    """Calculate relevance metrics with unjudged cases kept visible."""
    from anki_generator.benchmark.metrics import summarize_benchmark
    from anki_generator.benchmark.review import load_annotations

    data = _result(result, references)
    labels = load_annotations(annotations, data) if annotations else None
    metrics = summarize_benchmark(data, labels)
    typer.echo(str(write_new_json(output, metrics)))


@app.command("compare")
@safe_errors
def compare(
    baseline: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    candidate: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    baseline_annotations: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    candidate_annotations: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    references: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
):
    """Compare paired frozen inputs, preserving missing labels and uncertainty."""
    from anki_generator.benchmark.reports import write_comparison
    from anki_generator.benchmark.review import load_annotations

    before, after = _result(baseline, references), _result(candidate, references)
    labels_before = load_annotations(baseline_annotations, before) if baseline_annotations else None
    labels_after = load_annotations(candidate_annotations, after) if candidate_annotations else None
    typer.echo(
        str(
            write_comparison(
                before,
                after,
                output,
                baseline_annotations=labels_before,
                candidate_annotations=labels_after,
            )
        )
    )


@app.command("engineering")
@safe_errors
def engineering(output: Annotated[Path, typer.Option("--output", "-o")]):
    """Measure synthetic calculus-boundary and vector-cache engineering regressions."""
    from anki_generator.benchmark.engineering import collect_engineering_profiles

    typer.echo(str(write_new_json(output, collect_engineering_profiles())))


@app.command("smoke")
@safe_errors
def smoke(
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("data/benchmarks/smoke"),
):
    """Exercise inventory, real local extraction and reports using synthetic text only."""
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="benchmark-smoke-", dir=output) as temporary:
        directory = Path(temporary)
        archive = directory / "synthetic.zip"
        with ZipFile(archive, "w") as stream:
            stream.writestr(
                "Synthetic/courses/Probability/lecture.txt",
                "For independent events A and B, P(A and B) = P(A) P(B).\n",
            )
        manifest = inventory_zip(archive, extract_to=output / "inputs" / uuid4().hex)
        config = BenchmarkConfig.model_validate(
            {
                "name": "Synthetic developer smoke, no quality claim",
                "workloads": [
                    {
                        "id": "smoke",
                        "name": "Synthetic probability",
                        "samples": [
                            {
                                "source_id": manifest.sources[0].id,
                                "rationale": "Deterministic toolchain smoke only",
                            }
                        ],
                    }
                ],
            }
        )
        # Persist the source bytes independently of the temporary ZIP.
        result = run_benchmark(manifest, config, output)
    from anki_generator.benchmark.reports import write_report

    data = read_json(result)
    data["evidence"]["dataset_provenance"] = "synthetic inputs; real local extraction"
    typer.echo(str(write_report(data, result.parent / "report.md")))
