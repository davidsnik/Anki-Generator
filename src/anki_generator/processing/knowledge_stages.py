"""Role-aware sections and the source-grounded course concept inventory."""

from __future__ import annotations

import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from anki_generator.database.entities import (
    Concept,
    Run,
)
from anki_generator.processing.contracts import (
    PROMPT_VERSION,
    CourseKnowledge,
    DocumentKnowledge,
)

from .state import digest, entity_data


class KnowledgeStages:
    def _knowledge(self) -> None:
        from anki_generator.services.context_budget import bounded_batches

        tasks = []
        chunk_limit = min(
            self.options.source_chunk_characters, self.options.input_token_budget // 3
        )
        for document in self.documents:
            for page in document["extraction"]["pages"]:
                text = page["text"]
                sections = [
                    (text[offset : offset + chunk_limit], [])
                    for offset in range(0, len(text), chunk_limit - 200)
                    if text[offset : offset + chunk_limit].strip()
                ]
                sections.extend(("", [item]) for item in page.get("visual_interpretations", []))
                for index, (segment, visual) in enumerate(sections or [("", [])]):
                    tasks.append((document, page, index, segment, visual))
        self._stage("knowledge", total=len(tasks))

        def analyze(task):
            document, page, index, segment, visual = task
            visual_ids = {item["region_id"] for item in visual}
            payload = {
                "course": {"name": self.course["name"], "description": self.course["description"]},
                "document_id": document["id"],
                "filename": document["filename"],
                "role": document["category"],
                "authority": document["authority"],
                "linked_document_id": document["linked_document_id"],
                "role_influence": self.config.get("role_influence", {}),
                "page_number": page["page_number"],
                "text": segment,
                "visual_interpretations": visual,
                "available_regions": [
                    {"region_id": r["id"], "bbox": r["bbox"]}
                    for r in page["regions"]
                    if r["id"] in visual_ids
                ],
                "extraction_warnings": page["warnings"],
                "source_revision": document.get("source_revision", ""),
                "human_verified": page.get("human_verified", False),
            }
            result = self._call(
                "knowledge",
                f"{document['id']}:{page['page_number']}:{index}",
                payload,
                DocumentKnowledge,
            )
            for warning in result.warnings + result.conflicts:
                self._warning(f"{document['filename']}: {warning}")
            for concept in result.concepts:
                errors = self.evidence.validate(concept.sources)
                concept.uncertain |= bool(errors or result.conflicts)
                concept.conflicts.extend(errors + result.conflicts)
            return {
                "document_id": document["id"],
                "role": document["category"],
                "authority": document["authority"],
                **result.model_dump(mode="json"),
            }

        analyses = self._parallel(tasks, analyze)
        self._stage("knowledge", complete=True)
        self._load_concepts()
        # Preserve complete concepts/assumptions in bounded shards rather than
        # compressing an entire course into a final oversized request.
        units = []
        for analysis in analyses:
            for concept in analysis["concepts"]:
                units.append(
                    {
                        **{key: analysis[key] for key in ("document_id", "role", "authority")},
                        "concepts": [concept],
                        "exercises": [
                            e
                            for e in analysis["exercises"]
                            if concept["key"] in e["concepts"] or concept["title"] in e["concepts"]
                        ],
                        "conflicts": analysis["conflicts"],
                    }
                )
        batches = bounded_batches(
            units,
            max_bytes=max(2000, self.options.input_token_budget // 2),
            max_items=self.options.coverage_batch_size,
        )
        consolidated = []
        for index, batch in enumerate(batches):
            consolidated.append(
                self._call(
                    "consolidation",
                    f"course-shard-{index}",
                    {
                        "course": self.course["name"],
                        "analyses": batch,
                        "role_influence": self.config.get("role_influence", {}),
                        "hierarchy_scope": (
                            "Preserve topics/subtopics and all explicit assumptions "
                            "within this source-linked shard."
                        ),
                    },
                    CourseKnowledge,
                )
            )
        merged = {}
        for shard in consolidated:
            for concept in shard.concepts:
                if concept.key not in merged:
                    merged[concept.key] = concept
                else:
                    current = merged[concept.key]
                    if set(current.assumptions) != set(concept.assumptions):
                        concept.key = f"{concept.key}:{digest(sorted(concept.assumptions))[:10]}"
                        merged[concept.key] = concept
                        continue
                    refs = {
                        json.dumps(ref.model_dump(mode="json"), sort_keys=True): ref
                        for ref in current.sources + concept.sources
                    }
                    current.sources = list(refs.values())
                    current.relationships = list(
                        dict.fromkeys(current.relationships + concept.relationships)
                    )
                    current.exercise_frequency += concept.exercise_frequency
                    current.conflicts = list(dict.fromkeys(current.conflicts + concept.conflicts))
                    current.uncertain |= concept.uncertain
        result = CourseKnowledge(
            concepts=list(merged.values()),
            terminology=[v for shard in consolidated for v in shard.terminology],
            conflicts=[v for shard in consolidated for v in shard.conflicts],
            unresolved=[v for shard in consolidated for v in shard.unresolved],
        )
        self._persist_concepts(result, analyses)
        for warning in result.conflicts + result.unresolved:
            self._warning(warning)
        self._stage("consolidation", complete=True)

    def _load_concepts(self) -> None:
        with self.sessions() as session:
            self.concepts = [
                entity_data(c)
                for c in session.scalars(select(Concept).where(Concept.course_id == self.course_id))
            ]

    def _persist_concepts(self, result: CourseKnowledge, analyses: list[dict[str, Any]]) -> None:
        keys = {c.key for c in result.concepts}
        if len(keys) != len(result.concepts):
            raise ValueError(
                "Course synthesis produced duplicate semantic concept keys. Retry "
                "with a supported model."
            )
        previous_by_key = {c["metadata_json"].get("canonical_key"): c["id"] for c in self.concepts}
        previous_by_name = {
            (
                c["title"].casefold(),
                c["kind"],
                tuple(sorted(c["metadata_json"].get("assumptions", []))),
            ): c["id"]
            for c in self.concepts
        }
        ids = {
            c.key: previous_by_key.get(c.key)
            or previous_by_name.get((c.title.casefold(), c.kind, tuple(sorted(c.assumptions))))
            or str(uuid5(NAMESPACE_URL, f"{self.course_id}:concept:{c.key}"))
            for c in result.concepts
        }
        from anki_generator.services.identity import reconcile

        for candidate in result.concepts:
            ids[candidate.key] = reconcile(
                self,
                "concept",
                candidate.key,
                {
                    "title": candidate.title,
                    "statement": candidate.statement,
                    "kind": candidate.kind,
                    "assumptions": candidate.assumptions,
                    "sources": [ref.model_dump(mode="json") for ref in candidate.sources],
                },
                ids[candidate.key],
                self.concepts,
            )
        seen_ids = set()
        for key in ids:
            if ids[key] in seen_ids:
                ids[key] = str(uuid5(NAMESPACE_URL, f"{self.course_id}:concept:{key}"))
            seen_ids.add(ids[key])
        parent_keys = {c.key: c.parent_key for c in result.concepts}
        for key in keys:
            visited = {key}
            parent = parent_keys[key]
            while parent:
                if parent not in keys or parent in visited:
                    raise ValueError(
                        "Course synthesis produced an invalid or cyclic topic "
                        "hierarchy. Retry the run."
                    )
                visited.add(parent)
                parent = parent_keys[parent]
        exercise_records = [e for a in analyses for e in a.get("exercises", [])]
        exclusions = self.config.get("criteria", {}).get("topic_exclusions", [])
        with self.sessions() as session:
            current_ids = set(ids.values())
            for previous in session.scalars(
                select(Concept).where(Concept.course_id == self.course_id)
            ):
                if previous.id not in current_ids:
                    previous.metadata_json = {
                        **previous.metadata_json,
                        "active_in_inventory": False,
                    }
                    previous.coverage_status = "out_of_scope"
            for candidate in result.concepts:
                concept = session.get(Concept, ids[candidate.key])
                if concept is None:
                    concept = Concept(
                        id=ids[candidate.key], course_id=self.course_id, title=candidate.title
                    )
                    session.add(concept)
                candidate.sources = self.evidence.enrich(candidate.sources)
                errors = self.evidence.validate(candidate.sources)
                concept.title = candidate.title
                concept.description = candidate.statement
                concept.kind = candidate.kind
                concept.parent_id = ids.get(candidate.parent_key)
                from anki_generator.services.importance import importance_from_sources

                relevant_exercises = [
                    e
                    for e in exercise_records
                    if candidate.key in e.get("concepts", [])
                    or candidate.title in e.get("concepts", [])
                ]
                if not analyses and concept.exercise_analysis:
                    relevant_exercises = concept.exercise_analysis
                estimate = (
                    (concept.metadata_json or {}).get("model_importance", candidate.importance)
                    if not analyses
                    else candidate.importance
                )
                concept.importance, importance_signals = importance_from_sources(
                    estimate,
                    [ref.model_dump(mode="json") for ref in candidate.sources],
                    self.documents,
                    relevant_exercises,
                    self.config.get("role_influence", {}),
                )
                concept.sources = [ref.model_dump(mode="json") for ref in candidate.sources]
                concept.relationships = [ids[k] for k in candidate.relationships if k in ids]
                concept.exercise_analysis = relevant_exercises
                concept.excluded = concept.excluded or any(
                    str(x).casefold() in {candidate.key.casefold(), candidate.title.casefold()}
                    for x in exclusions
                )
                concept.metadata_json = {
                    **(concept.metadata_json or {}),
                    "canonical_key": candidate.key,
                    "active_in_inventory": True,
                    "assumptions": candidate.assumptions,
                    "importance_reason": candidate.importance_reason,
                    "importance_signals": importance_signals,
                    "model_importance": estimate,
                    "exercise_frequency": candidate.exercise_frequency,
                    "uncertain": candidate.uncertain or bool(errors),
                    "conflicts": list(dict.fromkeys(candidate.conflicts + errors)),
                    "run_id": self.run_id,
                    "prompt_version": PROMPT_VERSION,
                }
            session.commit()
        self._load_concepts()
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.progress = {**run.progress, "concepts": len(self.concepts)}
            session.commit()
        if not self.concepts:
            self._warning(
                "No supported concepts were identified. No cards can be generated; "
                "inspect document extraction."
            )

    def _eligible_concepts(self) -> list[dict[str, Any]]:
        excluded = {c["id"] for c in self.concepts if c["excluded"]}
        while True:
            expanded = excluded | {c["id"] for c in self.concepts if c["parent_id"] in excluded}
            if expanded == excluded:
                break
            excluded = expanded
        concepts = [
            c
            for c in self.concepts
            if c["id"] not in excluded
            and c["kind"] != "topic"
            and c["metadata_json"].get("active_in_inventory", True)
        ]
        topic_id = self.request.get("topic_id")
        if topic_id:
            children = {topic_id}
            while True:
                expanded = children | {c["id"] for c in self.concepts if c["parent_id"] in children}
                if expanded == children:
                    break
                children = expanded
            concepts = [c for c in concepts if c["id"] in children]
        return sorted(
            concepts, key=lambda concept: (-concept["importance"], concept["title"], concept["id"])
        )
