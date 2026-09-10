---
name: tmm-cli
description: Install and operate the public TMM CLI for linkage, rendering, exports, mechanisms, resume, cancel, and version while keeping credentials out of all user-visible data.
compatibility: Requires a released tmm binary and an account token in the TMM_API_TOKEN environment variable; paid exports require explicit admission flags.
---

# TMM CLI

Use the public `tmm` binary as a thin remote client. It sends the user's
authored YAML or document to the TMM service and writes declared artifacts
locally. It does not calculate mechanisms or run Mathcad/KOMPAS on its own.

## Install and verify

1. Download the archive for the current platform from the public
   [TMM skills releases](https://github.com/nickadminroot/tmm-skills/releases).
   Use the release assets and checksum file supplied by the publisher; do not
   clone a private source checkout.
2. Verify the archive before extracting it:

   ```bash
   sha256sum -c checksums.txt
   ```

   On macOS use `shasum -a 256 -c checksums.txt`. Compare the PowerShell
   `Get-FileHash` result on Windows. If a signed checksum bundle is supplied,
   verify it with the release's published identity before installation.
3. Put the verified executable in a user-owned `PATH` directory and check:

   ```bash
   tmm version
   tmm --help
   ```

   The current contract is CLI `0.1.0-dev` at the source revision recorded in
   [REFERENCE.md](REFERENCE.md). Refresh this statement with every release.

## Authentication and secrets

Set the token only in the process environment:

```bash
export TMM_API_TOKEN='token-from-the-account'
```

Keep it out of argv, YAML, URLs, shell history, prompts, chat, repository
files, and logs. Never paste a token into a diagnostic or an example.

## Workflow

1. Prepare or receive one physical YAML with [tmm-yaml](../tmm-yaml/SKILL.md).
2. Use `tmm linkage INPUT --output DIR` for the free generic analysis.
3. Inspect the returned status and artifacts. Keep the output path outside the
   installed skill directory.
4. Use `tmm resume UUID --output PATH` only where the returned operation says
   it is resumable. Use the same run; never resubmit a paid operation.
5. Use `tmm cancel UUID` only for a submitted run that the current contract
   allows to cancel.

## Admission

`--allow-new-mechanism` applies to paid XMCD. `--accept-new-mechanism`
applies to paid KOMPAS scene/page export. Obtain explicit user consent before
passing either flag. A generic `tmm linkage` operation is free and is not a
paid export.

KOMPAS requires the separately installed local Renderer. Mathcad/XMCD and
ordinary linkage/YAML preparation do not require KOMPAS. Do not put renderer
credentials or URLs in a skill request.

## Diagnostics

Keep stdout for the command's declared output. Read stderr for the stable
diagnostic code, stage, field/line/column, and ordered step status. Preserve the
exit code. A transport or accepted-run failure may include a Run ID and a
same-run Resume command; follow it only when the command reference says it is
allowed.

The skill covers the existing CLI surface only. Do not invent a `tmm skills`
subcommand, local calculation fallback, upload installer, or new flag.
