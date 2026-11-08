# Troubleshooting

- **Missing uv/Node/pnpm:** install the documented prerequisites, then run install.sh.
  Ordinary run.sh use after a completed installation does not need Node.
- **Frontend not built:** run install.sh. Development uses dev.sh (backend8000,
  Vite5173); production serves the built assets on8765.
- **Port already in use:** stop the previous instance or pass --port to run.sh.
  Use a separate data directory for a second backend instance.
- **Connection refused:** confirm the backend printed its loopback URL and is still
  running. Nonloopback binding is intentionally rejected.
- **Invalid local session/CSRF:** reload the page after restarting the backend.
- **API key unavailable after restart:** session keys are intentionally forgotten.
  Re-enter the key or use a working secure OS store. Locked/unavailable stores
  fall back to session storage; keys are never written to SQLite.
- **Authentication/billing/model failure:** use Settings connection test, check the
  selected model/account/project and API credits. Permanent errors do not retry
  endlessly. A ChatGPT subscription is separate from API billing.
- **Paused/failed run:** inspect its stage/error/warnings, correct configuration and
  resume or retry. Saved responses remain reusable. After source role/hash/link
  changes start a new run; old snapshots intentionally cannot silently change.
- **PDF failure or tiny text layer:** inspect original tiles and warnings. Scans,
  diagrams and mathematical text need visual analysis; local extraction alone
  does not resolve them. Unprocessed regions remain explicit.
- **Very long page exceeds limits:** increase relevant page/region/total-pixel limits
  in Settings or split the source into smaller PDFs. Each tile remains bounded.
- **Office equation/chart missing:** native Office layouts are not faithfully
  rendered. Export the original DOCX/PPTX to PDF and import the PDF.
- **No eligible Anki cards:** review/approve cards and resolve failed checks. Manual
  unverified approval requires a human rationale; duplicate/failed cards remain blocked.
- **Changed cards lost verification:** expected: checks refer to exact revisions.
  Reverify the new revision or provide an explicit human-review rationale.
- **Missing source image:** reprocess its document. Export fails rather than shipping
  a broken image reference.
- **Anki duplicated or did not update notes:** inspect note type/GUIDs/import settings;
  see [export behavior](anki-export.md). Restore an Anki backup if necessary.
- **Restricted test environment:** some sandboxes block local thread/event-loop or
  browser sockets. Run local HTTP/browser tests in an environment that permits
  loopback sockets. Never report blocked verification as passed.
