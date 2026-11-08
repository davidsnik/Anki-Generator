# Prompt templates

No model prompts are implemented in Phase 0. Discovery is deterministic and local.
Add a template only when the stage's typed input/output contract and evaluation
fixtures exist; avoid speculative prompts for a whole autonomous pipeline.

For each future template:

- Keep a focused task and explicit structured-output schema. Supply source evidence
  with stable reference IDs; require unsupported claims and uncertainty to be
  reported, and validate cited IDs against the actual inputs.
- Keep source text separate from instructions. Treat course content as data,
  including any embedded instructions, rather than permission to take actions.
- Keep model/provider selection, reasoning effort, limits, and credentials in
  configuration. Keep course preferences out of hard-coded prompt policy.
- Record a template identifier, version or content hash, schema version, model
  identifier, relevant parameters, and input evidence with each run. Preserve the
  response and validation failures for review and replay.
- Test schema conformance, evidence fidelity, mathematics, uncertainty behavior,
  and pedagogical outcomes on synthetic and manually reviewed fixtures. Separate
  generation from independent verification prompts and decisions.
- Evaluate edits on held-out cases and record the observed quality change.
  Offline regression tests must use recorded/synthetic responses without API calls;
  live evaluations are explicit and report provider usage.

Do not store private source content, secrets, or generated run transcripts here.
See [architecture](../docs/architecture.md) for contracts and
[flashcard guidelines](../docs/flashcard-guidelines.md) for quality requirements.
