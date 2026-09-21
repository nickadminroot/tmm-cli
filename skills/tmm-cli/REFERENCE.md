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
| `tmm render INPUT --output FILE [--scale N \| --target-max-side N]` | Render one Scene v2 input. |
| `tmm resolve INPUT.scene.json --output FILE.render.json` (alias `tmm render-json`) | Resolve high-level scene JSON to Scene v2 JSON without a token. |
| `tmm svg INPUT --output FILE [--format svg\|png]` | Publish an SVG or PNG preview. |
| `tmm xmcd INPUT --output FILE.xmcd` | Request the free native Mathcad 15 XMCD output. |
| `tmm kompas scene MODEL.yaml SCENE --output FILE [--accept-new-mechanism]` | Render one named scene through the local KOMPAS Renderer. |
| `tmm kompas page MODEL.yaml DOCUMENT.md --page N --format A1\|A2\|A3 --output FILE [--source-path PATH] [--accept-new-mechanism]` | Render one Markdown page through the local renderer. |
| `tmm kompas scene-json INPUT.scene.json --output FILE.cdw [--scale N \| --target-max-side N]` | Render arbitrary high-level scene JSON to CDW without a token. |
| `tmm kompas render-json INPUT.render.json --output FILE.cdw` | Render arbitrary Scene v2 JSON to CDW without a token. |
| `tmm mechanisms` | Read the account mechanism balance and registry. |
| `tmm resume UUID --output PATH` | Resume a permitted free operation or accepted native-XMCD legacy result. |
| `tmm cancel UUID` | Cancel a submitted run when the operation permits it. |
| `tmm version` | Print the client version. |

Check `tmm --help` from the released/source-built binary for the current
flags. This table is not permission to call an undocumented command.

## Environment

- `TMM_API_TOKEN` is required for account-scoped API requests and must be
  process-local. Public scene resolution and arbitrary JSON CDW plan requests
  intentionally omit `Authorization`.
- `TMM_API_URL` is an endpoint override for source/development builds; do not
  put credentials in it. Release builds use their embedded HTTPS endpoint.
- `TMM_KOMPAS_RENDERER_URL` is optional and must point to a local HTTP
  Renderer with an explicit port. It is not used for ordinary synthesis or
  XMCD.

## Exit classes

| Code | Meaning |
| ---: | --- |
| `0` | Success. |
| `2` | Usage or local input error. |
| `3` | Authentication, account, or mechanism-balance failure. |
| `4` | Remote domain failure. |
| `5` | Resumable free-operation transport failure. |
| `6` | Server, worker, or Renderer failure. |

Read the structured stderr diagnostic rather than translating one error into a
different class. Result-expired and result-lost are distinct remote errors.

## Safety rules

- Never log or echo `TMM_API_TOKEN`, Authorization headers, cookies, or signed
  URLs.
- Keep source YAML and output directories outside the installed skill.
- For legacy YAML KOMPAS scene/page commands, obtain explicit user consent
  before passing the compatibility-only `--accept-new-mechanism` flag; it does
  not reserve or consume credit.
- A successful server admission does not mean a local Renderer completed; inspect
  the actual result and any same-run resume instruction for KOMPAS operations.
- The public skill contains no server source, private checkout, or local
  calculation fallback.

## Public JSON endpoint contract

`tmm resolve` posts the high-level `.scene.json` bytes directly to
`POST /v1/scenes/resolve` and writes the returned Scene v2 `.render.json`.
`tmm kompas scene-json` obtains a fresh local-renderer challenge and posts
`{"scene": OBJECT, "options": {"version": 1, "agent_challenge": STRING,
...}}` to `POST /v1/cdw/scene`. `tmm kompas render-json` uses the same envelope
with `"render": OBJECT` at `POST /v1/cdw/render`. Both CDW endpoints return a
signed `application/zip` plan; the CLI validates its manifest and challenge,
then sends `plan.json` to the loopback KOMPAS Renderer. No YAML mechanism,
quote, balance, registry admission, or bearer token is involved.

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
