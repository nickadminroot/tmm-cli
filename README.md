# tmm-cli

Public thin client for the TMM remote execution service. It sends authored
inputs to the private server over HTTPS and publishes returned artifacts
locally. KOMPAS CDW creation obtains a server-signed plan and sends it to the
installed localhost KOMPAS Renderer only after the server has accepted the paid run.

## Commands

| Command | Result |
| --- | --- |
| `tmm linkage INPUT --output DIR` | Run linkage analysis and write the generic result tree, including free `mathcad/worksheet.xmcd` and `mathcad/preview.txt`. |
| `tmm xmcd INPUT --output FILE.xmcd` | Request the free native Mathcad 15 XMCD output and write the returned bytes. |
| `tmm md MODEL.yaml DOCUMENT.md --format A1\|A2\|A3 --output FILE [--source-path PATH]` | Render a Markdown document against the model and write the preview ZIP. The two input files are sent as-is; `PATH` is an optional logical publication path used to resolve relative scene references. |
| `tmm render INPUT --output FILE [--scale N \| --target-max-side N]` | Render one Scene v2 document. |
| `tmm svg INPUT --output FILE [--format svg\|png] [render/SVG/PNG options]` | Produce an SVG or PNG preview. |
| `tmm kompas scene MODEL.yaml SCENE_NAME --output FILE [--scale N] [--accept-new-mechanism]` | Generate the named linkage scene, render it through the installed KOMPAS Renderer, and write the CDW. |
| `tmm kompas page MODEL.yaml DOCUMENT.md --page N --format A1\|A2\|A3 --output FILE [--accept-new-mechanism]` | Generate and render one Markdown page through the installed KOMPAS Renderer, then write the CDW. |
| `tmm mechanisms` | Print the mechanism balance and registry fields. This command is read-only. |
| `tmm resume UUID --output PATH` | Resume a resumable free operation or accepted native-XMCD legacy run and write its result. |
| `tmm cancel UUID` | Cancel a submitted run. |
| `tmm version` | Print the client version. |

The `linkage` command materializes the free generic result tree under `DIR`.
The server owns linkage analysis and the native XMCD compiler; the client
writes declared bytes unchanged. `tmm xmcd` is the dedicated free endpoint for
the same native XMCD output and does not use KOMPAS.

## Mechanism admission

KOMPAS commands first obtain a fresh protocol-v2 challenge from the local
KOMPAS Renderer, then quote the exact model bytes. An exact built-in stock
model proceeds without a credit and is not added to the user registry. Known
mechanisms also proceed without a credit. A new mechanism requires
`--accept-new-mechanism`; without it the CLI exits before submitting the paid
run. An insufficient balance or inactive account also stops before submission.

`tmm xmcd` sends the authored YAML directly to `POST /v1/linkage/xmcd` and
receives `application/x-mathcad+xml`. It has no mechanism quote, allowance
flag, balance reservation, or local renderer dependency.

Physical inputs must declare `schema: linkage/v2`; the CLI does not convert
legacy YAML. `tmm mechanisms` prints each row's `descriptor_version`.
Version-one rows are retained history, not recognition candidates for v2.
An earlier activation can therefore require a new explicit admission; existing
balances, payments, history, and downloadable artifacts remain unchanged.

The server accepts only the named `SCENE_NAME` from the generated linkage
catalog. Markdown page requests send exactly `mechanism`, `document`, and
`options` multipart fields. Scene requests send exactly `mechanism` and
`options`; the server generates and verifies the selected scene.
For `tmm md`, `--source-path` is sent as `options.source_path` and is not read as a local file. Use the document's logical path inside the publication tree (for example, `kinematics/velocity-analysis.md`) when its scene directives use bare scene names. If omitted, the server uses `input/document.md`.

## Environment

| Variable | Contract |
| --- | --- |
| `TMM_API_TOKEN` | Required for every API URL, including loopback development URLs. Keep it in the environment, never argv, YAML, logs, or a URL. |
| `TMM_API_URL` | Required for repository development/source builds; release builds embed the production HTTPS URL. Plain HTTP is accepted only for loopback hosts. |
| `TMM_KOMPAS_RENDERER_URL` | Optional localhost KOMPAS Renderer URL; defaults to `http://127.0.0.1:17342`. The CLI accepts only plain HTTP `localhost` or `127.0.0.1` URLs with an explicit port. |

