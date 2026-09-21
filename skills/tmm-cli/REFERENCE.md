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
