# tmm-cli

Public thin client for the TMM remote execution service. It sends authored
inputs to the service over HTTPS and publishes returned artifacts locally.
Calculation, Mathcad, Markdown, Scene v2, and KOMPAS plan routes are
synchronous public contracts; no account token, quote, balance, or admission
step is required. KOMPAS CDW creation obtains a server-signed plan and sends
it to the installed localhost KOMPAS Renderer.

## Commands

| Command | Result |
| --- | --- |
| `tmm linkage INPUT --output DIR` | Run linkage analysis and write the generic result tree, including free `mathcad/worksheet.xmcd` and `mathcad/preview.txt`. |
| `tmm xmcd INPUT --output FILE.xmcd` | Request the free native Mathcad 15 XMCD output and write the returned bytes. |
| `tmm md MODEL.yaml DOCUMENT.md --format A1\|A2\|A3 --output FILE [--source-path PATH]` | Render a Markdown document against the model and write the preview ZIP. Explicit visible scene bindings upload adjacent local `.scene.json`/`.render.json` objects; missing files keep the generated-scene fallback. |
| `tmm render INPUT --output FILE [--scale N \| --target-max-side N]` | Resolve a high-level scene through the public compute route and write its result. |
| `tmm resolve INPUT.scene.json --output FILE.render.json` (alias `tmm render-json`) | Resolve arbitrary high-level scene JSON to a Scene v2 `.render.json` document; public and tokenless. |
| `tmm svg INPUT --output FILE [--format svg\|png] [render/SVG/PNG options]` | Produce an SVG or PNG preview. |
| `tmm kompas scene MODEL.yaml SCENE_NAME --output FILE [--scale N]` | Generate the named linkage scene, render it through the installed KOMPAS Renderer, and write the CDW. |
| `tmm kompas page MODEL.yaml DOCUMENT.md --page N --format A1\|A2\|A3 --output FILE [--source-path PATH]` | Generate and render one Markdown page through the installed KOMPAS Renderer, uploading explicit adjacent local scene objects when present. |
| `tmm kompas scene-json INPUT.scene.json --output FILE.cdw [--scale N \| --target-max-side N]` | Render arbitrary high-level scene JSON to CDW through the public plan endpoint and local Renderer; tokenless. |
| `tmm kompas render-json INPUT.render.json --output FILE.cdw` | Render arbitrary resolved Scene v2 JSON to CDW through the public plan endpoint and local Renderer; tokenless. |
| `tmm version` | Print the client version. |

The `linkage` command materializes the free generic result tree under `DIR`.
The server owns linkage analysis and the native XMCD compiler; the client
writes declared bytes unchanged. `tmm xmcd` is the dedicated free endpoint for
the same native XMCD output and does not use KOMPAS.

All calculation and render commands are tokenless. `tmm linkage`, `tmm render`,
and `tmm svg` send a v1 envelope plus the authored ZIP to `POST /v1/compute`;
the response is a validated `application/zip` with `_tmm-result.json` and an
`X-Result-Sha256` header. `tmm resolve` posts the authored high-level scene to
`POST /v1/scenes/resolve` and writes the returned Scene v2 document unchanged.
`tmm xmcd` posts YAML to `POST /v1/linkage/xmcd` and receives native
`application/x-mathcad+xml`. `tmm md` posts its Markdown multipart to
`POST /v1/linkage/markdown/render`.

YAML KOMPAS commands obtain a fresh local Renderer challenge and call the
synchronous `POST /v1/linkage/cdw/scene` or `/v1/linkage/cdw/page` route. JSON
KOMPAS commands call `POST /v1/cdw/scene` or `/v1/cdw/render`. Every plan is a
signed ZIP; the client checks its manifest, operation, job/challenge binding,
and then sends only `plan.json` to the loopback Renderer. No quote, balance,
registry admission, or account state is read. Physical inputs must declare
`schema: linkage/v2`; the CLI does not convert legacy YAML.

The server accepts only the named `SCENE_NAME` from the generated linkage
catalog for the YAML command. Markdown requests always send
`mechanism`, `document`, and `options`; when the document visibly references a
local scene file, they also send an optional `scenes` JSON object mapping the
directive's canonical path (for example `velocity-plan.scene.json`) to the
authored JSON object. The file itself is read relative to the Markdown file.
Fenced and inline-code examples are
ignored. A missing local file is left for the generated catalog fallback, while
an unreadable or non-object file is a local input error. Uploaded scenes take
priority over generated scenes at the same logical key. Scene requests send
exactly `mechanism` and `options`; the server generates and verifies the
selected scene. Public JSON requests are independent: `/v1/scenes/resolve`
accepts one high-level JSON object, while `/v1/cdw/scene` accepts
`{"scene": OBJECT, "options": {"version": 1, "agent_challenge": STRING,
...}}` and `/v1/cdw/render` accepts the same envelope with `"render": OBJECT`.
The CDW endpoints return a signed plan ZIP (`application/zip`), not a drawing;
the installed local Renderer creates the `.cdw`.
For `tmm md` and `tmm kompas page`, `--source-path` is sent as
`options.source_path` and is not read as a local file. Use the document's
logical path inside the publication tree (for example,
`kinematics/velocity-analysis.md`) when generated scenes are referenced by
bare names. Local scene files are still read beside the supplied Markdown
file; their upload keys remain the exact directive names. If omitted, the
server uses `input/document.md`.

