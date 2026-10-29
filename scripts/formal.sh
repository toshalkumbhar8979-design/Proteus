#!/usr/bin/env bash
# Formal property checks for the Proteus-1 core.
#
# Yosys's built-in SAT engine is used directly, so no external SMT solver is
# needed. Each property is proven on its own with a 40-cycle bounded model check
# plus an unbounded temporal-induction proof. Proving them separately keeps one
# failure from masking the others and gives a per-property verdict.
#
# Properties:
#   pc_freeze    the program counter does not move while the core is disabled
#   timer        the cycle timer advances by exactly one or is cleared
#   capture      the capture FIFO fill level never exceeds its depth
#   loader       an idle loader has an empty frame shifter after one clock
#   outputs      stopped, out-of-frame outputs and output enables are all low
#
# The properties live in `ifdef FORMAL blocks in the RTL, so they never reach
# synthesis. Excluding a property is done with the matching F_NO_* define.
#
# Requires: yosys with the `sat` command (standard).

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/build/formal"
mkdir -p "$OUT"
cd "$ROOT"

SOURCES=" \
  src/tt_um_proteus.v \
  src/proteus_core.v \
  src/proteus_loader.v \
  src/proteus_prog_ram.v \
  src/proteus_data_ram.v \
  src/proteus_capture.v"

run_property() {
  local name="$1"
  local defs="$2"
  local log="$OUT/$name.log"

  echo "== $name =="
  yosys -p "
    read_verilog -formal -DFORMAL $defs -Isrc$SOURCES
    prep -top tt_um_proteus -flatten
    async2sync
    chformal -lower
    memory_map
    sat -seq 40 -prove-asserts -verify
    sat -tempinduct -prove-asserts -verify
  " > "$log" 2>&1 || {
    echo "FAIL: $name (see $log)"
    grep -E "SAT proof finished|model found" "$log" | tail -2 || true
    return 1
  }

  echo "PASS: $name (BMC + induction)"
}

run_property pc_freeze "-DF_NO_TIMER -DF_NO_CAP -DF_NO_LOADER -DF_NO_OUT"
run_property timer     "-DF_NO_PC -DF_NO_CAP -DF_NO_LOADER -DF_NO_OUT"
run_property capture   "-DF_NO_PC -DF_NO_TIMER -DF_NO_LOADER -DF_NO_OUT"
run_property loader    "-DF_NO_PC -DF_NO_TIMER -DF_NO_CAP -DF_NO_OUT"
run_property outputs   "-DF_NO_PC -DF_NO_TIMER -DF_NO_CAP -DF_NO_LOADER"

echo
echo "== all properties together =="
yosys -p "
  read_verilog -formal -DFORMAL -Isrc$SOURCES
  prep -top tt_um_proteus -flatten
  async2sync
  chformal -lower
  memory_map
  sat -seq 40 -prove-asserts -verify
" > "$OUT/all.log" 2>&1 || {
  echo "FAIL: combined run (see $OUT/all.log)"
  exit 1
}
echo "PASS: combined run"

echo
echo "All formal properties hold. Logs in $OUT"
