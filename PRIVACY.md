# Privacy and repository content

This repository is public and contains the reviewed application source, architecture documentation, and a small set of curated RAG references.

## Never commit

- API keys, access tokens, `.env` files, or private deployment identifiers. Use `.env.example` and `frontend/.openai/hosting.example.json` as templates.
- Local databases, generated Excel/Word outputs, logs, virtual environments, caches, or raw daily-review/portfolio records.
- Local user names, home-directory paths, account credentials, or unreviewed personal source files.
- The separately maintained source checkout `review-cockpit-site/`; the reviewed frontend copy is under `frontend/`.

## Reviewed reference material

- `docs/rag/*.md` contains curated reference notes. Copies in this repository omit machine-local `source_path` metadata and use repository-relative Markdown links.
- The root `延边刺客短线打板体系.docx` is included as the backend's current manual RAG import source. Its document creator field is empty; it contains no local filesystem path.
- Raw spreadsheets, other Word files, and the rest of the local Obsidian archive remain excluded.

The reviewed items were approved for this repository provided that identifying local metadata is removed. This is not blanket approval for additional personal records. Before each push, inspect the exact staged diff and scan for credentials, contact details, account identifiers unrelated to the public source configuration, and local paths.
