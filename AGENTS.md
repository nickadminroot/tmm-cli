# tmm-cli agent rules

Public thin client for the TMM remote execution service. This is the only
customer-facing executable of the TMM project: it bundles authored inputs,
sends them to the private `tmm-server` over HTTPS, polls run status, and
publishes returned artifacts locally.

## Local constraints
- This repository is PUBLIC by design. Never place implementation source,
  private package names, component SHAs, checkout URLs, or server deployment
  files here.
- The client is a thin transport/publication layer only: no parsing beyond
  Markdown dependency discovery (goldmark), no local fallback execution.
- Every domain command requires `--output`. No token flags: credentials come
  only from `TMM_API_TOKEN`.
- Text contract: stdout carries only final written paths or fixed quota
  fields. Diagnostics go to stderr with stable exit classes (see README).
- Never log the Authorization header, even in debug builds.
- Run `go test ./...` before committing.
