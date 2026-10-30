# Proteus-1 top-level build.
#
#   make test       RTL cocotb suite (21 tests)
#   make tools      assembler/disassembler/ISS unit tests (7 tests)
#   make programs   assemble every example into build/programs
#   make synth      Yosys area estimate against IHP CMOS5L
#   make formal     Yosys SAT proofs of six core properties
#   make fpga       ECP5 synthesis + place-and-route portability check
#   make figures    render docs/figures/*.tex to the README images (tectonic + pymupdf)
#   make die        render the submitted GDS to docs/images/die.png (needs klayout)
#   make lint       Verilator -Wall (one intentional N-flag warning)
#   make clean

PYTHON ?= python3
GDS ?= build/sub/tt_submission/tt_um_proteus.gds
KLAYOUT ?= klayout
PDK_ROOT ?= $(HOME)/pdk/IHP-Open-PDK
SOURCES = src/tt_um_proteus.v src/proteus_core.v src/proteus_loader.v \
          src/proteus_prog_ram.v src/proteus_data_ram.v src/proteus_capture.v

.PHONY: test tools programs synth formal fpga figures die lint clean

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

# The PNG in the README is rasterised from the TikZ PDF at 300 dpi so the figure
# stays crisp on GitHub. Both steps are deterministic; nothing is hand-edited.
figures:
	tectonic -X compile docs/figures/block_diagram.tex --outdir build/figures
	@$(PYTHON) -c "import pymupdf; d = pymupdf.open('build/figures/block_diagram.pdf'); d[0].get_pixmap(matrix=pymupdf.Matrix(300/72, 300/72), alpha=False).save('docs/images/block_diagram.png')" \
	  || echo "note: install pymupdf to refresh docs/images/block_diagram.png"

# The GDS is a CI artifact, not a source file. Fetch it first:
#   gh run download -n tt_submission -D build/sub
# then render at 4x the published width and downsample once, so the cell rows
# stay crisp without storing a 5 MB PNG in the repository.
die:
	$(KLAYOUT) -z -r scripts/render_die.py -rd input=$(GDS) \
	  -rd output=build/die_hi.png -rd width=4800
	@$(PYTHON) -c "from PIL import Image; im = Image.open('build/die_hi.png').convert('RGB'); \
	  im = im.resize((1800, round(1800*im.size[1]/im.size[0])), Image.LANCZOS); \
	  im.quantize(colors=40, dither=Image.NONE).save('docs/images/die.png', optimize=True, dpi=(300,300))" \
	  || echo "note: install pillow to refresh docs/images/die.png"

lint:
	verilator --lint-only -Wall -Wno-fatal --top-module tt_um_proteus \
	  -Isrc $(SOURCES)

clean:
	rm -rf build test/sim_build test/__pycache__ tools/__pycache__ \
	  .pytest_cache test/*.fst test/*.vcd
