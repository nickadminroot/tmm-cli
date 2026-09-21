# tmm-cli agent guide

Public thin client for the TMM remote execution service. It sends authored
inputs to the private server over HTTPS and publishes returned artifacts
locally. Account-scoped operations use the bearer token; public arbitrary-scene
resolution and CDW plan endpoints are explicitly tokenless. KOMPAS CDW
creation obtains a server-signed plan and sends it to the installed localhost
KOMPAS Renderer. Mathcad 15 XMCD creation uses the free direct server endpoint
and never needs the local renderer.

Read [`README.md`](README.md) before changing the client; it is the consumer
contract for commands, environment variables, output, and exit classes.

Keep this application a thin transport and publication layer. Markdown
rendering, mechanism classification, linkage generation, worksheet/XMCD
compilation, and plan compilation remain server-side. KOMPAS commands transport
a signed plan to the installed native renderer; they do not solve or render on
the client.

## Public-repository boundary

This repository is public by design. Keep private implementation, component
SHAs, checkout URLs, and server deployment files outside it. Keep local
fallback execution out of the client.

## Transport and output invariants

- Require `--output` for every artifact-producing command.
- Require `TMM_API_TOKEN` for every account-scoped API request, including
  loopback HTTP development URLs. Public arbitrary-scene endpoints are the
  only tokenless API exception. Keep tokens out of argv and URLs.
- Keep stdout limited to final written paths or the fixed fields of
`tmm mechanisms`.
- Send diagnostics, including mechanism quote information, to stderr and
preserve the exit classes in the README.
- Send the model YAML and Markdown bytes supplied by the user without local
  scene discovery or calculation. Generic `tmm linkage` publishes the free
  declared result tree, including `mathcad/worksheet.xmcd` and
  `mathcad/preview.txt`.
- `tmm xmcd` sends the authored YAML to `POST /v1/linkage/xmcd`, validates the
  `application/x-mathcad+xml` response, and publishes only the XMCD bytes.
- Treat uploaded inputs and returned artifacts as transport data, not as
  client-side solver state.

Legacy YAML KOMPAS commands first obtain a fresh renderer challenge, then quote
the exact model bytes. They remain account-scoped for compatibility. Arbitrary
`.scene.json` and `.render.json` commands obtain the same challenge, call the
public plan endpoint with the challenge, validate the returned plan ZIP, and
send only the signed plan to the local renderer; they never quote YAML or
reserve a mechanism.

XMCD is a free direct request and has no renderer challenge, mechanism quote,
allowance flag, or balance reservation. Require the native XML content type and
bounded non-empty bytes before publishing.

Require protocol-v2 renderer capabilities, validate the legacy account-scoped KOMPAS result
manifest and member checksum, validate the signed plan envelope and its
run/challenge binding, and verify the renderer CDW response checksum before
publishing bytes. Unavailable, incompatible, busy, and integrity renderer
failures use exit code `6` and do not emit resume guidance. Legacy account-scoped
KOMPAS runs are not resumable through `tmm resume`.

Never log the `Authorization` header, including in debug builds.

## Local workflow

From `apps/tmm-cli/`, use the Go toolchain for local builds and tests:

```bash
go build ./...
go test ./...
```

Exercise a changed domain command with a local API fixture or development
service. Confirm stdout, stderr, exit code, output path, and transport-failure
behavior; do not substitute a local calculation fallback.

Repo-local regeneration discovers `.tmm/dev/credentials.json` only after
`pnpm db:init -- dev`, `pnpm dev`, and `pnpm dev -- credentials`; installed CLI
invocations require an explicit `TMM_API_TOKEN` only for account-scoped
commands. `tmm resolve`, `tmm kompas scene-json`, and
`tmm kompas render-json` use the public endpoints without a token.

## Checks

`skills/` contains the portable CLI/YAML guides and standalone metric-synthesis
runtime. Preserve complete skill directories, including references and examples.
After changing synthesis code, run `uv sync --extra dev --locked`,
`uv run --locked pytest -q ../tests` and `uv run --locked ruff check .` from
`skills/metric-synthesis/scripts`.

Before committing, update the public README when a command, environment
variable, output field, or exit class changes, then run both Go commands above.
