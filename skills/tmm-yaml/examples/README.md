# Mechanism example corpus

This directory contains complete `linkage/v2` YAML inputs. Every file is an
input model, not a generated result tree: it can be copied, inspected, edited,
and submitted to `tmm linkage` after checking the physical assumptions.

The corpus is split by its public TMM source:

- [`tmm-web/`](tmm-web/) contains all 18 YAML files shipped with the static
  editor's example directory, including the 12 records currently exposed by
  its `SYSTEM_EXAMPLES` catalog and the additional coursework/extreme/force
  scenarios kept alongside that catalog.
- [`linkage-once/`](linkage-once/) contains all 35 working YAML variants from
  `python/linkage_once/variants/`. The intentionally excluded
  `variant_33_broken_do_not_use.yaml` is not a working example and is not
  published here.

The two source sets intentionally remain separate even when filenames and
bytes overlap. This preserves the distinction between an editor snapshot and
the solver's variant inventory; in particular, it prevents a source change
from silently replacing the other copy.

## Verification

The source inventory was checked with the local `linkage_once` solver using
the locked Python environment: all 35 `linkage-once` variants completed, and
all 18 `tmm-web` YAML files completed. The solver may emit warnings for
singular samples while still returning a successful model result. This is not
a substitute for running the public CLI on a modified copy:

```bash
tmm linkage "/absolute/path/to/model.yaml" \
  --output "/absolute/path/to/output-dir"
```

The checked-in files are snapshots. When the owning TMM YAML contract or CLI
changes, re-run that command and update the snapshots together with the
compatibility notes in the parent skill documents.
