# tmm-scene-kompas agent guide

KOMPAS-3D adapter for Scene v2 JSON. It renders `.cdw` drawings through API7
with API5 fallback for leader arrowheads.

Read [`README.md`](README.md) before changing the public input or output
contract. Keep Windows, WSL, COM, fixture, and live-evidence procedures here.

## Scope
- Live drawing requires Windows, KOMPAS-3D, API7/API5 type libraries, and
  Python with `pywin32`.
- COM-free parsing, layout, and fake-API tests can run in Linux Python.
- Live drawing, raster export, and CDW inspection run in Windows Python.
- The portable public Scene v2 schema is
  `../skills/tmm-graphics/references/tmm-scene-v2.schema.json`.

## Internal references

- `docs/WSL.md` owns the WSL wrapper, setup, direct invocation, live smoke tests,
  path handling, raster export, and troubleshooting.
- `docs/rendering-reference.md` owns KOMPAS sheet handling, table/text lowering,
  capability evidence, and estimator diagnostics.
- `src/tmm_scene_kompas/fixtures/` contains synchronized conformance data.
- Calibration probes live under `tools/`.

## Checks

Install the locked KOMPAS extra on Windows:

```bash
uv sync --extra kompas --locked
```

Run the COM-free parser/layout and fake-API regression suite:

```bash
uv run --locked python -m unittest
```

Use the WSL guide for a live smoke test. Live gabarit, object-count,
style-readback, and CDW checks require the Windows KOMPAS/COM environment.

## Local KOMPAS Renderer

`src/tmm_scene_kompas/renderer.py` is the localhost-only native renderer used
by public CLI/web consumers. The public flow is challenge → authenticated
dedicated scene/page CDW endpoint → Ed25519-signed declarative envelope →
local renderer. Keep the fixed allowlist, signature check, one-use
challenge/replay protection, loopback peer/Host checks, exact release origins,
PNA preflight, bounded payloads, fixed `build_drawing` call, and
non-forwarding of auth credentials. There is no remote or unsigned-plan
fallback.

Installed startup reads only the strict five-key `renderer-config.json`
(`public_key`, `key_id`, `allowed_origins`, `renderer_version`,
`data_directory`). Unknown/missing keys and wildcard origins stop startup.
`--dev` plus environment/CLI values is an internal development seam only and
never overrides an installed release config. The default bind is
`127.0.0.1:17342`; one per-user mutex and the fixed-port bind make a second
interactive session fail with an explicit diagnostic.

The render path calls the existing `build_drawing(scene, output,
visible=True, keep_open=True)` API, writes unique persistent backing files
under the configured `runs/` directory, returns a SHA-256 header, and leaves
the visible document open.  Cleanup removes only old UUID-named files owned
by the runs marker and skips files that KOMPAS still locks.  Live visible
document behavior remains a Windows/KOMPAS gate; COM-free tests use a fake
renderer.

The supported setup and portable ZIP are unsigned and
interactive-session-only. PyInstaller stages one shared frozen onedir runtime;
the portable archive keeps it intact, while Inno Setup installs it under
`%LOCALAPPDATA%`, registers HKCU Run, and preserves runtime/downloaded CDW
data on uninstall. On Windows, build with
`uv sync --extra kompas --extra packaging --locked` and run the release script;
`--portable-only` skips Inno Setup, otherwise `ISCC.exe` remains an external
Windows prerequisite. Both forms keep the strict adjacent release config and
same production public verification key; never add private signing material or
rotate keys as a packaging side effect. SmartScreen may display a warning.
Never add arbitrary command, path, script, or COM-member execution APIs.
## Synchronization invariant

Public fixture snapshots under `src/tmm_scene_kompas/fixtures/` are executable
test inputs. When synchronizing them from an upstream metrics producer, copy
exact bytes and run this repository's corpus checks. Renderer output is never a
fixture source, and public documentation must not depend on a private checkout.
