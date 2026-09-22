# tmm-scene-kompas

Renders `tmm-scene` v2 JSON into KOMPAS-3D `.cdw` drawings through the API7
type library, with API5 fallback for leader arrowheads.

## Supported environment

Live drawing requires Windows, KOMPAS-3D, its API7 and API5 type libraries, and
Python 3.9 or newer with `pywin32`. COM-free parsing and layout are separate
from the live KOMPAS boundary.

## Install the released Renderer

End users do not need Python, uv, PyInstaller, or Inno Setup. Download the
current `tmm-kompas-renderer-setup.exe` from the
[first-party TMM API](https://api.tmm-agent.ru/v1/kompas-renderer/installer),
or download the identical setup and `.sha256` file from the
[latest tmm-cli release](https://github.com/nickadminroot/tmm-cli/releases/latest).
Verify the checksum, run the setup as the current Windows user, accept the
unsigned-app SmartScreen prompt only after verification, and then check:

```powershell
Invoke-RestMethod http://127.0.0.1:17342/v1/capabilities
```

The setup installs under `%LOCALAPPDATA%\Programs\TMM Kompas Renderer`, starts
the renderer immediately, and registers HKCU startup. Native acceptance requires
an actual CLI or website render that leaves a visible KOMPAS document open and
returns a non-empty `.cdw`.

## Run the portable Renderer

For one-off agent work, the latest tmm-cli release also contains
`tmm-kompas-renderer-portable-windows-amd64.zip` and its `.sha256` file. Verify
and extract the complete archive, then run `tmm-kompas-renderer.exe` from the
extracted `tmm-kompas-renderer` directory. The ZIP is the same frozen daemon as
the installed form, with the same production public verification key,
`key_id`, allowed origin, localhost port, mutex, and data directory. It does
not rotate a key, register HKCU startup, or install a Windows service.

Keep `renderer-config.json` and every frozen runtime file beside the
executable. A lone copied `.exe` is intentionally unsupported. Start it in the
logged-in interactive Windows session and verify protocol v2:

```powershell
$rendererDir = (Resolve-Path .\tmm-kompas-renderer).Path
$renderer = Start-Process `
  -FilePath "$rendererDir\tmm-kompas-renderer.exe" `
  -WorkingDirectory $rendererDir `
  -PassThru
Invoke-RestMethod http://127.0.0.1:17342/v1/capabilities
```

Do not start it when another renderer already answers on the fixed port. After
the task, stop only the process represented by `$renderer`; do not terminate an
installed renderer that the agent did not start. Native acceptance still
requires a real signed-plan render, non-empty CDW, and visible KOMPAS document.

## Input and output contract

The adapter consumes one schema-valid `tmm-scene` v2 document and produces one
`.cdw` drawing. It consumes the document root as one scene; a `scenes[]` wrapper
is not accepted.

```json
{
  "format": "tmm-scene",
  "version": 2,
  "units": "mm",
  "id": "hello",
  "entities": [
    { "id": "base", "type": "line", "from": [0, 0], "to": [25, 0] },
    { "id": "label", "type": "text", "position": [12.5, 8], "text": "Hello", "fontSize": 3.5 }
  ]
}
```

The portable public Scene v2 schema is bundled with the
[`tmm-graphics`](../skills/tmm-graphics/references/tmm-scene-v2.schema.json)
skill. This adapter owns KOMPAS-specific lowering, sheet handling, tables,
text, and drawing capabilities.

## CLI contract

```text
tmm-scene-kompas INPUT.json --output OUTPUT.cdw
```

When `--output` is omitted, the `.cdw` file is written next to the input with
the same stem name.

## Local KOMPAS Renderer

The package provides the native localhost renderer used by the public CLI and
web clients. They obtain a fresh challenge, request a scene or page CDW plan
from the public plan route, and send only the resulting Ed25519-signed
declarative envelope to this renderer. The renderer never accepts
commands, filesystem paths, scripts, bearer tokens, or arbitrary COM member
names.

The supported release is a per-user **unsigned** Windows setup. It requires
KOMPAS-3D with API7/API5 in the same interactive desktop session; it is not a
Windows service and cannot render in a headless session. The setup installs
under `%LOCALAPPDATA%\Programs\TMM Kompas Renderer`, registers HKCU Run, and
stores persistent KOMPAS backing files under
`%LOCALAPPDATA%\TMM\KompasRenderer\runs`. SmartScreen may warn because the setup
is unsigned.

## Build the Windows setup and portable ZIP

Building the installer requires Windows and a separate Inno Setup installation.
Synchronize the locked project extras, then run the release script with an
Ed25519 **public** key and the exact browser origin:

```text
uv sync --extra kompas --extra packaging --locked
uv run --locked --extra kompas --extra packaging python packaging/build_windows.py \
  --public-key-file RELEASE_PUBLIC_KEY.pem --key-id release-2026 \
  --allowed-origin https://www.tmm-agent.ru --renderer-version 0.2.0
```

The production portal origin is exactly `https://www.tmm-agent.ru`. If
`--allowed-origin` is omitted, the builder uses `TMM_SITE_ORIGIN` as the exact
origin; explicit CLI origins remain authoritative. An installer built with
another origin returns `403 forbidden` to the portal and must be rebuilt;
changing the web client cannot repair an already-installed allowlist.

The script first creates the complete portable ZIP and then invokes `ISCC.exe`
from the Inno Setup installation (or accepts an explicit `--iscc` path). Use
`--portable-only` to skip Inno Setup. `--dry-run` validates inputs on
non-Windows hosts. Both artifacts can be published as GitHub release assets. The production
site serves its admitted copy from `/v1/kompas-renderer/installer`; deployment
configuration and private signing material remain outside this public source
repository.

`renderer-config.json` is generated with exactly five release keys:
`public_key`, `key_id`, `allowed_origins`, `renderer_version`, and
`data_directory`. It contains no private key, API token, or browser credentials.
Frozen installed and portable startup read only this adjacent file; environment and CLI configuration is
available solely through the explicit `--dev` development seam and cannot
override a release config. The public key verifies plans signed by the existing
production key; building the portable form neither requires nor rotates the
private key.

The renderer binds only to `127.0.0.1:17342`. `GET /v1/capabilities` returns
protocol version 2, the renderer version, a UUID, a one-use 32-byte challenge,
and all capabilities `scene-v2`, `api7`, `api5-text`, `visible-document`, and
`cdw-return`. `POST /v1/render` requires the signed plan, loopback peer,
localhost Host, exact configured Origin (when sent), and the protocol-v2
compatibility header `X-TMM-Agent-Request: 1`. CORS preflight permits only
GET/POST/OPTIONS and the two required headers; PNA is acknowledged only for an
allowlisted Origin. No Authorization or cookie is accepted or forwarded.

Successful renders return a non-empty `application/octet-stream` CDW with
`Content-Disposition` and `X-TMM-Result-Sha256`, call the existing
`build_drawing(scene, output, visible=True, keep_open=True)` seam, and leave
the visible KOMPAS document open. The backing file is not deleted while that
document is open. Startup failures (configuration, mutex, or bind) are
recorded in `%LOCALAPPDATA%\TMM\KompasRenderer\renderer-startup.log` in addition
to stderr. A second render while COM is active receives the protocol-v2
compatibility error `409 agent_busy`; bind conflicts produce an explicit startup
diagnostic.

## Boundary

The adapter is a native KOMPAS output boundary. It does not redefine Scene v2
field semantics, render SVG, or provide a Linux-native substitute for KOMPAS.
