"""Explicit local HTTP transport for packaged-app tests; never bundled in releases.

The production executable uses its real OpenAI SDK against this loopback fixture.
Responses and embeddings are synthetic, not measurements of academic quality.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from collections import Counter
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from anki_generator.processing import contracts

from .controlled_provider import ControlledProvider

TEST_KEY = "sk-controlled-packaged-desktop-no-paid-requests"
SCHEMAS = {
    "VisualInterpretation": "interpretation",
    "DocumentKnowledge": "knowledge",
    "CourseKnowledge": "consolidation",
    "GeneratedCards": "generation",
    "QualityReview": "factual",
    "DuplicateDecision": "deduplication",
    "CoverageReview": "coverage",
    "SourceAuditResult": "source_audit",
    "SourceMatchingResult": "source_matching",
    "TargetCoverageResult": "target_coverage",
    "IdentityMatchResult": "identity",
}


class ControlledResponsesServer(AbstractContextManager):
    def __init__(self, port: int = 0):
        self.lock = threading.Lock()
        self.gates: dict[str, threading.Event] = {}
        self.waiting: set[str] = set()
        self.entered: set[str] = set()
        self.calls: Counter[str] = Counter()
        self.image_requests = 0
        self.provider = ControlledProvider()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _reply(self, status: int, value: Any):
                data = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _authorized(self):
                if self.headers.get("Authorization") == f"Bearer {TEST_KEY}":
                    return True
                self._reply(401, {"error": {"message": "Synthetic fixture key required"}})
                return False

            def do_GET(self):
                if not self._authorized():
                    return
                if self.path == "/control":
                    self._reply(200, owner.snapshot())
                elif self.path == "/v1/models":
                    self._reply(
                        200,
                        {
                            "object": "list",
                            "data": [
                                {
                                    "id": identifier,
                                    "object": "model",
                                    "created": 0,
                                    "owned_by": "synthetic-test-fixture",
                                }
                                for identifier in ("gpt-6-astra", "text-embedding-3-small")
                            ],
                        },
                    )
                else:
                    self._reply(404, {"error": {"message": "Fixture endpoint not found"}})

            def do_POST(self):
                if not self._authorized():
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 96 * 1024 * 1024:
                    self._reply(413, {"error": {"message": "Fixture request too large"}})
                    return
                try:
                    body = json.loads(self.rfile.read(length))
                    if self.path == "/control/gates":
                        with owner.lock:
                            if owner.waiting:
                                raise ValueError("Release previous gates first")
                            owner.gates = {
                                str(identifier): threading.Event()
                                for identifier in body["document_ids"]
                            }
                            owner.entered.clear()
                        result = owner.snapshot()
                    elif self.path == "/control/release":
                        with owner.lock:
                            for identifier in body["document_ids"]:
                                owner.gates[str(identifier)].set()
                        result = owner.snapshot()
                    elif self.path == "/v1/responses":
                        result = owner.response(body)
                    elif self.path == "/v1/embeddings":
                        dimensions = int(body["dimensions"])
                        with owner.lock:
                            owner.calls["embeddings"] += 1
                        result = {
                            "object": "list",
                            "model": body["model"],
                            "data": [
                                {
                                    "object": "embedding",
                                    "index": index,
                                    "embedding": [1.0] + [0.0] * (dimensions - 1),
                                }
                                for index, _text in enumerate(body["input"])
                            ],
                            "usage": {"prompt_tokens": 30, "total_tokens": 30},
                        }
                    else:
                        self._reply(404, {"error": {"message": "Fixture endpoint not found"}})
                        return
                    self._reply(200, result)
                except (KeyError, TypeError, ValueError, AssertionError) as error:
                    self._reply(
                        400,
                        {"error": {"message": f"Synthetic fixture rejected input: {error}"}},
                    )

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        with self.lock:
            for gate in self.gates.values():
                gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def snapshot(self):
        with self.lock:
            return {
                "provider": "synthetic local HTTP fixture; no paid calls",
                "waiting": sorted(self.waiting),
                "entered": sorted(self.entered),
                "calls": dict(self.calls),
                "image_requests": self.image_requests,
            }

    def response(self, body: dict[str, Any]):
        schema_name = body["text"]["format"]["name"]
        stage = "connection" if schema_name == "ConnectionCheck" else SCHEMAS[schema_name]
        parts = body["input"][0]["content"]
        payload = json.loads(next(part["text"] for part in parts if part["type"] == "input_text"))
        with self.lock:
            self.calls[stage] += 1
            if any(part["type"] == "input_image" for part in parts):
                self.image_requests += 1
            gate = self.gates.get(payload.get("document_id")) if stage == "knowledge" else None
            if gate is not None and not gate.is_set():
                identifier = payload["document_id"]
                self.entered.add(identifier)
                self.waiting.add(identifier)
            else:
                gate = None
        if gate is not None:
            try:
                if not gate.wait(timeout=180):
                    raise ValueError("Synthetic provider barrier timed out")
            finally:
                with self.lock:
                    self.waiting.discard(payload["document_id"])
        if stage == "connection":
            data = {"connected": True}
        else:
            schema = getattr(contracts, schema_name)
            data = self.provider.structured(stage, payload, schema, model=body["model"]).data
            if stage == "generation":
                # Exercise actual frozen multiprocessing + SymPy, not just imports.
                data.cards[0].symbolic_checks = [
                    contracts.SymbolicCheck(
                        lhs="a*a+b*b",
                        rhs="b*b+a*a",
                        variables=["a", "b"],
                        assumptions=[],
                        purpose="Commutative sum of squared leg lengths",
                    )
                ]
            data = data.model_dump(mode="json")
        return {
            "id": f"resp_desktop_fixture_{time.monotonic_ns()}",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "model": body["model"],
            "output": [
                {
                    "id": "msg_synthetic_desktop",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": json.dumps(data), "annotations": []}
                    ],
                }
            ],
            "parallel_tool_calls": True,
            "tools": [],
            "tool_choice": "auto",
            "text": body["text"],
            "usage": {
                "input_tokens": 20,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 10,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 30,
            },
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    with ControlledResponsesServer(args.port) as server:
        args.ready_file.write_text(json.dumps({"origin": server.origin, "pid": os.getpid()}))
        threading.Event().wait()


if __name__ == "__main__":
    main()
