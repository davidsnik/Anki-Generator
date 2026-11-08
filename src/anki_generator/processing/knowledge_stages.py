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

from .state import entity_data


class KnowledgeStages:
    def _knowledge(self) -> None:
        analyses: list[dict[str, Any]] = []
        chunk_limit = min(max(int(self.config.get("source_chunk_characters", 18000)), 2000), 48000)
        sections_total = 0
        for doc in self.documents:
            for page in doc["extraction"]["pages"]:
                text = page["text"]
                text_sections = sum(
                    bool(text[n : n + chunk_limit].strip())
                    for n in range(0, max(len(text), 1), chunk_limit - 300)
                )
                sections_total += max(
                    1, text_sections + len(page.get("visual_interpretations", []))
                )
        self._stage("knowledge", total=sections_total)
        for document in self.documents:
            for page in document["extraction"]["pages"]:
                text = page["text"]
                visual = page.get("visual_interpretations", [])
                # Even a single extremely long text page is segmented with overlap.
                segments = [
                    text[n : n + chunk_limit]
                    for n in range(0, max(len(text), 1), chunk_limit - 300)
                ]
                sections = [(segment, []) for segment in segments if segment.strip()]
                sections.extend(("", [item]) for item in visual)
                if not sections:
                    sections = [("", [])]
                for section_index, (segment, section_visual) in enumerate(sections):
                    payload = {
                        "course": {
                            "name": self.course["name"],
                            "description": self.course["description"],
                        },
                        "document_id": document["id"],
                        "filename": document["filename"],
                        "role": document["category"],
                        "authority": document["authority"],
                        "linked_document_id": document["linked_document_id"],
                        "role_influence": self.config.get("role_influence", {}),
                        "page_number": page["page_number"],
                        "text": segment,
                        "visual_interpretations": section_visual,
                        "available_regions": [
                            {"region_id": r["id"], "bbox": r["bbox"]} for r in page["regions"]
                        ],
                        "extraction_warnings": page["warnings"],
                    }
                    result = self._call(
                        "knowledge",
                        f"{document['id']}:{page['page_number']}:{section_index}",
                        payload,
                        DocumentKnowledge,
                    )
                    for warning in result.warnings + result.conflicts:
                        self._warning(f"{document['filename']}: {warning}")
                    for concept in result.concepts:
                        if result.conflicts:
                            concept.uncertain = True
                            concept.conflicts.extend(result.conflicts)
                        problems = self.evidence.validate(concept.sources)
                        if problems:
                            concept.uncertain = True
                            concept.conflicts.extend(problems)
                    analyses.append(
                        {
                            "document_id": document["id"],
                            "role": document["category"],
                            "authority": document["authority"],
                            **result.model_dump(mode="json"),
                        }
                    )
        self._stage("knowledge", complete=True)
        self._load_concepts()
        existing = [
            {
                "key": c["metadata_json"].get("canonical_key", c["id"]),
                "title": c["title"],
                "kind": c["kind"],
            }
            for c in self.concepts
        ]
        # Hierarchical consolidation bounds the number of full candidate records
        # per request while retaining assumptions/evidence in every intermediate.
        level = analyses
        round_number = 0
        while len(json.dumps(level)) > 400000 and len(level) > 1:
            reduced = []
            for offset in range(0, len(level), 8):
                merged = self._call(
                    "consolidation",
                    f"level-{round_number}-{offset}",
                    {
                        "analyses": level[offset : offset + 8],
                        "existing_keys": existing,
                        "role_influence": self.config.get("role_influence", {}),
                    },
                    CourseKnowledge,
                )
                reduced.append(merged.model_dump(mode="json"))
            if len(reduced) >= len(level):
                raise ValueError(
                    "Course synthesis exceeds the configured context budget. Process "
                    "a smaller topic set."
                )
            level = reduced
            round_number += 1
        result = self._call(
            "consolidation",
            "course",
            {
                "course": self.course["name"],
                "analyses": level,
                "existing_keys": existing,
                "role_influence": self.config.get("role_influence", {}),
            },
            CourseKnowledge,
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
                concept.importance = candidate.importance
                concept.sources = [ref.model_dump(mode="json") for ref in candidate.sources]
                concept.relationships = [ids[k] for k in candidate.relationships if k in ids]
                concept.exercise_analysis = [
                    e
                    for e in exercise_records
                    if candidate.key in e.get("concepts", [])
                    or candidate.title in e.get("concepts", [])
                ]
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
        return concepts
