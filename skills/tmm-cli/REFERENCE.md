# TMM CLI reference

This reference is maintained with the public CLI source and skills. Use a
released or source-built `tmm` matching the commands below; verify release
archive checksums and inspect `tmm version` and `tmm --help` before use.
No private TMM source revision is a dependency.

## Commands

| Command | Contract |
| --- | --- |
| `tmm linkage INPUT --output DIR` | Run free generic linkage analysis and publish the returned artifact tree, including native XMCD and its text preview. |
| `tmm md MODEL.yaml DOCUMENT.md --format A1\|A2\|A3 --output FILE [--source-path PATH]` | Render Markdown with its referenced local scenes and publish the preview. |
| `tmm render INPUT --output FILE [--scale N \| --target-max-side N]` | Run the synchronous public Scene v2 calculation. |
| `tmm resolve INPUT.scene.json --output FILE.render.json` (alias `tmm render-json`) | Resolve high-level scene JSON to Scene v2 JSON. |
| `tmm svg INPUT --output FILE [--format svg\|png]` | Publish an SVG or PNG preview. |
| `tmm xmcd INPUT --output FILE.xmcd` | Request the free native Mathcad 15 XMCD output. |
| `tmm kompas scene MODEL.yaml SCENE --output FILE` | Request a signed YAML scene plan and render it through the local KOMPAS Renderer. |
| `tmm kompas page MODEL.yaml DOCUMENT.md --page N --format A1\|A2\|A3 --output FILE [--source-path PATH]` | Request a signed Markdown page plan and render it through the local Renderer. |
| `tmm kompas scene-json INPUT.scene.json --output FILE.cdw [--scale N \| --target-max-side N]` | Render arbitrary high-level scene JSON to CDW. |
| `tmm kompas render-json INPUT.render.json --output FILE.cdw` | Render arbitrary Scene v2 JSON to CDW. |
| `tmm version` | Print the client version. |

Check `tmm --help` from the released/source-built binary for the current
flags. This table is not permission to call an undocumented command.

## Environment

- No API token or bearer header is used by supported commands. Keep unrelated
  credentials out of the environment, files, and logs.
- `TMM_API_URL` is an endpoint override for source/development builds; do not
  put credentials in it. Release builds use their embedded HTTPS endpoint.
- `TMM_KOMPAS_RENDERER_URL` is optional and must point to a local HTTP
  Renderer with an explicit port. It is not used for ordinary synthesis or
  XMCD.

## Local Renderer contract

- Production setup: `https://api.tmm-agent.ru/v1/kompas-renderer/installer`.
- Portable release assets:
  `tmm-kompas-renderer-portable-windows-amd64.zip` and its `.sha256` file in
  the latest public CLI release.
- Public source and release mirror:
  `https://github.com/nickadminroot/tmm-cli/tree/main/kompas-renderer` and the
  latest release assets.
- Supported runtime: 64-bit Windows, installed KOMPAS-3D API7/API5, one
  interactive user session.
- Installed program: `%LOCALAPPDATA%\Programs\TMM Kompas Renderer` with HKCU
  startup; persistent backing data is under
  `%LOCALAPPDATA%\TMM\KompasRenderer`.
- Probe: `GET http://127.0.0.1:17342/v1/capabilities`, protocol version 2.
- Startup diagnostics:
  `%LOCALAPPDATA%\TMM\KompasRenderer\renderer-startup.log`.

The portable ZIP is the same frozen daemon and strict release config without
the installer, HKCU startup entry, or Windows service. Keep the full extracted
`tmm-kompas-renderer` directory together. The adjacent config contains the
production public verification key, not signing material; it does not create
or rotate keys. Probe first and reuse an existing protocol-v2 process because
the installed and portable forms share port `17342` and the per-user mutex.

The setup and portable executable are unsigned and may trigger SmartScreen.
Verify the corresponding separate SHA-256 release asset before execution.
Reaching the capabilities endpoint
does not prove COM rendering; require a non-empty checksummed CDW and visible
KOMPAS document for native acceptance.

## Exit classes

| Code | Meaning |
| ---: | --- |
| `0` | Success. |
| `2` | Usage or local input error. |
| `3` | Reserved upstream authentication/account failure; supported commands do not initiate account requests. |
| `4` | Remote domain failure. |
| `5` | Synchronous request transport failure or interruption before a result. |
| `6` | Server, worker, or Renderer failure. |

Read the structured stderr diagnostic rather than translating one error into a
different class. Result-expired and result-lost are distinct remote errors.

## Safety rules

