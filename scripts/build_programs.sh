#!/usr/bin/env bash
# Assemble every example program into build/programs/{name}.{json,hex,lst}.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/programs"
PYTHON="${PYTHON:-python3}"

mkdir -p "$OUT"

shopt -s nullglob
sources=("$ROOT"/programs/*.s)
if [[ ${#sources[@]} -eq 0 ]]; then
  echo "error: no programs found in $ROOT/programs" >&2
  exit 1
fi

for src in "${sources[@]}"; do
  name="$(basename "$src" .s)"
  "$PYTHON" "$ROOT/tools/proteus_asm.py" "$src" -o "$OUT/$name" --quiet
  echo "  $name"
done

echo "assembled ${#sources[@]} programs into $OUT"
