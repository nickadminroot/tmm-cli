from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .classify import classify_text
from .models import MODELS, models_list
from .models import render as render_solution
from .models import schema as schema_for
from .models import solve as solve_model
from .util import dump_json, load_json


def _read_text_arg(value: str) -> str:
    p = Path(value)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return value


def cmd_models(args: argparse.Namespace) -> int:
    print(dump_json({"models": models_list()}))
    return 0


def skill_path() -> Path:
    package_root = Path(__file__).resolve().parents[1]
    candidate = package_root.parent / "SKILL.md"
    if candidate.is_file():
        return candidate.resolve()
    raise FileNotFoundError("The metric-synthesis skill is not installed")


def cmd_skill_path(args: argparse.Namespace) -> int:
    print(skill_path())
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    print(dump_json(schema_for(args.model)))
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    text = _read_text_arg(args.text)
    print(dump_json(classify_text(text)))
    return 0


def _result_exit_code(result: dict[str, Any]) -> int:
    return 0 if result.get("status") == "ok" else 3


def _print_final(rendered: dict[str, Any]) -> None:
    mathcad_text = rendered.get("mathcad_text", "").strip()
    explanation = rendered.get("short_explanation", "").strip()
    if mathcad_text:
        print(mathcad_text)
        print(f"\nКраткое пояснение: {explanation}")
    elif explanation:
        print(explanation)


def cmd_solve(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    model = args.model or payload.get("model")
    if not model:
        raise ValueError("Model must be provided via --model or input.model")
    result = solve_model(model, payload)
    print(dump_json(result))
    return _result_exit_code(result)


def cmd_render(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    model = args.model or payload.get("model")
    if not model:
        raise ValueError("Model must be provided via --model or input.model")
    if args.solution:
        result = load_json(args.solution)
    else:
        result = solve_model(model, payload)
    rendered = render_solution(model, payload, result)
    if args.output_format == "json":
        print(dump_json(rendered))
    elif args.output_format == "mathcad":
        print(rendered["mathcad_text"])
    else:
        _print_final(rendered)
    return _result_exit_code(result)


def cmd_run(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    model = args.model or payload.get("model")
    if not model:
        raise ValueError("Model must be provided via --model or input.model")
    result = solve_model(model, payload)
    rendered = render_solution(model, payload, result)
    out: dict[str, Any] = {**result, **rendered}
    if args.output_format == "json":
        print(dump_json(out))
    elif args.output_format == "mathcad":
        print(rendered["mathcad_text"])
    else:
        _print_final(rendered)
    return _result_exit_code(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="msynth", description="Metric synthesis CLI for archive-style planar mechanism tasks.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("models", help="List supported model classes")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("skill-path", help="Print the installed metric-synthesis SKILL.md path")
    p.set_defaults(func=cmd_skill_path)

    p = sub.add_parser("schema", help="Print JSON schema for a model")
    p.add_argument("model", choices=sorted(MODELS.keys()))
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("classify", help="Classify a text task")
    p.add_argument("--text", required=True, help="Task text or path to UTF-8 text file")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("solve", help="Solve a model using JSON input")
    p.add_argument("--model", choices=sorted(MODELS.keys()))
    p.add_argument("--input", required=True)
    p.set_defaults(func=cmd_solve)

    p = sub.add_parser("render", help="Render Mathcad-like text for an input and optional solution JSON")
    p.add_argument("--model", choices=sorted(MODELS.keys()))
    p.add_argument("--input", required=True)
    p.add_argument("--solution")
    p.add_argument("--output-format", choices=["json", "mathcad", "final"], default="json")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("run", help="Solve and render in one call")
    p.add_argument("--model", choices=sorted(MODELS.keys()))
    p.add_argument("--input", required=True)
    p.add_argument("--output-format", choices=["json", "mathcad", "final"], default="json")
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}", file=sys.stderr)
        return 2
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"error: {str(exc).strip(chr(39))}", file=sys.stderr)
        return 2
    except Exception as exc:  # Defensive CLI boundary: never expose an agent-facing traceback.
        print(f"error: internal failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
