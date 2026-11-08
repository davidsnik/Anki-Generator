# Roadmap and evaluation

## Implemented application

The repository now contains the local GUI, persistent course/source/card management,
bounded multimodal-ready ingestion, course synthesis, generation, independent
quality stages, durable jobs, source-aware review and real Anki export. The original
Phase0 discovery feature is retained. See [requirements](requirements.md) and
[architecture](architecture.md) for scope and [testing](testing.md) for verification.

Completed work includes:
- Locked Python/frontend installation and Linux launch/development commands.
- Source roles/authority/linking, page geometry/visuals, long-page segmentation and
  local extraction with explicit Office limitations.
- Typed model outputs, role-aware hierarchical concepts, exercise competencies,
  independent evidence/quality checks, bounded repair/deduplication/coverage.
- Durable stages/checkpoints, reuse, pause/cancel/resume/retry and recovery.
- Card/source inspection, history, decisions, model/key/preferences GUI and export.

## Next priorities

1. **Manually reviewed quality corpus.** Expand synthetic fixtures into a legally
   redistributable set across probability, analysis, programming and circuits.
   Have domain reviewers annotate learning targets, source regions, difficult
   notation, accepted cards and deliberate defects. Keep a held-out split. Define
   factual accuracy, target coverage, ambiguity, redundancy and human-acceptance
   denominators and publish reviewer agreement. Controlled tests do not replace this.
   Deliverable: versioned annotated corpus and scoring report. Acceptance: each
   subject has reviewed sources/cards, a held-out split and reproducible metrics.
2. **Live-provider evaluation.** Run explicit opt-in small course evaluations with
   configured keys; compare stage models/reasoning/visual approaches. Record versions,
   source evidence, defects and usage. Acceptance: measured accuracy and known limits,
   not a model's self-reported confidence.
   Deliverable: reproducible opt-in evaluation command and dated comparison report.
3. **Real Anki compatibility matrix.** Import edited/repeated packages into disposable
   collections across supported Anki versions and update settings. Check review
   history, cloze changes, media and manual Anki edits; document exact tested settings.
   Deliverable: version/settings matrix with repeatable import cases. Acceptance:
   stable-note updates and any scheduling/manual-edit effects are recorded per case.
4. **Document fidelity.** Expand difficult handwriting and dense-math fixtures, model
   disagreements and Office-native conversion options. Add another parser only when
   reviewed failures justify it; preserve original-region inspection.
   Deliverable: difficult-format regression corpus and parser comparison. Acceptance:
   every added fixture retains source coordinates and flags omitted/uncertain content;
   improvements are measured against human transcriptions and existing regressions.
5. **Large-course reliability/performance.** Measure representative courses, improve
   concept reconciliation and bounded synthesis, add targeted retrieval where needed,
   and harden crash boundaries/provider idempotence. Preserve quality gates and reuse.
   Deliverable: reproducible scale benchmark and crash-injection scenarios. Acceptance:
   documented memory/time/call counts, resumable checkpoints, no lost human edits and
   no repeated expensive work for unchanged completed stages.
6. **Review ergonomics.** Add evaluated shortcuts/bulk review and optional true image
   occlusion only with tested masks/media/templates; never label ordinary image cards
   as occlusion. Direct Anki integration remains optional and requires explicit consent.
   Deliverable: tested keyboard/bulk-review flows and a separately scoped occlusion
   design if pursued. Acceptance: decisions apply to the intended card revisions,
   remain auditable and undoable, and any occlusion package passes real mask/media
   and disposable-collection import tests.

Each new stage/contract/identity change must include relevant tests, migration or
prompt version changes, measured behavior and accurate documentation. Critical
unresolved mathematics or missing evidence always blocks automatic verification.
