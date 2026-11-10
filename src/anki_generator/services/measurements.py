"""Optional, content-free developer measurements, never an application dashboard.

Wall spans are inclusive and may overlap. Thread CPU excludes other stage threads
and child processes; process CPU/RSS cover the shared Python process, not a job.
No background sampler, payload serialization or new dependencies are required.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


def _peak_rss_bytes() -> int | None:
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except (ImportError, OSError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


class PipelineMeasurements:
    """Thread-safe bounded aggregates with no source text, paths or credentials.

    Labels are developer-selected stage/operation names. Never pass document names,
    prompt text, arbitrary request payloads or provider exceptions as labels.
    """

    def __init__(
        self, *, retrieval_observer: Callable[[dict[str, Any]], None] | None = None
    ) -> None:
        self._lock = threading.RLock()
        self._started = time.perf_counter()
        self._cpu_started = time.process_time()
        self._rss_started = _peak_rss_bytes()
        self._spans: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
        self._counts: dict[str, dict[str, float | int]] = defaultdict(dict)
        self._usage: dict[str, dict[str, Any]] = {}
        self._subprocesses: dict[str, dict[str, Any]] = {}
        self._retrieval_observer = retrieval_observer

    @property
    def captures_retrieval(self) -> bool:
        return self._retrieval_observer is not None

    def observe_retrieval(self, event: dict[str, Any]) -> None:
        """Forward optional private developer traces, never persist them as telemetry.

        Traces contain object IDs and ranked scores, no vectors or source text.
        A failed observer fails the opted-in experiment explicitly, rather than
        producing a successful report with silently missing retrieval evidence.
        """
        if self._retrieval_observer is not None:
            try:
                self._retrieval_observer(event)
            except Exception:
                self.count("retrieval", "capture_failures")
                raise RuntimeError("Developer retrieval capture failed.") from None

    @contextmanager
    def measure(self, stage: str, *, operation: str = "stage") -> Iterator[None]:
        wall, cpu = time.perf_counter(), time.thread_time()
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            self.record_span(
                stage,
                operation=operation,
                wall_seconds=time.perf_counter() - wall,
                thread_cpu_seconds=time.thread_time() - cpu,
                failed=failed,
            )

    def record_span(
        self,
        stage: str,
        *,
        operation: str,
        wall_seconds: float,
        thread_cpu_seconds: float | None = None,
        failed: bool = False,
    ) -> None:
        with self._lock:
            row = self._spans[stage].setdefault(
                operation,
                {
                    "count": 0,
                    "failed": 0,
                    "wall_seconds_sum": 0.0,
                    "wall_seconds_max": 0.0,
                    "initiating_thread_cpu_seconds_sum": 0.0,
                },
            )
            row["count"] += 1
            row["failed"] += int(failed)
            row["wall_seconds_sum"] += max(0, wall_seconds)
            row["wall_seconds_max"] = max(row["wall_seconds_max"], wall_seconds)
            if thread_cpu_seconds is not None:
                row["initiating_thread_cpu_seconds_sum"] += max(0, thread_cpu_seconds)

    def count(self, stage: str, name: str, amount: int | float = 1) -> None:
        if _number(amount) is None:
            raise ValueError("Measurement counts must be finite and nonnegative")
        with self._lock:
            row = self._counts[stage]
            row[name] = row.get(name, 0) + amount

    def record_usage(self, stage: str, usage: dict[str, Any], *, model: str) -> None:
        """Only returned successful-response usage, never estimates for failures.

        Known-cost sums are partial when unpriced responses exist. Cached artifact
        reuse does not call this method and therefore consumes no new API tokens.
        """
        with self._lock:
            row = self._usage.setdefault(
                stage,
                {
                    "responses": 0,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "cached_input_tokens": None,
                    "unmeasured_response_fields": {},
                    "retry_count_successful_responses": 0,
                    "estimated_cost_usd_known_sum": 0.0,
                    "unpriced_responses": 0,
                    "models": {},
                },
            )
            row["responses"] += 1
            row["models"][model] = row["models"].get(model, 0) + 1
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                number = _number(usage.get(key))
                if number is None:
                    unmeasured = row["unmeasured_response_fields"]
                    unmeasured[key] = unmeasured.get(key, 0) + 1
                else:
                    row[key] = (row[key] or 0) + int(number)
            details = usage.get("input_tokens_details")
            details = details if isinstance(details, dict) else {}
            incoming, cached = (
                _number(usage.get("input_tokens")),
                _number(details.get("cached_tokens")),
            )
            if incoming is not None and cached is not None:
                row["cached_input_tokens"] = (row["cached_input_tokens"] or 0) + int(
                    min(incoming, cached)
                )
            else:
                unmeasured = row["unmeasured_response_fields"]
                unmeasured["cached_input_tokens"] = unmeasured.get("cached_input_tokens", 0) + 1
            row["retry_count_successful_responses"] += int(_number(usage.get("retry_count")) or 0)
            cost = _number(usage.get("estimated_cost_usd"))
            if cost is None:
                row["unpriced_responses"] += 1
            else:
                row["estimated_cost_usd_known_sum"] += cost

    def record_subprocess(self, stage: str, values: dict[str, Any]) -> None:
        """Fresh parser observations only, separate from shared parent resources.

        The caller must not replay cached extraction timing as newly executed work.
        Worker CPU/RSS exclude subprocesses such as an Office conversion tool.
        """
        with self._lock:
            row = self._subprocesses.setdefault(stage, {"reports": 0})
            row["reports"] += 1
            for key in ("worker_wall_seconds", "worker_cpu_seconds", "pdf_render_seconds"):
                number = _number(values.get(key))
                if number is not None:
                    row[key + "_sum"] = row.get(key + "_sum", 0) + number
            peak = _number(values.get("worker_peak_rss_bytes"))
            if peak is not None:
                row["worker_peak_rss_bytes_max"] = max(
                    row.get("worker_peak_rss_bytes_max", 0), int(peak)
                )
            regions = _number(values.get("pdf_regions_rendered"))
            if regions is not None:
                row["pdf_regions_rendered"] = row.get("pdf_regions_rendered", 0) + int(regions)

    def provider_measurement(self, event: dict[str, Any]) -> None:
        """Consume numeric transport records; intentionally ignore arbitrary fields."""
        if event.get("kind") != "api_attempt":
            return
        stage = event["operation"]
        failed = event.get("outcome") == "failed"
        self.count(stage, "physical_api_attempts")
        self.count(stage, "physical_api_failures" if failed else "physical_api_completions")
        self.record_span(
            stage,
            operation="physical_api_attempt",
            wall_seconds=event["wall_seconds"],
            thread_cpu_seconds=event["thread_cpu_seconds"],
            failed=failed,
        )

    def resource_event(self, event: dict[str, Any]) -> None:
        kind = event.get("kind")
        stage = event.get("operation", "resource_admission")
        if kind == "api_retry":
            self.count(stage, "retry_events")
            self.count(stage, "backoff_seconds_requested", event.get("delay_seconds", 0))
        elif kind == "api_failure":
            self.count(stage, "logical_api_failures")
        elif kind == "resource_acquired":
            self.count("resource_admission", "wait_events")
            self.count("resource_admission", "wait_seconds", event.get("wait_seconds", 0))

    def snapshot(self) -> dict[str, Any]:
        import copy

        with self._lock:
            return {
                "schema_version": "1",
                "elapsed_wall_seconds": time.perf_counter() - self._started,
                "process_cpu_seconds_shared": time.process_time() - self._cpu_started,
                "process_peak_rss_bytes_cumulative": _peak_rss_bytes(),
                "process_peak_rss_bytes_at_start": self._rss_started,
                "spans": copy.deepcopy(dict(self._spans)),
                "counts": copy.deepcopy(dict(self._counts)),
                "usage": copy.deepcopy(self._usage),
                "subprocesses": copy.deepcopy(self._subprocesses),
                "scopes": {
                    "wall": (
                        "Inclusive intervals; nested/concurrent span sums are not total runtime."
                    ),
                    "cpu": (
                        "Span CPU is initiating thread only; excludes child processes "
                        "and other threads."
                    ),
                    "memory": (
                        "Process cumulative RSS high-water mark; shared with other jobs, "
                        "not stage/job peak."
                    ),
                    "process_cpu": (
                        "Whole-process CPU since recorder creation; includes concurrent jobs, "
                        "excludes children."
                    ),
                    "usage": (
                        "Returned responses only; failure token usage and unknown prices "
                        "remain unmeasured."
                    ),
                    "cost": (
                        "Estimated known-price subtotal; unpriced responses prevent "
                        "a complete cost estimate."
                    ),
                    "subprocesses": (
                        "Fresh parser reports only; worker CPU/RSS exclude child conversion tools. "
                        "Maximum per-worker RSS is not simultaneous process-tree peak."
                    ),
                },
            }