- Never log or echo Authorization headers, cookies, or signed URLs.
- Keep source YAML and output directories outside the installed skill.
- Verify the signed KOMPAS plan and inspect the actual local Renderer result;
  receiving a plan is not evidence that a `.cdw` was created.
- The public skill contains no server source, private checkout, or local
  calculation fallback.

## Synchronous calculation contract

`tmm linkage`, `tmm render`, and `tmm svg` send a multipart request to
`POST /v1/compute`. The `request` part is a v1 JSON envelope:

```json
{"version":1,"operation":"linkage|render|svg","entrypoint":"...","options":{}}
```

The `bundle` part is the authored input ZIP. The response is an
`application/zip` result with `_tmm-result.json` and an
`X-Result-Sha256` header. The CLI verifies the lowercase SHA-256 digest and
the manifest operation/publication before writing files. Requests are
synchronous and do not expose run, quote, balance, or resume state.

`tmm xmcd` posts YAML to `POST /v1/linkage/xmcd`; the response is native
Mathcad XML. `tmm md` posts model/document/options (and an optional `scenes`
JSON object) to `POST /v1/linkage/markdown/render`.

## Public JSON and YAML KOMPAS endpoint contract

`tmm resolve` posts the high-level `.scene.json` bytes directly to
`POST /v1/scenes/resolve` and writes the returned Scene v2 `.render.json`.
`tmm kompas scene-json` obtains a fresh local-renderer challenge and posts
`{"scene": OBJECT, "options": {"version": 1, "agent_challenge": STRING,
...}}` to `POST /v1/cdw/scene`. `tmm kompas render-json` uses the same envelope
with `"render": OBJECT` at `POST /v1/cdw/render`. Both CDW endpoints return a
signed `application/zip` plan; the CLI validates its manifest and challenge,
then sends `plan.json` to the loopback KOMPAS Renderer. No YAML mechanism,
quote, balance, registry admission, or bearer token is involved.

`tmm kompas scene` sends the YAML mechanism and options to
`POST /v1/linkage/cdw/scene`; `tmm kompas page` sends the YAML mechanism,
Markdown document, options, and optional `scenes` JSON object to
`POST /v1/linkage/cdw/page`. Both return the same signed plan shape. The
options include `version: 1`, the Renderer challenge, and the requested scene
or page (`format`, `page`, and optional `source_path`).

All YAML-backed linkage, XMCD, and KOMPAS calls operate on one
ground-connected, closed planar linkage per `linkage/v2` file. Coupled
multi-loop linkages are allowed; independent mechanisms are not a multi-mechanism
container, even if they share `ground` or are drawn in one place. Solve rare
independent mechanisms in separate YAML files, then compose their scene JSON,
Markdown, XMCD, and CDW outputs manually. See
[`tmm-yaml` topology boundary](../tmm-yaml/REFERENCE.md#topology-boundary).

Agents may freely edit any received `.scene.json` or `.render.json` intermediate
file to improve or repair presentation before calling the tokenless commands.
Keep a high-level `.scene.json` valid for its scene-input contract and a
`.render.json` valid Scene v2 JSON; preserve the edited file outside the
installed skill directory.

## Markdown attachments

`md` and `kompas page` include the local `.scene.json` and `.render.json`
files referenced by `tmm-scene` and graphic bindings. Paths are relative to the
Markdown file's directory; uploads override generated scenes with the same
logical key, and absent local files retain the generated-catalog fallback.
`--source-path` sets the logical document path for both commands. For the full
syntax and examples, use [tmm-graphics](../tmm-graphics/SKILL.md).

## XMCD editing boundary

Use the standalone [`xmcd` library](https://github.com/nickadminroot/xmcd) for
every agent edit or static check of a classic Mathcad `.xmcd` file. Load an
existing file with `Worksheet.read(...)`, edit its typed regions and
expressions, and write it with `Worksheet.write(...)`. Do not hand-edit XMCD
XML. The [mathcad-mechanisms](../mathcad-mechanisms/SKILL.md) skill includes
this library and a typed adapter for authored mechanism calculations.

| Gate | Required operation | What it proves |
| --- | --- | --- |
| Static | `Worksheet.check()`, `Worksheet.validate()`, `Worksheet.write()`, or structural `validate(...)`; use `calculation_errors(...)` only to read saved diagnostics | The document and supported expressions pass the library's static checks; no Mathcad execution occurs. |
| Native | Open, recalculate, and save in installed classic Mathcad; inspect saved results, errors, and graphs | Formula/solver convergence and graph output for that Mathcad runtime. |

Treat static success and native recalculation as separate evidence. The
`tmm linkage` and `tmm xmcd` commands publish XMCD bytes; they do not turn a
static library check into proof that Mathcad recalculated the worksheet.
