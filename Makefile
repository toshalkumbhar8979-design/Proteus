# Proteus-1 top-level build.
#
#   make test       RTL cocotb suite (20 tests)
#   make tools      assembler/disassembler/ISS unit tests (7 tests)
#   make programs   assemble every example into build/programs
#   make synth      Yosys area estimate against IHP CMOS5L
#   make formal     Yosys SAT proofs of five core properties
#   make fpga       ECP5 synthesis + place-and-route portability check
#   make lint       Verilator -Wall (one intentional N-flag warning)
#   make clean

PYTHON ?= python3
PDK_ROOT ?= $(HOME)/pdk/IHP-Open-PDK
SOURCES = src/tt_um_proteus.v src/proteus_core.v src/proteus_loader.v \
          src/proteus_prog_ram.v src/proteus_data_ram.v src/proteus_capture.v

.PHONY: test tools programs synth formal fpga lint clean

test:
	$(MAKE) -C test -B

tools:
	$(PYTHON) -m pytest -q tools/test_isa.py

programs:
	PYTHON=$(PYTHON) ./scripts/build_programs.sh

synth:
	PDK_ROOT=$(PDK_ROOT) ./scripts/synth_area.sh

formal:
	./scripts/formal.sh

fpga:
	./scripts/synth_fpga.sh

lint:
	verilator --lint-only -Wall -Wno-fatal --top-module tt_um_proteus \
	  -Isrc $(SOURCES)

clean:
	rm -rf build test/sim_build test/__pycache__ tools/__pycache__ \
	  .pytest_cache test/*.fst test/*.vcd
