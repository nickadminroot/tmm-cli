# tmm-cli agent guide

Public thin client for the TMM remote execution service. It sends authored
inputs to the service over HTTPS and publishes returned artifacts locally.
Calculation, Mathcad, Markdown, Scene v2, and KOMPAS plan routes are
synchronous and tokenless. KOMPAS CDW creation obtains a server-signed plan
and sends it to the installed or portable localhost KOMPAS Renderer. Mathcad 15 XMCD
creation uses the direct server endpoint and never needs the local renderer.

Read [`README.md`](README.md) before changing the client; it is the consumer
contract for commands, environment variables, output, and exit classes.

Keep this application a thin transport and publication layer. Markdown
rendering, mechanism classification, linkage generation, worksheet/XMCD
compilation, and plan compilation remain server-side. KOMPAS commands transport
a signed plan to the running native renderer; they do not solve or render on
the client.

## Public-repository boundary

This repository is public by design. Keep private implementation, component
SHAs, checkout URLs, and server deployment files outside it. Keep local
fallback execution out of the client.

`kompas-renderer/` owns the public native renderer source, COM-free tests,
locked Python dependencies, and Windows installer/portable packaging scripts.
Release public keys and exact allowed origins are build inputs; private signing
keys never enter this repository or its artifacts. Installed and portable
artifacts use the same strict release config, fixed port, mutex, and trust key.

## Transport and output invariants

- Require `--output` for every artifact-producing command.
- Keep stdout limited to final written paths.
- Send diagnostics to stderr and preserve the exit classes in the README.
- Send the model YAML and Markdown bytes supplied by the user unchanged.
  For `md` and `kompas page`, collect only visible explicit scene bindings
  (`tmm-scene`, `tmm-scale`, `tmm-segment`, `tmm-lever`) from adjacent local
  `.scene.json`/`.render.json` files; skip fenced and inline code. Missing
  files remain eligible for the server's generated-catalog fallback, while
  unreadable or non-object files fail locally. Generic `tmm linkage` publishes
  the free declared result tree, including `mathcad/worksheet.xmcd` and
  `mathcad/preview.txt`.
- `tmm xmcd` sends the authored YAML to `POST /v1/linkage/xmcd`, validates the
  `application/x-mathcad+xml` response, and publishes only the XMCD bytes.
- Treat uploaded inputs and returned artifacts as transport data, not as
  client-side solver state.
- `tmm linkage`, `tmm render`, and `tmm svg` send the v1 envelope and bundle
  ZIP to `POST /v1/compute`; require `application/zip`, `_tmm-result.json`,
  and a matching `X-Result-Sha256` before publication.

YAML and arbitrary JSON KOMPAS commands obtain a fresh renderer challenge, call
their synchronous public plan endpoint, validate the returned plan ZIP, and
send only the signed plan to the local renderer. They never quote YAML or
reserve a mechanism.

XMCD is a free direct request and has no renderer challenge, mechanism quote,
allowance flag, or balance reservation. Require the native XML content type and
bounded non-empty bytes before publishing.

Require protocol-v2 renderer capabilities, validate the signed plan envelope and
its challenge binding, and verify the renderer CDW response checksum before
publishing bytes. Unavailable, incompatible, busy, and integrity renderer
failures use exit code `6`.

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
`pnpm db:init -- dev` and `pnpm dev`; installed CLI invocations use public
endpoints without credentials.

## Checks

`skills/` contains the portable workflow and drawing guides, standalone
metric-synthesis runtime, and bundled Mathcad examples/library. Preserve complete
skill directories, including references, examples, assets, and vendor licenses.
After changing synthesis code, run `uv sync --extra dev --locked`,
`uv run --locked pytest -q ../tests` and `uv run --locked ruff check .` from
`skills/metric-synthesis/scripts`.

Before committing, update the public README when a command, environment
variable, output field, or exit class changes, then run both Go commands above.

After changing `kompas-renderer/`, synchronize its locked environment and run
the COM-free suite from that directory:

```bash
uv sync --locked
uv run --locked python -m unittest
```

Run packaging tests on Linux. Building the portable ZIP requires 64-bit
Windows; building the setup additionally requires Inno Setup. Live acceptance
of either form requires KOMPAS-3D and an interactive desktop session.
