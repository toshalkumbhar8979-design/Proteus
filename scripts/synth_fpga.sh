#!/usr/bin/env bash
# FPGA portability check: map the design to ECP5 fabric and place-and-route it.
#
# This is not a substitute for running on a board. It answers the two questions
# a board would answer first: does the RTL map to real FPGA primitives, and does
# it fit and close timing in a plausible device? No hardware is required.
#
# Target: Lattice ECP5 LFE5U-25F, CABGA256, speed grade 6. Chosen because it is
# the smallest common ECP5 that has plenty of room for a 128 x 16 register-file
# program memory, and because nextpnr supports it without vendor tools.
#
# Outputs:
#   build/fpga/tt_um_proteus.json   post-synthesis netlist
#   build/fpga/nextpnr.log          resource utilisation and Fmax report
#   build/fpga/report.json          machine-readable PnR report
#
# Requires: yosys with the ecp5 backend, nextpnr-ecp5.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/build/fpga"
mkdir -p "$OUT"

# Run from the repository root: the checkout path may contain spaces, which
# yosys's script parser does not accept inside a command argument.
cd "$ROOT"

SOURCES=" \
  src/tt_um_proteus.v \
  src/proteus_core.v \
  src/proteus_loader.v \
  src/proteus_prog_ram.v \
  src/proteus_data_ram.v \
  src/proteus_capture.v"

echo "== synthesis (yosys, synth_ecp5) =="
yosys -q -p "
  read_verilog -Isrc$SOURCES
  synth_ecp5 -top tt_um_proteus -json build/fpga/tt_um_proteus.json
  stat
" | tee "$OUT/yosys.log"

echo
echo "== place and route (nextpnr-ecp5, LFE5U-25F) =="
nextpnr-ecp5 \
  --25k --package CABGA256 --speed 6 \
  --json "$OUT/tt_um_proteus.json" \
  --freq 32 \
  --timing-allow-fail \
  --report "$OUT/report.json" \
  --textcfg "$OUT/tt_um_proteus.config" \
  2>&1 | tee "$OUT/nextpnr.log"

echo
echo "Reports: $OUT/nextpnr.log and $OUT/report.json"
