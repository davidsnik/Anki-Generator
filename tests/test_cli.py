"""Exercise the installed command surface without external services."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from anki_generator import cli
from anki_generator.models import DiscoveryManifest

runner = CliRunner()


@pytest.mark.parametrize("arguments", [["--help"], ["inspect", "--help"]])
def test_help_starts(arguments: list[str]) -> None:
    result = runner.invoke(cli.app, arguments)
    assert result.exit_code == 0
    assert "inspect" in result.output.lower() or "course" in result.output.lower()


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 2
    assert "Usage" in result.output


def test_inspect_synthetic_course(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "fixtures/example-course"
    result = runner.invoke(cli.app, ["inspect", str(fixture), "--output", str(tmp_path)])
    assert result.exit_code == 0, result.output
    manifest = DiscoveryManifest.model_validate_json((tmp_path / "manifest.json").read_bytes())
    assert len(manifest.documents) >= 3
    assert "Discovered" in result.output


def test_empty_course_reports_success(tmp_path: Path) -> None:
    course = tmp_path / "course"
    course.mkdir()
    output = tmp_path / "output"
    result = runner.invoke(cli.app, ["inspect", str(course), "-o", str(output)])
    assert result.exit_code == 0
    assert "empty" in result.output
    manifest = DiscoveryManifest.model_validate_json((output / "manifest.json").read_bytes())
    assert manifest.documents == ()


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_bad_input_is_usage_error(tmp_path: Path, kind: str) -> None:
    course = tmp_path / "course"
    if kind == "file":
        course.write_text("not a directory", encoding="utf-8")
    result = runner.invoke(cli.app, ["inspect", str(course), "-o", str(tmp_path / "out")])
    assert result.exit_code == 2
    assert not (tmp_path / "out").exists()


def test_missing_output_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["inspect", str(tmp_path)])
    assert result.exit_code == 2
    assert "output" in result.output.lower()


def test_repeated_run_requires_overwrite(tmp_path: Path) -> None:
    course = tmp_path / "course"
    course.mkdir()
    (course / "notes.txt").write_text("source", encoding="utf-8")
    output = tmp_path / "result"
    arguments = ["inspect", str(course), "--output", str(output)]
    first = runner.invoke(cli.app, arguments)
    assert first.exit_code == 0, first.output
    previous = (output / "manifest.json").read_bytes()
    denied = runner.invoke(cli.app, arguments)
    assert denied.exit_code == 1
    assert "overwrite" in denied.output
    assert (output / "manifest.json").read_bytes() == previous
    overwritten = runner.invoke(cli.app, [*arguments, "--overwrite"])
    assert overwritten.exit_code == 0, overwritten.output
    assert (output / "manifest.json").read_bytes() == previous


def test_nested_output_documents_are_not_scanned(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("source", encoding="utf-8")
    output = tmp_path / "custom-result"
    output.mkdir()
    (output / "previous.pdf").write_bytes(b"old output")
    result = runner.invoke(cli.app, ["inspect", str(tmp_path), "-o", str(output)])
    assert result.exit_code == 0, result.output
    manifest = DiscoveryManifest.model_validate_json((output / "manifest.json").read_bytes())
    assert [document.relative_path for document in manifest.documents] == ["notes.txt"]


def test_config_controls_discovery_and_invalid_config_fails_cleanly(tmp_path: Path) -> None:
    course = tmp_path / "course"
    course.mkdir()
    (course / "custom.csv").write_text("a,b", encoding="utf-8")
    config = tmp_path / "settings.toml"
    config.write_text('[discovery]\nsupported_extensions=[".csv"]', encoding="utf-8")
    output = tmp_path / "result"
    args = ["inspect", str(course), "-o", str(output), "--config", str(config)]
    assert runner.invoke(cli.app, args).exit_code == 0
    manifest = DiscoveryManifest.model_validate_json((output / "manifest.json").read_bytes())
    assert manifest.documents[0].file_type == "csv"
    previous = (output / "manifest.json").read_bytes()
    config.write_text("unknown = true", encoding="utf-8")
    bad = runner.invoke(cli.app, [*args, "--overwrite"])
    assert bad.exit_code == 1
    assert "Error:" in bad.output
    assert (output / "manifest.json").read_bytes() == previous


def test_discovery_error_does_not_publish_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise PermissionError("simulated unreadable course")

    monkeypatch.setattr(cli, "discover_documents", fail)
    output = tmp_path / "result"
    result = runner.invoke(cli.app, ["inspect", str(tmp_path), "-o", str(output)])
    assert result.exit_code == 1
    assert "simulated unreadable" in result.output
    assert not output.exists()
