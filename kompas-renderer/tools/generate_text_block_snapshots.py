"""Generate/check the committed COM-free textBlock semantic/layout snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tmm_scene_kompas.text_block_corpus import load_text_block_corpus
from tmm_scene_kompas.text_block_snapshot import conformance_snapshot


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "tmm_scene_kompas" / "fixtures" / "python-conformance-snapshots.v1.json"


def build() -> dict:
    corpus = load_text_block_corpus()
    return {
        "format": "tmm-python-text-block-conformance-snapshots",
        "version": 1,
        "contract": corpus["contract"],
        "cases": [
            {
                "id": fixture["id"],
                "snapshot": conformance_snapshot({
                    **fixture["entity"], "text": fixture["source"]["markdown"],
                }),
            }
            for fixture in corpus["fixtures"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != data:
            print(f"out-of-date: {OUTPUT}")
            return 1
        return 0
    OUTPUT.write_text(data, encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
