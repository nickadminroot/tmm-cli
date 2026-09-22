# TextBlock conformance fixtures

This directory contains the packaged conformance fixtures for the KOMPAS
adapter's text and table-cell boundaries.

## Canonical data

`text-block-corpus.v1.json` defines the canonical public text-block corpus.
`python-layout-envelope.v1.json` locks the COM-free deterministic plan width,
height, line count, and overflow result and identifies the corpus by SHA-256.
`table-cell-corpus.v1.json` covers accepted and rejected plain or inline-
`$...$` table-cell cases, including stable error codes and source spans.

## Update contract

Update the canonical fixtures deliberately and keep the corpus digest and layout
envelope aligned. Renderer output is not a source for fixture updates. The
fixture set defines stable input, layout, and diagnostic behavior for the public
Python adapter.
