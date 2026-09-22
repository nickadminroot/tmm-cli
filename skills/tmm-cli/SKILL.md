---
name: tmm-cli
description: Install and operate the public TMM CLI and its installed or portable local KOMPAS Renderer for linkage, rendering, XMCD, Markdown, KOMPAS export, and version without account credentials.
---

# TMM CLI

The public `tmm` binary is a synchronous transport and publication client.
All supported calculation, scene, XMCD, Markdown, and KOMPAS plan requests are
tokenless. It sends authored YAML, Markdown, or scene JSON to the TMM service,
then writes the declared artifact locally. It does not calculate mechanisms or
run Mathcad/KOMPAS on its own. Native CDW export still requires a running local
KOMPAS Renderer and an installed KOMPAS-3D.

Use this skill together with [tmm-yaml](../tmm-yaml/SKILL.md),
[metric-synthesis](../metric-synthesis/SKILL.md),
[mathcad-mechanisms](../mathcad-mechanisms/SKILL.md), and
[tmm-graphics](../tmm-graphics/SKILL.md). The recommended project and homework
sections are in the public [`WORKFLOW.md`](https://github.com/nickadminroot/tmm-cli/blob/main/WORKFLOW.md).

Before each stage, install every skill relevant to that stage as a complete
directory inside the current working project, including its `references`,
`examples`, `assets`, `scripts`, and `vendor`. A copied `SKILL.md` alone is not
an installation. Read each installed `SKILL.md` and consult it and its routed
resources throughout the work.

## Install and verify

1. Download the archive for the current platform from the public
   [TMM CLI releases](https://github.com/nickadminroot/tmm-cli/releases). Use
   the release assets and checksum file supplied by the publisher; do not
   clone a private source checkout.
2. Verify the downloaded archive before extracting it. The checksum file lists
   every platform asset, so check only the row for the file you downloaded:

   ```bash
   archive="$(find . -maxdepth 1 -type f -name 'tmm-cli_*' -print -quit)"
   test -n "$archive"
   grep -F "  ${archive##*/}" checksums.txt | sha256sum -c -
   ```

   On macOS pipe the matching row to `shasum -a 256 -c -`. On Windows compare
   `Get-FileHash` with the matching filename row. Running `sha256sum -c
   checksums.txt` is valid only after downloading every archive in the
   release.
3. Put the verified executable in a user-owned `PATH` directory and check:

   ```bash
   tmm version
   tmm --help
   ```

The exact command contract is in [REFERENCE.md](REFERENCE.md). Confirm that
the binary version and help describe the release you installed.

## Start the local KOMPAS Renderer

The renderer is required only for native `.cdw` output. It is a separate
64-bit Windows application, not part of the `tmm` executable or a skill
directory. It requires installed KOMPAS-3D with API7/API5 and the user's
interactive desktop session.

First probe `GET http://127.0.0.1:17342/v1/capabilities`. Reuse an existing
compatible protocol-v2 renderer. If none is reachable, choose one release form:

- Regular workstation: install the per-user setup.
- One-off agent task: download and run the portable ZIP in the background,
  then stop only the process started by that agent.

1. Download `tmm-kompas-renderer-setup.exe` from the first-party
   [`/v1/kompas-renderer/installer`](https://api.tmm-agent.ru/v1/kompas-renderer/installer)
   route. The same setup and its `.sha256` file are attached to the
   [latest CLI release](https://github.com/nickadminroot/tmm-cli/releases/latest).
2. Verify the setup SHA-256 against the adjacent release checksum. Run the
   unsigned setup as the current user; SmartScreen may require the user to
   choose **More info → Run anyway**.
3. Confirm that `GET http://127.0.0.1:17342/v1/capabilities` returns protocol
   version 2. The setup starts the renderer immediately and registers per-user
   startup for future Windows logins.
4. Run the required `tmm kompas ... --output FILE.cdw` command and inspect the
   non-empty CDW in visible KOMPAS. A capabilities response, signed plan, JSON
   result, or preview alone is not native acceptance.

For portable use, download
`tmm-kompas-renderer-portable-windows-amd64.zip` and its `.sha256` file from the
latest release. Verify and extract the complete archive; never copy only the
`.exe`. Start `tmm-kompas-renderer.exe` from the extracted directory with its
adjacent `renderer-config.json` and frozen runtime files. The config contains
the current production **public** verification key and non-secret runtime
settings; no private key, token, installation, service, startup registration,
or key rotation is involved.

Use the supported local interactive renderer rather than a Linux process,
Windows service, remote renderer, or private source checkout. Installed and
portable forms intentionally conflict on the same port and per-user mutex, so
never start a second copy.
The public renderer source and packaging contract are in
[`kompas-renderer/`](https://github.com/nickadminroot/tmm-cli/tree/main/kompas-renderer).

## Endpoint and environment contract

The CLI reads `TMM_API_URL` only as an endpoint override for source or
development builds. Release builds use their embedded HTTPS endpoint. No
`TMM_API_TOKEN` is read, required, or sent, and no synthetic bearer header is
created. Keep unrelated credentials out of YAML, URLs, prompts, repositories,
and logs.

The public transport is:

- `linkage`, `render`, and `svg`: synchronous `POST /v1/compute` with a v1
  request envelope and ZIP bundle; the client verifies the
  `X-Result-Sha256` checksum and `_tmm-result.json` manifest before publishing.
- `xmcd`: `POST /v1/linkage/xmcd`, returning native Mathcad XML.
- `resolve`: `POST /v1/scenes/resolve`, returning Scene v2 `.render.json`.
- `md`: `POST /v1/linkage/markdown/render`, uploading the model, document,
  explicitly referenced local scenes, and options.
- YAML `kompas scene` and `kompas page`: synchronous signed plans from
  `/v1/linkage/cdw/scene` and `/v1/linkage/cdw/page`; challenge/signature
  verification remains required before sending `plan.json` to the local
  Renderer.
- JSON `kompas scene-json` and `kompas render-json`: signed plans from
  `/v1/cdw/scene` and `/v1/cdw/render`.

The service owns schema validation and calculation. The CLI validates transport
checksums, result manifests, signed renderer plans, and local output paths.

## Physical linkage scope

YAML-backed `linkage`, `xmcd`, and KOMPAS routes accept one ground-connected,
closed planar linkage per `linkage/v2` file. Mechanically coupled multi-loop
linkages are supported, but independent mechanisms are not a supported bundle,
even when they share `ground` or occupy one assembly drawing. For that rare
case, use one YAML per mechanism, solve each separately, and manually compose
the exported scenes/Markdown, XMCD calculations, and final CDW presentation.
See the [topology boundary](../tmm-yaml/REFERENCE.md#topology-boundary) for the
physical contract and split workflow.

## Workflow

1. Prepare one physical YAML per physical linkage with
   [tmm-yaml](../tmm-yaml/SKILL.md), using its compact scientific notation:
   numeric link IDs, uppercase-Latin point/pair IDs, and short indexed symbols.
2. Use `tmm linkage MODEL.yaml --output DIR` for the generic linkage artifact
   tree, including native XMCD and its text preview.
3. Use `tmm xmcd MODEL.yaml --output FILE.xmcd` when only the native Mathcad
   worksheet is needed. Edit and statically validate it with
   [mathcad-mechanisms](../mathcad-mechanisms/SKILL.md), then use native
   Mathcad for recalculation when available.
4. Inspect every returned `.scene.json` and `.render.json` and keep working
   copies outside the installed skill. YAML and the CLI do not solve every
   coursework section, but they can and must supply draft mechanism scenes.
   Start graphics work from the closest generated draft. Agents may edit
   schema-supported labels, visibility, line weights,
   layout, and other presentation details while preserving the worksheet's
   values and units. Resolve with `tmm resolve`, or send either form directly
   to `tmm kompas scene-json`/`tmm kompas render-json`. For every mechanism
   calculation, retain the high-level `calculation-schematic` scene from this
   catalog and keep it synchronized with the Mathcad worksheet; see
   [mathcad-mechanisms](../mathcad-mechanisms/SKILL.md).
5. Use `tmm md MODEL.yaml DOCUMENT.md --format A1|A2|A3 --output FILE` for a
   Markdown preview. The CLI uploads only scene files explicitly referenced
   by directives or graphic bindings; absent files use the server's generated
   catalog. Use `--source-path` consistently when the document has a logical
   publication path. Use `tmm kompas page` to render one page to native CDW.
6. For a high-level scene, use `tmm kompas scene-json INPUT.scene.json` with
   `--scale` or `--target-max-side`; for a resolved Scene v2 file use
   `tmm kompas render-json INPUT.render.json`. Both require the local Renderer.

Create a new mechanism scene only as a documented last resort when the linkage
catalog has no usable draft. New independently calculated graphs are different:
author them as high-level `engineering-graph.scene.json` inputs and let
`tmm resolve` or `tmm kompas scene-json` produce the derived Scene v2/CDW.
Do not hand-author SVG illustrations unless the user explicitly requests SVG.
Treat Markdown as a working CLI input; deliver prose and reports as editable
DOCX, converting with Pandoc when available. Create PDF only on an explicit user
request. See [tmm-graphics](../tmm-graphics/SKILL.md) for the full policy and
visual reference pages.

The two coursework groups are described in
[`WORKFLOW.md`](https://github.com/nickadminroot/tmm-cli/blob/main/WORKFLOW.md).
A course project may select synthesis, YAML, kinematics, independently
authored dynamics, analytical kinetostatics, and gear/cam studies in the order
required by its brief. First-semester homework usually selects YAML,
kinematics, and the requested single-position kinematic/graphical
kinetostatic sheets. Do not add omitted sections automatically. Every graph in
the final Mathcad worksheet needs a matching scene and native KOMPAS rendering;
see [tmm-graphics](../tmm-graphics/SKILL.md).

## XMCD editing and acceptance

Use [mathcad-mechanisms](../mathcad-mechanisms/SKILL.md) for mechanism methods,
notation, and worksheet layout; it includes the `xmcd` authoring library.

For every agent-authored or agent-edited classic Mathcad `.xmcd`, use the
standalone [`xmcd` library](https://github.com/nickadminroot/xmcd) as the
editing and static-validation API. Load a worksheet with
`Worksheet.read(...)`, edit typed regions and expressions, and write it with
`Worksheet.write(...)`. Preserve editable formulas instead of rewriting raw
XML.

Keep the two acceptance gates separate:

- Static validation uses `Worksheet.check()`, `Worksheet.validate()`, and the
  validation performed by `Worksheet.write(...)`. These operations do not run
  Mathcad or recalculate formulas.
- Native acceptance opens, recalculates, and saves the worksheet in installed
  classic Mathcad, then inspects saved results, calculation errors, and graph
  output. A clean static report is not evidence of native recalculation.

## Diagnostics

Keep stdout for the command's declared output path. Read stderr for the stable
diagnostic code, stage, field/line/column, and ordered step status. Preserve
the exit code. Synchronous operations do not create account runs, quote or
balance reservations, resume commands, or cancellation IDs; Ctrl+C interrupts
the local request. A `6` from a KOMPAS command can indicate a server, worker,
Renderer, or native installation failure.

The commands and public endpoints above are the complete supported surface. Do
not invent a `tmm skills` subcommand, local calculation fallback, upload
installer, or authentication mechanism.
