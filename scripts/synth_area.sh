#!/usr/bin/env bash
# Local area/timing sanity check against the IHP SG13CMOS5L standard cells.
#
# This is not the Tiny Tapeout GDS flow; it is a fast gate-level estimate used
# during development. The GitHub GDS action / LibreLane run is the authority.
#
# Usage:
#   PDK_ROOT=$HOME/pdk/IHP-Open-PDK ./scripts/synth_area.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDK_ROOT="${PDK_ROOT:-$HOME/pdk/IHP-Open-PDK}"
LIB="$PDK_ROOT/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib"

if [[ ! -f "$LIB" ]]; then
  echo "error: liberty not found: $LIB" >&2
  echo "set PDK_ROOT to the directory containing ihp-sg13cmos5l" >&2
  exit 1
fi

mkdir -p "$ROOT/build"
cd "$ROOT"

SOURCES="src/tt_um_proteus.v src/proteus_core.v src/proteus_loader.v src/proteus_prog_ram.v src/proteus_data_ram.v src/proteus_capture.v"

yosys -p "
  read_verilog $SOURCES;
  hierarchy -check -top tt_um_proteus;
  proc; opt; memory; opt; techmap; opt;
  check -assert;
  dfflibmap -liberty $LIB;
  abc -liberty $LIB;
  opt_clean;
  stat -liberty $LIB;
  tee -o build/area_report.txt stat -liberty $LIB
" 2>&1 | tee build/synth.log

echo
echo "Area report: build/area_report.txt"
echo "Full log:    build/synth.log"