## Environment

| Variable | Contract |
| --- | --- |
| `TMM_API_URL` | Required for repository development/source builds; release builds embed the production HTTPS URL. Plain HTTP is accepted only for loopback hosts. |
| `TMM_KOMPAS_RENDERER_URL` | Optional localhost KOMPAS Renderer URL; defaults to `http://127.0.0.1:17342`. The CLI accepts only plain HTTP `localhost` or `127.0.0.1` URLs with an explicit port. |

KOMPAS plan ZIPs, manifests, checksums, signed envelopes, and challenge
bindings are verified before a plan reaches the local renderer. The renderer response must be
non-empty CDW bytes with the required SHA-256 checksum. If the local renderer
fails after the server succeeds, stderr reports the renderer failure. Renderer
failures use exit code `6`.

The dedicated XMCD command receives one validated XML document and writes the
bytes unchanged. Generic linkage output carries the same native XMCD as a
declared artifact alongside the deterministic text preview; no worksheet
interchange document exists in the CLI contract.

Repository development has a random persisted HTTPS port. Set `TMM_API_URL` to
the `apiUrl` in `.tmm/dev/credentials.json` after `pnpm db:init -- dev` and
`pnpm dev`; no account credential is needed by this CLI.

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
`localhost` and `127.0.0.1`. Public JSON endpoints still use the same base URL,
but do not add an `Authorization` header.

## Diagnostics

Failed remote calculations print the server diagnostic to stderr: the stable
error code and message, pipeline stage, input field and YAML position when
available, followed by ordered `[пройден]`, `[ошибка]`, or `[пропущен]` steps.
Successful commands keep stdout reserved for published paths.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Success. |
| `2` | Usage or local input error. |
| `3` | Reserved for an upstream authentication/account error; supported CLI routes do not initiate account requests. |
| `4` | Remote domain failure. |
| `5` | Transport failure; retry the synchronous command. |
| `6` | Server, worker, or KOMPAS Renderer failure. |

`result_expired` and `result_lost` are reported as distinct remote domain
errors. Synchronous public calculations do not emit run IDs or resume
instructions.

## AI-agent skills

The portable installation, security, command, and coursework workflow
is documented in this public [CLI and skills repository](https://github.com/nickadminroot/tmm-cli/tree/main/skills).
Before each stage, install every skill relevant to that stage as a complete
directory inside the current working project. Preserve its `references`,
`examples`, `assets`, `scripts`, and `vendor` content; copying only `SKILL.md`
is insufficient. Read each installed `SKILL.md` and consult it and its routed
resources throughout the work.

- [`tmm-cli`](skills/tmm-cli/SKILL.md): installation, commands and diagnostics.
- [`tmm-yaml`](skills/tmm-yaml/SKILL.md): physical YAML authoring and complete examples.
- [`metric-synthesis`](skills/metric-synthesis/SKILL.md): dimension synthesis documented in editable XMCD, with a standalone Python solver.
- [`mathcad-mechanisms`](skills/mathcad-mechanisms/SKILL.md): editable classic Mathcad mechanism calculations, examples and the bundled XMCD library.
- [`tmm-graphics`](skills/tmm-graphics/SKILL.md): scene formats, custom plots, Markdown and KOMPAS CDW rendering.

Read the [recommended coursework workflow](WORKFLOW.md). For a course project,
select and order the needed sections: synthesis, iterative YAML, kinematics,
independently authored dynamics, analytical kinetostatics, and gear/cam studies;
the site/CLI dynamics output is alpha material. For first-semester homework,
the usual set is iterative YAML, kinematics, and the single-position kinematics
and graphical kinetostatics sheets. When a worksheet is final, render every
Mathcad graph and requested Markdown/scene in KOMPAS and keep edited Mathcad
and scenes consistent.

`tmm --help` and `tmm help` show project/homework sections and public documentation links,
without requiring an API token or a network request.

## Boundary

The client owns transport, synchronous result/plan integrity checks, and local
publication. It owns no calculation logic; computation happens in the private
service or the installed KOMPAS Renderer.
