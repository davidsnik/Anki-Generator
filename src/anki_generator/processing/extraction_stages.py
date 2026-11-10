"""Local extraction caches and complete region-by-region visual interpretation."""

from __future__ import annotations

import json
import shutil

from sqlalchemy import delete, select

from anki_generator.database.entities import (
    Document,
    Page,
    Run,
)
from anki_generator.ingestion.contracts import ExtractionOptions
from anki_generator.processing.contracts import (
    VisualInterpretation,
)

from .state import atomic_json, digest, entity_data


class ExtractionStages:
    def _extract(self) -> None:
        from anki_generator.ingestion.extraction import extract_document_safely

        with self.sessions() as session:
            documents = list(
                session.scalars(
                    select(Document)
                    .where(Document.course_id == self.course_id)
                    .order_by(Document.relative_path)
                )
            )
            run = session.get(Run, self.run_id)
            if not run.inputs:
                run.inputs = [
                    {
                        "document_id": d.id,
                        "sha256": d.sha256,
                        "category": d.category,
                        "authority": d.authority,
                        "linked_document_id": d.linked_document_id,
                    }
                    for d in documents
                ]
                session.commit()
            input_by_id = {item.get("document_id", item.get("id")): item for item in run.inputs}
            documents = [d for d in documents if d.id in input_by_id]
            snapshots = [entity_data(d) for d in documents]
            if set(input_by_id) != {d["id"] for d in snapshots}:
                raise ValueError(
                    "The source document set changed. Start a new run for the current sources."
                )
        if not snapshots:
            raise ValueError("Import at least one supported source document before processing.")
        self._stage("extraction", total=len(snapshots))
        options = ExtractionOptions.model_validate(self.config.get("extraction", {}))
        selected = set(
            self.request.get("document_ids") or [document["id"] for document in snapshots]
        )
        self._stage("extraction", total=len(selected))
        for document in snapshots:
            self._check()
            snapshot = input_by_id[document["id"]]
            if any(
                document.get(field) != snapshot.get(field)
                for field in ("sha256", "category", "authority", "linked_document_id")
                if field in snapshot
            ):
                raise ValueError(
                    "A source changed after this run was created. Start a new run for "
                    "the updated document set."
                )
            from anki_generator.services.source_corrections import snapshot_source_state

            with self.sessions() as session:
                current_source_state = snapshot_source_state(
                    session, session.get(Document, document["id"])
                )
            if (
                "source_revision" in snapshot
                and snapshot["source_revision"] != current_source_state["source_revision"]
            ):
                raise ValueError(
                    "A human correction or selected region changed. "
                    "Start a new run for corrected evidence."
                )
            document["source_revision"] = current_source_state["source_revision"]
            if document["id"] not in selected:
                if not document["extraction"]:
                    document["extraction"] = {
                        "pages": [],
                        "status": "unprocessed",
                        "warnings": [],
                        "artifact_dir": "",
                    }
                continue
            document.update(
                {
                    k: snapshot[k]
                    for k in ("category", "authority", "linked_document_id")
                    if k in snapshot
                }
            )
            cache_key = digest(
                {"sha": document["sha256"], "options": options.model_dump(), "extractor": "3"}
            )
            directory = self.root / "artifacts" / document["id"] / cache_key
            previous = document.get("extraction", {})
            if document["extraction_key"] == cache_key and previous.get("artifact_dir"):
                directory = (self.root / previous["artifact_dir"]).resolve()
                if not directory.is_relative_to(self.root):
                    raise ValueError("Extraction artifact path escapes local storage")
            selected_pages = (
                self.request.get("page_numbers")
                if self.mode == "extract" or self.request.get("retry_stage") == "extraction"
                else None
            )
            force_reprocess = (
                bool(previous.get("force_reprocess"))
                or self.request.get("retry_stage") == "extraction"
            )
            if selected_pages and force_reprocess:
                target_dir = (
                    self.root
                    / "artifacts"
                    / document["id"]
                    / digest({"base": cache_key, "pages": selected_pages, "run": self.run_id})
                )
                if directory.is_dir() and not target_dir.exists():
                    shutil.copytree(directory, target_dir)
                directory = target_dir
            result_path = directory / "extraction.json"
            if (
                result_path.is_file()
                and document["extraction_key"] == cache_key
                and not force_reprocess
            ):
                self._count("extraction", "cache_hits")
                extraction = json.loads(result_path.read_text(encoding="utf-8"))
            else:
                self._count("extraction", "cache_misses")
                source = (self.root / document["storage_path"]).resolve()
                if not source.is_relative_to(self.root):
                    raise ValueError("Source storage path escapes the application data directory.")
                try:
                    derivative = previous.get("rendered_source_path")
                    if selected_pages and source.suffix.lower() != ".pdf":
                        if not derivative:
                            raise ValueError(
                                "Selected-page processing requires a PDF or an Office PDF rendering"
                            )
                        source = (self.root / previous["artifact_dir"] / derivative).resolve()
                        if not source.is_relative_to(self.root) or not source.is_file():
                            raise ValueError(
                                "The Office PDF rendering is missing; reprocess the whole document"
                            )
                    with self._measure("extraction", operation="parser_subprocess"):
                        with self._local_work():
                            result = extract_document_safely(
                                source, directory, options=options, page_numbers=selected_pages
                            )
                    if self.measurements is not None and result.measurements is not None:
                        self.measurements.record_subprocess(
                            "extraction", result.measurements.model_dump(exclude_none=True)
                        )
                    extraction = result.model_dump(mode="json")
                    if selected_pages and derivative:
                        extraction["source_sha256"] = document["sha256"]
                        extraction["source_type"] = previous.get(
                            "source_type", source.suffix.lower()
                        )
                        extraction["rendered_source_path"] = previous["rendered_source_path"]
                        extraction["rendering_engine"] = previous.get("rendering_engine")
                    if selected_pages and previous.get("pages"):
                        by_page = {page["page_number"]: page for page in previous["pages"]}
                        by_page.update({page["page_number"]: page for page in extraction["pages"]})
                        extraction["pages"] = [by_page[number] for number in sorted(by_page)]
                        if len(by_page) == extraction["total_pages"]:
                            statuses = {page["status"] for page in extraction["pages"]}
                            extraction["status"] = (
                                "partial"
                                if statuses & {"partial", "failed"}
                                else (
                                    "needs_review"
                                    if any(page.get("needs_vision") for page in extraction["pages"])
                                    else "complete"
                                )
                            )
                            extraction["warnings"] = [
                                warning
                                for warning in extraction["warnings"]
                                if "Targeted extraction contains only" not in warning
                            ]
                        extraction["warnings"] = list(
                            dict.fromkeys(previous.get("warnings", []) + extraction["warnings"])
                        )
                except ValueError as error:
                    if selected_pages:
                        raise
                    extraction = {
                        "schema_version": "1",
                        "extractor_version": "1",
                        "source_sha256": document["sha256"],
                        "source_type": source.suffix.lower(),
                        "pages": [],
                        "warnings": [
                            f"Document extraction failed ({type(error).__name__}). "
                            "Inspect the file or reimport a readable original."
                        ],
                        "status": "failed",
                        "needs_vision": False,
                        "total_pages": 0,
                    }
                if extraction["source_sha256"] != document["sha256"]:
                    raise ValueError(
                        "An original source hash changed. Reimport this document before processing."
                    )
                extraction["artifact_dir"] = directory.relative_to(self.root).as_posix()
                if extraction["status"] == "failed" and force_reprocess:
                    previous = document.get("extraction", {})
                    extraction = {
                        **previous,
                        **({} if previous.get("pages") else extraction),
                        "status": "failed",
                        "effective_status": "failed",
                        "force_reprocess": True,
                        "warnings": list(
                            dict.fromkeys(previous.get("warnings", []) + extraction["warnings"])
                        ),
                    }
                else:
                    atomic_json(result_path, extraction)
            document["extraction"] = extraction
            with self.sessions() as session:
                stored = session.get(Document, document["id"])
                stored.extraction = extraction
                stored.extraction_key = "" if extraction.get("force_reprocess") else cache_key
                stored.status = extraction["status"]
                stored.warnings = extraction["warnings"]
                session.execute(delete(Page).where(Page.document_id == stored.id))
                for page in extraction["pages"]:
                    session.add(
                        Page(
                            document_id=stored.id,
                            page_number=page["page_number"],
                            width=page["width"],
                            height=page["height"],
                            text=page["text"],
                            blocks=page["blocks"],
                            regions=page["regions"],
                            warnings=page["warnings"],
                            needs_vision=page["needs_vision"],
                            status=page["status"],
                        )
                    )
                session.commit()
            if extraction["status"] != "complete":
                self._warning(
                    f"{document['filename']}: {extraction['status']}; inspect "
                    "extraction warnings and original regions."
                )
            self._progress(
                "extraction", document["id"], result_path.relative_to(self.root).as_posix()
            )
        self.documents = snapshots
        self._stage("extraction", complete=True)
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.progress = {
                **run.progress,
                "documents": len(snapshots),
                "pages": sum(len(d["extraction"]["pages"]) for d in snapshots),
            }
            session.commit()
        if not any(d["extraction"]["pages"] for d in snapshots):
            raise ValueError(
                "No source pages could be extracted. Inspect document warnings before retrying."
            )

    def _interpret(self) -> None:
        selected_docs = set(self.request.get("document_ids") or [d["id"] for d in self.documents])
        pages = set(self.request.get("page_numbers") or [])
        selected_regions = set(self.request.get("region_ids") or [])
        replace_human = self.request.get("replace_human", False)
        regions = [
            (doc, page, region)
            for doc in self.documents
            if doc["id"] in selected_docs
            for page in doc["extraction"]["pages"]
            if not pages or page["page_number"] in pages
            for region in page["regions"]
            if (not selected_regions or region["id"] in selected_regions)
            and (region.get("needs_vision") or page.get("needs_vision") or self.mode == "interpret")
            and (replace_human or not (page.get("human_verified") or region.get("human_verified")))
        ]
        if not regions:
            return
        self._stage("interpretation", total=len(regions))

        def interpret(task):
            doc, page, region = task
            relative = (
                region.get("storage_path")
                or f"{doc['extraction']['artifact_dir']}/{region['image_path']}"
            )
            blocks = [
                b["text"]
                for b in page["blocks"]
                if b["kind"] == "text"
                and b["bbox"][0] < region["bbox"][2]
                and b["bbox"][2] > region["bbox"][0]
                and b["bbox"][1] < region["bbox"][3]
                and b["bbox"][3] > region["bbox"][1]
            ]
            hint = " ".join(blocks)
            if len(hint.encode()) > self.options.input_token_budget // 3:
                hint = (
                    "[Unlocalized machine text omitted; "
                    "inspect the complete original image region.]"
                )
            result = self._call(
                "interpretation",
                f"{doc['id']}:{region['id']}",
                {
                    "document_id": doc["id"],
                    "role": doc["category"],
                    "authority": doc["authority"],
                    "page_number": page["page_number"],
                    "region_id": region["id"],
                    "bbox": region["bbox"],
                    "machine_text": hint,
                    "warnings": page["warnings"],
                    "source_revision": doc.get("source_revision", ""),
                },
                VisualInterpretation,
                images=[self.root / relative],
            )
            return task, {"region_id": region["id"], "origin": "model", **result.model_dump()}

        results = self._parallel(regions, interpret)
        for (doc, page, region), interpretation in results:
            page["visual_interpretations"] = [
                v for v in page.get("visual_interpretations", []) if v["region_id"] != region["id"]
            ] + [interpretation]
            if interpretation["uncertain"]:
                self._warning(
                    f"{doc['filename']} page {page['page_number']}: "
                    "visual interpretation remains uncertain."
                )
            # Preserve native extraction and all human corrections separately. Only
            # automatic visual readings are appended to the original artifact.
            with self.sessions() as session:
                stored = session.get(Document, doc["id"])
                native = json.loads(json.dumps(stored.extraction))
                native_page = next(
                    (p for p in native["pages"] if p["page_number"] == page["page_number"]), None
                )
                if native_page is not None:
                    native_page["visual_interpretations"] = [
                        v
                        for v in native_page.get("visual_interpretations", [])
                        if v["region_id"] != region["id"]
                    ] + [interpretation]
                stored.extraction = native
                if replace_human and not interpretation["uncertain"]:
                    from anki_generator.services.source_corrections import (
                        adopt_automatic_replacement,
                    )

                    adopt_automatic_replacement(
                        session,
                        doc["id"],
                        page["page_number"],
                        region["id"],
                        interpretation["transcription"],
                        self.run_id,
                    )
                session.commit()
        if replace_human:
            from anki_generator.services.source_corrections import adopt_automatic_replacement

            for doc in self.documents:
                for page in doc["extraction"]["pages"]:
                    selected_results = [
                        reading
                        for (d, p, _), reading in results
                        if d["id"] == doc["id"] and p["page_number"] == page["page_number"]
                    ]
                    if (
                        selected_results
                        and not selected_regions
                        and all(not reading["uncertain"] for reading in selected_results)
                    ):
                        with self.sessions() as session:
                            adopt_automatic_replacement(
                                session,
                                doc["id"],
                                page["page_number"],
                                None,
                                "\n".join(reading["transcription"] for reading in selected_results),
                                self.run_id,
                            )
                            session.commit()
        for doc in self.documents:
            flagged = [
                (page, region)
                for page in doc["extraction"]["pages"]
                for region in page["regions"]
                if region.get("needs_vision") or page.get("needs_vision")
            ]
            if flagged:
                unresolved = any(
                    not (page.get("human_verified") or region.get("human_verified"))
                    and not any(
                        item["region_id"] == region["id"] and not item["uncertain"]
                        for item in page.get("visual_interpretations", [])
                    )
                    for page, region in flagged
                )
                doc["extraction"]["vision_status"] = "uncertain" if unresolved else "interpreted"
                doc["extraction"]["effective_status"] = (
                    "complete"
                    if not unresolved and doc["extraction"]["status"] == "needs_review"
                    else doc["extraction"]["status"]
                )
                with self.sessions() as session:
                    stored = session.get(Document, doc["id"])
                    stored.extraction = {
                        **stored.extraction,
                        "vision_status": doc["extraction"]["vision_status"],
                        "effective_status": doc["extraction"]["effective_status"],
                    }
                    session.commit()
        self._stage("interpretation", complete=True)
