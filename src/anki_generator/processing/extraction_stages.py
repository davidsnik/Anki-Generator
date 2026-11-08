"""Local extraction caches and complete region-by-region visual interpretation."""

from __future__ import annotations

import json

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
            document.update(
                {
                    k: snapshot[k]
                    for k in ("category", "authority", "linked_document_id")
                    if k in snapshot
                }
            )
            cache_key = digest(
                {"sha": document["sha256"], "options": options.model_dump(), "extractor": "1"}
            )
            directory = self.root / "artifacts" / document["id"] / cache_key
            result_path = directory / "extraction.json"
            force_reprocess = bool(document.get("extraction", {}).get("force_reprocess"))
            if (
                result_path.is_file()
                and document["extraction_key"] == cache_key
                and not force_reprocess
            ):
                extraction = json.loads(result_path.read_text(encoding="utf-8"))
            else:
                source = (self.root / document["storage_path"]).resolve()
                if not source.is_relative_to(self.root):
                    raise ValueError("Source storage path escapes the application data directory.")
                try:
                    result = extract_document_safely(source, directory, options=options)
                    extraction = result.model_dump(mode="json")
                except ValueError as error:
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
        regions = [
            (doc, page, region)
            for doc in self.documents
            for page in doc["extraction"]["pages"]
            for region in page["regions"]
            if region.get("needs_vision") or page.get("needs_vision")
        ]
        if not regions:
            return
        self._stage("interpretation", total=len(regions))
        for doc, page, region in regions:
            image = self.root / doc["extraction"]["artifact_dir"] / region["image_path"]
            interpreted = self._call(
                "interpretation",
                f"{doc['id']}:{region['id']}",
                {
                    "document_id": doc["id"],
                    "role": doc["category"],
                    "authority": doc["authority"],
                    "page_number": page["page_number"],
                    "region_id": region["id"],
                    "bbox": region["bbox"],
                    "machine_text": " ".join(
                        b["text"]
                        for b in page["blocks"]
                        if b["kind"] == "text"
                        and b["bbox"][1] < region["bbox"][3]
                        and b["bbox"][3] > region["bbox"][1]
                    ),
                    "warnings": page["warnings"],
                },
                VisualInterpretation,
                images=[image],
            )
            interpretation = {"region_id": region["id"], **interpreted.model_dump()}
            page["visual_interpretations"] = [
                v for v in page.get("visual_interpretations", []) if v["region_id"] != region["id"]
            ] + [interpretation]
            if interpreted.uncertain:
                self._warning(
                    f"{doc['filename']} page {page['page_number']}: visual "
                    "interpretation remains uncertain."
                )
            with self.sessions() as session:
                stored = session.get(Document, doc["id"])
                stored.extraction = json.loads(json.dumps(doc["extraction"]))
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
                    not any(
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
                    stored.extraction = json.loads(json.dumps(doc["extraction"]))
                    session.commit()
        self._stage("interpretation", complete=True)
