#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  tools/render_from_wsl.sh INPUT.json [options]

Options:
  --output PATH.cdw   CDW output (default: INPUT stem + .cdw)
  --png PATH.png      Also export the rendered drawing to PNG
  --dpi NUMBER        PNG resolution (default: 180)
  --work-area         Export only the KOMPAS work area
  --keep-open         Keep the rendered KOMPAS document open
  -h, --help          Show this help

Environment:
  PYTHON_EXE          Windows Python executable (default: python.exe)
EOF
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 2
}

[[ $# -gt 0 ]] || { usage >&2; exit 2; }
[[ "${1:-}" != "-h" && "${1:-}" != "--help" ]] || { usage; exit 0; }

input=$1
shift
output=
png=
dpi=180
work_area=0
keep_open=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      [[ $# -ge 2 ]] || fail "--output requires a path"
      output=$2
      shift 2
      ;;
    --png)
      [[ $# -ge 2 ]] || fail "--png requires a path"
      png=$2
      shift 2
      ;;
    --dpi)
      [[ $# -ge 2 ]] || fail "--dpi requires a number"
      dpi=$2
      shift 2
      ;;
    --work-area)
      work_area=1
      shift
      ;;
    --keep-open)
      keep_open=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

[[ "$dpi" =~ ^[1-9][0-9]*$ ]] || fail "--dpi must be a positive integer"
command -v wslpath >/dev/null 2>&1 || fail "wslpath is unavailable; run this tool inside WSL"
python_exe=${PYTHON_EXE:-python.exe}
command -v "$python_exe" >/dev/null 2>&1 || fail "$python_exe is unavailable through WSL interop"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
[[ -f "$input" ]] || fail "input does not exist: $input"
input=$(realpath "$input")

if [[ -z "$output" ]]; then
  output=${input%.*}.cdw
else
  output=$(realpath -m "$output")
fi
mkdir -p "$(dirname -- "$output")"

if [[ -n "$png" ]]; then
  png=$(realpath -m "$png")
  mkdir -p "$(dirname -- "$png")"
fi

src_win=$(wslpath -w "$repo_root/src")
input_win=$(wslpath -w "$input")
output_win=$(wslpath -w "$output")
export_tool_win=$(wslpath -w "$repo_root/tools/export_active_document_png.py")

win_python() {
  PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "$python_exe" "$@"
}

# Windows Python can omit an UNC entry supplied through PYTHONPATH. Insert the
# WSL source path explicitly so an older editable install cannot shadow this
# checkout.
win_python -c 'import sys; sys.path.insert(0, sys.argv[1]); import pythoncom, win32com.client, markdown_it, mdit_py_plugins, tmm_scene_kompas; print("Windows Python/pywin32 preflight: OK"); print("Source:", tmm_scene_kompas.__file__)' "$src_win"

render_args=("$input_win" --output "$output_win")
if [[ -n "$png" || "$keep_open" -eq 1 ]]; then
  render_args+=(--keep-open)
fi
win_python -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from tmm_scene_kompas.cli import main; raise SystemExit(main())' "$src_win" "${render_args[@]}"

if [[ -n "$png" ]]; then
  png_win=$(wslpath -w "$png")
  export_args=("$export_tool_win" "$png_win" --dpi "$dpi")
  [[ "$work_area" -eq 1 ]] && export_args+=(--work-area)
  [[ "$keep_open" -eq 0 ]] && export_args+=(--close)
  win_python "${export_args[@]}"
fi

[[ -s "$output" ]] || fail "CDW was not created: $output"
printf 'CDW: %s (%s bytes)\n' "$output" "$(stat -c %s "$output")"
if [[ -n "$png" ]]; then
  [[ -s "$png" ]] || fail "PNG was not created: $png"
  printf 'PNG: %s (%s bytes)\n' "$png" "$(stat -c %s "$png")"
fi
