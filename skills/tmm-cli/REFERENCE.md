# TMM CLI reference

This reference is part of the public skills release tag `v0.1.2`. It requires
a separately published `tmm` CLI release asset; verify the archive checksum and
`tmm version` before use. No private TMM source revision is a dependency.

## Commands

| Command | Contract |
| --- | --- |
| `tmm linkage INPUT --output DIR` | Run free generic linkage analysis and publish the returned artifact tree, including native XMCD and its text preview. |
| `tmm md MODEL.yaml DOCUMENT.md --format A1\|A2\|A3 --output FILE` | Render a Markdown document and publish the preview. |
| `tmm render INPUT --output FILE [--scale N \| --target-max-side N]` | Render one Scene v2 input. |
| `tmm svg INPUT --output FILE [--format svg\|png]` | Publish an SVG or PNG preview. |
| `tmm xmcd INPUT --output FILE.xmcd` | Request the free native Mathcad 15 XMCD output. |
| `tmm kompas scene MODEL.yaml SCENE --output FILE [--accept-new-mechanism]` | Render one named scene through the local KOMPAS Renderer. |
| `tmm kompas page MODEL.yaml DOCUMENT.md --page N --format A1\|A2\|A3 --output FILE [--accept-new-mechanism]` | Render one Markdown page through the local renderer. |
| `tmm mechanisms` | Read the account mechanism balance and registry. |
| `tmm resume UUID --output PATH` | Resume a permitted free operation or accepted native-XMCD legacy result. |
| `tmm cancel UUID` | Cancel a submitted run when the operation permits it. |
| `tmm version` | Print the client version. |

Check `tmm --help` from the released/source-built binary for the current
flags. This table is not permission to call an undocumented command.

## Environment

- `TMM_API_TOKEN` is required for API requests and must be process-local.
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
- Obtain explicit user consent before passing the paid KOMPAS
  `--accept-new-mechanism` flag.
- A successful server admission does not mean a local Renderer completed; inspect
  the actual result and any same-run resume instruction for KOMPAS operations.
- The public skill contains no server source, private checkout, or local
  calculation fallback.

## XMCD editing boundary

Use the standalone [`xmcd` library](https://github.com/nickadminroot/xmcd) for
every agent edit or static check of a classic Mathcad `.xmcd` file. Load an
existing file with `Worksheet.read(...)`, edit its typed regions and
expressions, and write it with `Worksheet.write(...)`. Do not hand-edit XMCD
XML or replace this path with a local/private legacy generator such as
`mathcad_xmcd_generator`.

| Gate | Required operation | What it proves |
| --- | --- | --- |
| Static | `Worksheet.check()`, `Worksheet.validate()`, `Worksheet.write()`, or structural `validate(...)`; use `calculation_errors(...)` only to read saved diagnostics | The document and supported expressions pass the library's static checks; no Mathcad execution occurs. |
| Native | Open, recalculate, and save in installed classic Mathcad; inspect saved results, errors, and graphs | Formula/solver convergence and graph output for that Mathcad runtime. |

Treat static success and native recalculation as separate evidence. The
`tmm linkage` and `tmm xmcd` commands publish XMCD bytes; they do not turn a
static library check into proof that Mathcad recalculated the worksheet.