KOMPAS plan ZIPs, manifests, checksums, signed envelopes, run IDs, and
challenge bindings are verified before a plan reaches the local renderer; the
API token is never sent to that renderer. The renderer response must be
non-empty CDW bytes with the required SHA-256 checksum. If the local renderer
fails after the server succeeds, stderr states that the mechanism is already
activated and a retry will not charge it again. Renderer failures use exit code
`6` and do not emit resume guidance.

The dedicated XMCD command receives one validated XML document and writes the
bytes unchanged. Generic linkage output carries the same native XMCD as a
declared artifact alongside the deterministic text preview; no worksheet
interchange document exists in the CLI contract.

Repository development has a random persisted HTTPS port. Set `TMM_API_URL` to
the `apiUrl` in `.tmm/dev/credentials.json` and set `TMM_API_TOKEN` explicitly;
repo-local regeneration helpers discover both values from the mode-0600
manifest after `pnpm db:init -- dev`, `pnpm dev`, and `pnpm dev -- credentials`.

## Release installation

Public releases are published in
[`tmm-cli`](https://github.com/nickadminroot/tmm-cli/releases) with tags
`tmm-cli/v*`. Each release contains archives for Linux, macOS, and Windows on
`amd64` and `arm64`, plus `checksums.txt`. Verify the archive checksum before
extracting:

```bash
archive="$(find . -maxdepth 1 -type f -name 'tmm-cli_*' -print -quit)"
test -n "$archive"
filename="$(basename "$archive")"
grep -F "  $filename" checksums.txt | sha256sum -c -
```

The checksum file lists every release archive; checking it without the filename
filter requires downloading all of them. On macOS pipe the matching row to
`shasum -a 256 -c -`; on Windows compare `Get-FileHash` with the matching row.

The release embeds the production HTTPS API URL. `TMM_API_URL` is only needed
for an explicit endpoint override; plain HTTP remains valid only for
`localhost` and `127.0.0.1`.

## Diagnostics

Failed remote calculations print the server diagnostic to stderr: the stable
error code and message, pipeline stage, input field and YAML position when
available, followed by ordered `[пройден]`, `[ошибка]`, or `[пропущен]` steps.
Successful commands keep stdout reserved for published paths or the fixed
fields of `tmm mechanisms`.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Success. |
| `2` | Usage or local input error. |
| `3` | Authentication, account, or mechanism-balance failure. |
| `4` | Remote domain failure. |
| `5` | Resumable free-operation transport failure; output includes `Run ID:` and `Resume:` lines. |
| `6` | Server, worker, or KOMPAS Renderer failure. |

`result_expired` and `result_lost` are reported as distinct remote domain
errors. A pending refund makes the corresponding unused balance zero for new
mechanism admissions; it does not block free operations or CDW exports for
already registered mechanisms. Such a new paid admission fails with
`mechanism_balance_exhausted`.

## AI-agent skills

The portable installation, security, command, and synthesis-to-YAML workflow
is documented in this public [CLI and skills repository](https://github.com/nickadminroot/tmm-cli/tree/main/skills).
Install a complete skill directory with its references, examples, and (for
`metric-synthesis`) the standalone `scripts/` runtime.

- [`tmm-cli`](skills/tmm-cli/SKILL.md): installation, authentication, commands and diagnostics.
- [`tmm-yaml`](skills/tmm-yaml/SKILL.md): physical YAML authoring and complete examples.
- [`metric-synthesis`](skills/metric-synthesis/SKILL.md): numerical dimension synthesis with its standalone Python runtime.

`tmm --help` and `tmm help` show both the public repository and skills links,
without requiring an API token or a network request.

## Boundary

The client owns transport, polling, plan/result integrity checks, and local
publication. It owns no calculation logic; computation happens in the private
service or the installed KOMPAS Renderer.
