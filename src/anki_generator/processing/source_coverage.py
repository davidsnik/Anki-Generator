"""Independent original-evidence inventory and hierarchical competency coverage."""

from __future__ import annotations

import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from anki_generator.database.entities import Run
from anki_generator.database.pipeline_entities import SourceCoverageTarget
from anki_generator.processing.contracts import (
    CandidateConcept,
    CourseKnowledge,
    EvidenceReference,
    SourceAuditResult,
    SourceMatchingResult,
    TargetCoverageResult,
)
from anki_generator.services.semantic import SemanticIndex

from .state import digest, entity_data


class SourceCoverageStages:
    def _source_audit(self) -> None:
        if not self.options.source_audit:
            self._warning(
                "Independent source audit is disabled in this experiment; "
                "inventory coverage is not source completeness."
            )
            return
        tasks = []
        for document in self.documents:
            for page in document["extraction"]["pages"]:
                text = page["text"]
                step = max(
                    500,
                    min(self.options.source_chunk_characters, self.options.input_token_budget // 3),
                )
                for offset in range(0, len(text), step - 200):
                    tasks.append(
                        (document, page, f"text-{offset}", text[offset : offset + step], None)
                    )
                for region in page["regions"]:
                    if region.get("is_original_visual", True):
                        tasks.append((document, page, region["id"], "", region))
        self._stage("source_audit", total=len(tasks))

        def inspect(task):
            document, page, section, text, region = task
            payload = {
                "course": self.course["name"],
                "document_id": document["id"],
                "role": document["category"],
                "authority": document["authority"],
                "linked_document_id": document["linked_document_id"],
                "page_number": page["page_number"],
                "text": text,
                "visual_interpretations": [
                    v
                    for v in page.get("visual_interpretations", [])
                    if region and v["region_id"] == region["id"]
                ],
                "region_id": region["id"] if region else None,
                "bbox": region["bbox"] if region else None,
                "source_warnings": page.get("warnings", []),
                "human_verified_transcription": page.get("human_verified", False),
            }
            images = []
            if region:
                relative = (
                    region.get("storage_path")
                    or f"{document['extraction']['artifact_dir']}/{region['image_path']}"
                )
                images = [self.root / relative]
            result = self._call(
                "source_audit",
                f"{document['id']}:{page['page_number']}:{section}",
                payload,
                SourceAuditResult,
                images=images,
            )
            return result

        results = self._parallel(tasks, inspect)
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.metrics = {
                **run.metrics,
                "independent_inspection": {
                    "unresolved_findings": sum(len(result.unresolved) for result in results),
                    "inspection_units": len(tasks),
                    "pages_inspected": len(
                        {(document["id"], page["page_number"]) for document, page, *_ in tasks}
                    ),
                    "pages_available": sum(
                        len(document["extraction"]["pages"]) for document in self.documents
                    ),
                },
            }
            session.commit()
        targets = {}
        for result in results:
            for warning in result.warnings + result.unresolved:
                self._warning(warning)
            for target in result.targets:
                meaning = digest(
                    {
                        "title": " ".join(target.concept.title.casefold().split()),
                        "statement": " ".join(target.concept.statement.split()),
                        "assumptions": sorted(target.concept.assumptions),
                        "competency": " ".join(target.competency.split()),
                        "exercise_pattern": target.exercise_pattern,
                    }
                )[:16]
                key = f"{target.dimension}:{target.concept.key}:{meaning}"
                if key not in targets:
                    targets[key] = target
                else:
                    current = targets[key].concept
                    unique = {
                        json.dumps(ref.model_dump(mode="json"), sort_keys=True): ref
                        for ref in current.sources + target.concept.sources
                    }
                    current.sources = list(unique.values())
                    current.assumptions = list(
                        dict.fromkeys(current.assumptions + target.concept.assumptions)
                    )
                    current.conflicts = list(
                        dict.fromkeys(current.conflicts + target.concept.conflicts)
                    )
                    current.uncertain |= target.concept.uncertain
        self._stage("source_audit", complete=True)
        if not targets:
            self._warning(
                "Independent source inspection identified no learning targets; "
                "source coverage remains unresolved."
            )
            return
        concept_vectors = self._vectors(self.concepts, "concept") if self.concepts else {}
        concept_index = SemanticIndex(concept_vectors, measurements=self.measurements)
        target_objects = [
            {
                "id": key,
                "title": value.concept.title,
                "statement": value.concept.statement,
                "assumptions": value.concept.assumptions,
            }
            for key, value in targets.items()
        ]
        target_vectors = self._vectors(target_objects, "source_target")
        by_id = {concept["id"]: concept for concept in self.concepts}
        new_concepts = []
        mappings = {}
        self._stage("source_matching", total=len(targets))
        for key, target in targets.items():
            nearest = concept_index.search(
                target_vectors[key],
                limit=self.options.semantic_candidates,
                query_id=key,
                stage="source_matching",
                query_kind="source_target",
                candidate_kind="concept",
            )
            retrieved = [
                {
                    "key": by_id[cid]["metadata_json"].get("canonical_key", cid),
                    "id": cid,
                    "title": by_id[cid]["title"],
                    "kind": by_id[cid]["kind"],
                    "statement": by_id[cid]["description"],
                    "assumptions": by_id[cid]["metadata_json"].get("assumptions", []),
                    "similarity": score,
                }
                for cid, score in nearest
            ]
            result = self._call(
                "source_matching",
                key,
                {
                    "targets": [
                        {
                            "target_key": key,
                            **target.model_dump(mode="json"),
                            "concept": {
                                **target.concept.model_dump(mode="json"),
                                "sources": [
                                    ref.model_dump(mode="json")
                                    for ref in target.concept.sources[:3]
                                ],
                            },
                            "source_inventory": {
                                "total": len(target.concept.sources),
                                "hash": digest(
                                    [ref.model_dump(mode="json") for ref in target.concept.sources]
                                ),
                            },
                        }
                    ],
                    "retrieved_concepts": retrieved,
                },
                SourceMatchingResult,
            )
            match = next((item for item in result.matches if item.target_key == key), None)
            exact = next(
                (
                    c
                    for c in self.concepts
                    if c["metadata_json"].get("canonical_key")
                    == (match.concept_key if match else None)
                ),
                None,
            )
            distinct_dimension = exact is not None and (
                set(target.concept.assumptions)
                != set(exact["metadata_json"].get("assumptions", []))
                or (target.dimension == "assumption" and exact["kind"] != "assumption")
                or (
                    target.dimension in {"technique", "exercise_pattern"}
                    and exact["kind"] in {"theorem", "definition"}
                )
            )
            if exact is not None and match.relation == "same" and not distinct_dimension:
                mappings[key] = exact["id"]
            else:
                candidate = target.concept.model_copy(deep=True)
                candidate.key = f"source:{key}"
                candidate.parent_key = (
                    None  # target hierarchy remains independently retained below.
                )
                new_concepts.append(candidate)
                mappings[key] = candidate.key
            errors = self.evidence.validate(target.concept.sources)
            target.concept.uncertain |= bool(errors)
            target.concept.conflicts.extend(errors)
        self._stage("source_matching", complete=True)
        if new_concepts:
            existing = self._as_candidate_inventory()
            self._persist_concepts(
                CourseKnowledge(
                    concepts=existing + new_concepts, terminology=[], conflicts=[], unresolved=[]
                ),
                [],
            )
        by_key = {
            concept["metadata_json"].get("canonical_key", concept["id"]): concept["id"]
            for concept in self.concepts
        }
        parent_aliases: dict[str, list[str]] = {}
        for key, target in targets.items():
            parent_aliases.setdefault(target.concept.key, []).append(key)
        target_keys = {alias: keys[0] for alias, keys in parent_aliases.items() if len(keys) == 1}
        for target in targets.values():
            if (
                target.concept.parent_key
                and len(parent_aliases.get(target.concept.parent_key, [])) > 1
            ):
                self._warning(
                    "An independent source hierarchy has an ambiguous parent key; "
                    "its separate learning targets remain retained without an invented parent."
                )
        with self.sessions() as session:
            for key, target in targets.items():
                concept_id = mappings[key]
                concept_id = by_key.get(concept_id, concept_id)
                row = session.scalar(
                    select(SourceCoverageTarget).where(
                        SourceCoverageTarget.run_id == self.run_id,
                        SourceCoverageTarget.target_key == key,
                    )
                )
                if row is None:
                    row = SourceCoverageTarget(
                        id=str(uuid5(NAMESPACE_URL, f"{self.run_id}:source-target:{key}")),
                        course_id=self.course_id,
                        run_id=self.run_id,
                        target_key=key,
                        kind=target.dimension,
                        title=target.concept.title,
                        statement=target.concept.statement,
                    )
                    session.add(row)
                row.parent_key = target_keys.get(target.concept.parent_key)
                if row.parent_key == key:
                    row.parent_key = None
                row.importance = target.concept.importance
                row.sources = [ref.model_dump(mode="json") for ref in target.concept.sources]
                row.mapped_concept_ids = [concept_id]
                row.status = (
                    "uncertain"
                    if target.concept.uncertain or target.concept.conflicts
                    else "uncovered"
                )
                row.metadata_json = {
                    "competency": target.competency,
                    "exercise_pattern": target.exercise_pattern,
                    "assumptions": target.concept.assumptions,
                    "uncertain": target.concept.uncertain,
                    "conflicts": target.concept.conflicts,
                    "independent_from_initial_inventory": True,
                    "recovered_initial_omission": mappings[key] in {c.key for c in new_concepts},
                }
            session.commit()
        self._source_coverage_metrics()

    def _as_candidate_inventory(self) -> list[CandidateConcept]:
        id_to_key = {
            c["id"]: c["metadata_json"].get("canonical_key", c["id"]) for c in self.concepts
        }
        return [
            CandidateConcept(
                key=id_to_key[c["id"]],
                title=c["title"],
                kind=c["kind"],
                parent_key=id_to_key.get(c["parent_id"]),
                statement=c["description"],
                assumptions=c["metadata_json"].get("assumptions", []),
                relationships=[id_to_key[k] for k in c["relationships"] if k in id_to_key],
                importance=c["importance"],
                importance_reason=c["metadata_json"].get("importance_reason", ""),
                exercise_frequency=c["metadata_json"].get("exercise_frequency", 0),
                sources=[EvidenceReference.model_validate(r) for r in c["sources"]],
                uncertain=c["metadata_json"].get("uncertain", False),
                conflicts=c["metadata_json"].get("conflicts", []),
            )
            for c in self.concepts
            if c["metadata_json"].get("active_in_inventory", True)
        ]

    def _audit_source_targets(self, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self.sessions() as session:
            targets = [
                entity_data(row)
                for row in session.scalars(
                    select(SourceCoverageTarget).where(SourceCoverageTarget.run_id == self.run_id)
                )
            ]
        if not targets:
            return []
        card_vectors = self._vectors(cards, "card") if cards else {}
        target_vectors = self._vectors(
            [
                {
                    "id": t["target_key"],
                    "title": t["title"],
                    "statement": t["statement"],
                    "assumptions": t["metadata_json"].get("assumptions", []),
                }
                for t in targets
            ],
            "source_target",
        )
        index = SemanticIndex(card_vectors, measurements=self.measurements)
        by_id = {card["id"]: card for card in cards}
        self._stage("target_coverage", total=len(targets))
        gaps = []
        for target in targets:
            if target["metadata_json"].get("uncertain") or target["metadata_json"].get("conflicts"):
                gaps.append(target)
                continue
            nearest = index.search(
                target_vectors[target["target_key"]],
                limit=self.options.semantic_candidates,
                query_id=target["target_key"],
                stage="target_coverage",
                query_kind="source_target",
                candidate_kind="card",
            )
            retrieved = [by_id[cid] for cid, _ in nearest]
            compact_cards = [
                {
                    key: card[key]
                    for key in ("id", "question", "answer", "kind", "card_type", "concept_id")
                }
                for card in retrieved
            ]
            result = self._call(
                "target_coverage",
                f"{target['target_key']}:{digest(compact_cards)}",
                {
                    "targets": [
                        {
                            **{
                                key: target[key]
                                for key in ("kind", "title", "statement", "metadata_json")
                            },
                            "id": target["target_key"],
                        }
                    ],
                    "retrieved_cards": compact_cards,
                    "original_evidence": self.evidence.sources(
                        [EvidenceReference.model_validate(ref) for ref in target["sources"][:3]]
                    ),
                },
                TargetCoverageResult,
            )
            finding = next(
                (item for item in result.assessments if item.target_id == target["target_key"]),
                None,
            )
            valid_ids = (
                [cid for cid in finding.card_ids if cid in {card["id"] for card in retrieved}]
                if finding
                else []
            )
            status = finding.status if finding else "uncertain"
            if status == "covered" and not valid_ids:
                status = "uncovered"
            with self.sessions() as session:
                row = session.get(SourceCoverageTarget, target["id"])
                row.status, row.covered_card_ids = status, valid_ids
                row.metadata_json = {
                    **row.metadata_json,
                    "missing_aspects": finding.missing_aspects
                    if finding
                    else ["No assessment returned."],
                    "assessment_reason": finding.reason
                    if finding
                    else "The model omitted this target.",
                    "assessment_origin": "llm_judgment_not_human_ground_truth",
                }
                session.commit()
            if status != "covered":
                target["status"] = status
                target["metadata_json"] = {
                    **target["metadata_json"],
                    "missing_aspects": finding.missing_aspects
                    if finding
                    else ["No assessment returned"],
                    "assessment_reason": finding.reason if finding else "No assessment returned",
                }
                gaps.append(target)
        self._stage("target_coverage", complete=True)
        self._source_coverage_metrics()
        return gaps

    def _source_coverage_metrics(self) -> None:
        with self.sessions() as session:
            targets = list(
                session.scalars(
                    select(SourceCoverageTarget).where(SourceCoverageTarget.run_id == self.run_id)
                )
            )
            by_kind = {}
            for row in targets:
                group = by_kind.setdefault(
                    row.kind,
                    {"total": 0, "covered": 0, "partial": 0, "uncertain": 0, "uncovered": 0},
                )
                group["total"] += 1
                group[row.status] = group.get(row.status, 0) + 1
            from anki_generator.database.entities import Concept

            concepts = list(
                session.scalars(select(Concept).where(Concept.course_id == self.course_id))
            )
            nodes = {
                concept.id: {
                    "id": concept.id,
                    "parent_id": concept.parent_id,
                    "title": concept.title,
                    "kind": concept.kind,
                    "targets": 0,
                    "covered": 0,
                    "partial": 0,
                    "uncovered": 0,
                    "uncertain": 0,
                }
                for concept in concepts
                if concept.metadata_json.get("active_in_inventory", True)
            }
            for row in targets:
                visited = set()
                for concept_id in row.mapped_concept_ids:
                    current = concept_id
                    while current in nodes and current not in visited:
                        visited.add(current)
                        node = nodes[current]
                        node["targets"] += 1
                        node[row.status] += 1
                        current = node["parent_id"]
            for node in nodes.values():
                node["status"] = (
                    "uncovered"
                    if not node["targets"]
                    else ("covered" if node["covered"] == node["targets"] else "partial")
                )
            run = session.get(Run, self.run_id)
            run.metrics = {
                **run.metrics,
                "source_coverage": {
                    "targets_total": len(targets),
                    "covered": sum(t.status == "covered" for t in targets),
                    "mapped": sum(bool(t.mapped_concept_ids) for t in targets),
                    "unresolved": sum(t.status != "covered" for t in targets),
                    "by_kind": by_kind,
                    "hierarchy": [entity_data(t) for t in targets[:50]],
                    "hierarchy_truncated": len(targets) > 50,
                    "topic_rollup": list(nodes.values())[:100],
                    "topic_rollup_truncated": len(nodes) > 100,
                    "recovered_initial_omissions": sum(
                        t.metadata_json.get("recovered_initial_omission", False) for t in targets
                    ),
                    "inspection": {
                        "pages_total": sum(len(d["extraction"]["pages"]) for d in self.documents),
                        "source_independent": True,
                    },
                    "judgment_origin": "llm_audit_not_human_ground_truth",
                },
            }
            session.commit()
