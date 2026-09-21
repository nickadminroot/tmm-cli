---
name: tmm-cli
description: Install and operate the public TMM CLI for linkage, rendering, exports, mechanisms, resume, cancel, and version while keeping credentials out of all user-visible data.
compatibility: Requires a released tmm binary; account-scoped operations use TMM_API_TOKEN, while arbitrary JSON resolution/CDW export is public and tokenless. Native CDW export still requires the local KOMPAS Renderer.
---

# TMM CLI

Use the public `tmm` binary as a thin remote client. It sends the user's
authored YAML, document, or intermediate scene JSON to the TMM service and
writes declared artifacts locally. It does not calculate mechanisms or run
Mathcad/KOMPAS on its own.

## Install and verify

1. Download the archive for the current platform from the public
   [TMM CLI releases](https://github.com/nickadminroot/tmm-cli/releases).
   Use the release assets and checksum file supplied by the publisher; do not
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
   release. If a signed checksum bundle is supplied, verify it with the
   release's published identity before installation.
3. Put the verified executable in a user-owned `PATH` directory and check:

   ```bash
   tmm version
   tmm --help
   ```

The public skill release tag recorded in [REFERENCE.md](REFERENCE.md) versions
this instruction. The CLI binary is versioned by its `tmm-cli/v*` release; do
not proceed until a matching public asset is available and `tmm version` passes.

## Authentication and secrets

Set the token only in the process environment:

```bash
export TMM_API_TOKEN='token-from-the-account'
```

Keep it out of argv, YAML, URLs, shell history, prompts, chat, repository
files, and logs. Never paste a token into a diagnostic or an example.

`TMM_API_TOKEN` is not needed for `tmm resolve`, `tmm kompas scene-json`, or
`tmm kompas render-json`. Those commands still use `TMM_API_URL`; they must
never send an empty or synthetic bearer header.

## Workflow

1. Prepare or receive one physical YAML with [tmm-yaml](../tmm-yaml/SKILL.md).
2. Use `tmm linkage INPUT --output DIR` for the free generic analysis; its
   result tree includes the native XMCD and text preview artifacts.
3. Use `tmm xmcd INPUT --output FILE.xmcd` when only the native Mathcad file is
   needed. This is a free direct request and has no admission flag.
4. Inspect the returned status and artifacts. Keep the output path outside the
   installed skill directory.
5. If the result contains a `.scene.json` or `.render.json` intermediate,
   agents may edit that JSON as needed to improve or repair presentation
   (labels, visibility, line weights, layout, and other schema-supported
   drawing details). Keep a high-level `.scene.json` valid for its scene-input
   contract and a `.render.json` valid Scene v2 JSON. Keep the edited file
   outside the installed skill and render it with `tmm kompas scene-json` or
   `tmm kompas render-json` without a token.
6. Use `tmm resolve INPUT.scene.json --output OUTPUT.render.json` to convert a
   high-level scene to Scene v2 without a token. Use `tmm kompas scene-json` for
   direct high-level-scene CDW export, or `tmm kompas render-json` for an
   already-resolved `.render.json` file. Both require the local KOMPAS Renderer.
7. Use `tmm resume UUID --output PATH` only where the returned operation says
   it is resumable (including accepted native-XMCD legacy runs). Use the same run;
   never resubmit a legacy account-scoped operation.
8. Use `tmm cancel UUID` only for a submitted run that the current contract
   allows to cancel.

## XMCD editing and acceptance

For any agent-authored or agent-edited classic Mathcad `.xmcd`, use the
standalone [`xmcd` library](https://github.com/nickadminroot/xmcd) as the
editing and static-validation API. Load an existing worksheet with
`Worksheet.read(...)`, edit typed regions and expressions, and write it with
`Worksheet.write(...)`. Treat this library as the single XMCD editing path:
keep XML edits out of the workflow and do not substitute a local or private
ad-hoc generator.

Keep the two acceptance gates separate:

- Static validation uses `Worksheet.check()`, `Worksheet.validate()`, and the
  validation performed by `Worksheet.write(...)`. `validate(...)` and
  `calculation_errors(...)` can inspect structure and saved diagnostics, but
  none of these operations executes Mathcad or recalculates formulas.
- Native acceptance opens, recalculates, and saves the worksheet in installed
  classic Mathcad, then inspects saved results, calculation errors, and graph
  output. A clean static report or a newly written file is not evidence of a
  native recalculation.

After `tmm linkage` or `tmm xmcd` publishes an XMCD artifact, use the library
for any agent edit and static check. Run native Mathcad separately whenever
formula, solver, or graph results need runtime acceptance and that environment
is available.

## Admission

`--accept-new-mechanism` applies only to the legacy YAML KOMPAS scene/page
export. Obtain explicit user consent before passing that flag. Arbitrary JSON
CDW commands never quote or admit a mechanism. XMCD and generic `tmm linkage`
are free operations and do not use an admission flag.

KOMPAS requires the separately installed local Renderer. Mathcad/XMCD and
ordinary linkage/YAML preparation do not require KOMPAS. Do not put renderer
credentials or URLs in a skill request.

## Diagnostics

Keep stdout for the command's declared output. Read stderr for the stable
diagnostic code, stage, field/line/column, and ordered step status. Preserve the
exit code. A transport or accepted-run failure may include a Run ID and a
same-run Resume command; follow it only when the command reference says it is
allowed.

The commands and public endpoints above are the complete supported surface. Do
not invent a `tmm skills` subcommand, local calculation fallback, upload
installer, or a new authentication mechanism.
