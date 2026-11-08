"""A second backend must not process an already-owned queue."""

from pathlib import Path

import pytest

from anki_generator.services.instance_lock import InstanceLock


def test_second_instance_is_refused_until_owner_releases(tmp_path: Path) -> None:
    first = InstanceLock(tmp_path)
    second = InstanceLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another application instance"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_separate_data_directories_allow_separate_instances(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    first = InstanceLock(tmp_path)
    second = InstanceLock(other)
    try:
        first.acquire()
        second.acquire()
    finally:
        first.release()
        second.release()
