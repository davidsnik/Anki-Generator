"""Configuration has a deliberately small, validated surface."""

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from anki_generator.config import DiscoverySettings, Settings, load_settings


def test_documented_defaults_match_builtin_settings() -> None:
    default_file = Path(__file__).parents[1] / "config/default.toml"
    assert load_settings(default_file) == load_settings() == Settings()


def test_loads_explicit_settings(tmp_path: Path) -> None:
    config = tmp_path / "settings.toml"
    config.write_text('[discovery]\nsupported_extensions = [".csv"]\n', encoding="utf-8")
    assert load_settings(config).discovery.supported_extensions == (".csv",)


@pytest.mark.parametrize(
    "config",
    [
        {"unsupported": True},
        {"discovery": {"unknown": True}},
        {"discovery": {"supported_extensions": []}},
        {"discovery": {"supported_extensions": ["PDF"]}},
        {"discovery": {"supported_extensions": [".PDF"]}},
        {"discovery": {"supported_extensions": [".pdf", ".pdf"]}},
        {"discovery": {"excluded_directory_names": ["a/b"]}},
        {"discovery": {"excluded_directory_names": [".."]}},
        {"discovery": {"excluded_directory_names": ["x", "x"]}},
    ],
)
def test_invalid_settings_are_rejected(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(config)


def test_invalid_toml_reports_parse_error(tmp_path: Path) -> None:
    config = tmp_path / "settings.toml"
    config.write_text("[invalid", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_settings(config)


def test_empty_exclusions_are_allowed() -> None:
    assert DiscoverySettings(excluded_directory_names=()).excluded_directory_names == ()
