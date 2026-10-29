# Verification Report

This report records what was actually run, what each check proves, and what
remains unproven. It describes the RTL at commit time, not an aspiration.

## 1. Method

Proteus-1 is verified at three levels:

1. **Directed cocotb tests** drive the chip through its real host loader, then
   observe pins the way a logic analyzer or a protocol peer would. The tests do
   not peek at internal state to decide pass/fail, except in the co-simulation
   test, which compares every architectural register.
2. **A cycle-accurate Python ISS** is an independently written golden model.
   The same assembled image runs on both; after every enabled clock the RTL and
   ISS must agree on `PC`, `A`, `X`, `Y`, flags, `SP`, pin registers, timer,
   wait state, halt state, and capture count.
3. **Toolchain unit tests** check the assembler, disassembler, encoder, and ISS
   without a simulator, so a broken tool cannot hide behind a passing RTL test.

The randomized program is generated from the ISA encoder, not from hand-written
hex, and contains all twelve opcode classes. The opcode sweep is exhaustive over
the 12 x 8 encoding space, including subops that ISA v1 leaves unused.

## 2. Results

Environment: Icarus Verilog 12.0, cocotb 2.0.1, Python 3.13, Yosys 0.65,
Verilator 5.046, IHP-Open-PDK `2bbec75`.

```
TESTS=20 PASS=20 FAIL=0 SKIP=0
TOTAL SIM TIME=4,019,410 ns
```

| Test | Stimulus | What it proves |
|---|---|---|
| `test_reset` | `rst_n` low, then release | `uo_out`, `uio_out`, `uio_oe` are driven to 0; no floating outputs |
| `test_loader_readback` | Load `selftest_basic`, read first and last words with command `0x04` | 32-bit frame framing, write port, pipelined MISO readback |
| `test_selftest_basic` | Run the self-test image | Exact output sequence `55 AA 07 C3 03 04 11 91 90 10 A1`: ALU, direct/indexed memory, bit ops, loop, timer signature |
| `test_wait_timing` | `WAIT 10`, `WAIT 20` | Edge-to-edge deltas are exactly 11 and 21 clocks, including the instruction after the wait |
| `test_timer_cosim` | Directed `TMR_CLR`, `TMR_LO`/`TMR_HI`, and two waits past 255 cycles | Timer clear, atomic high-byte latch, increment while running/halted; every clock compared to the ISS |
| `test_uart_tx` | Run `uart_tx.s`, decode `uo_out[7]` at 417 cycles/bit | 8N1 framing, start/stop bits, LSB-first data `P1\n`, exact baud period |
| `test_uart_rx` | Drive `ui_in[3]` with an 8N1 `0x5A` frame | Start-bit detection, centre sampling, stop-bit handling, output match |
| `test_spi_master` | Run `spi_master.s`, sample MOSI on SCK rising | Mode 0, MSB-first `0xA5`, CS framing, done marker |
| `test_spi_other_modes` | Reload CPOL=0 and CPOL=1 images, sample on the CPHA edge | Modes 1–3: `0xA5` recovered on the falling/rising sampling edges |
| `test_spi_target` | Drive `ui_in` as an SPI controller, shift `0xA5` | Target-role sampling and receive path |
| `test_i2c_master` | Run `i2c_master.s` against a cocotb target model | START, address `0x50`, data `0x42`, ACK sampling, STOP |
| `test_i2c_master_400k` | Run `i2c_master_400k.s`, measure SCL rising-to-rising periods | Same exchange at ~400 kHz; every measured bit period is 80–84 clocks (381–400 kHz at 32 MHz) |
| `test_ps2_device` | Run `ps2_device.s`, decode DATA on CLK falling edges | Start, eight LSB-first data bits, odd parity, stop; data `0x5A` |
| `test_i2c_target` | Run `i2c_target.s` against a cocotb controller model | Address match, ACK, received byte `0x42`, open-drain bus behaviour |
| `test_i2c_target_400k` | Same target, 80-clock SCL periods | Address/data ACKs and `0x42` at 400 kHz timing |
| `test_capture` | Toggle pins with `CAP_EN=1`, drain with `CAP_POP` | Edge detection, timestamped entries, FIFO count/empty status, data ordering |
| `test_capture_overflow` | Ten pin changes into the eight-entry FIFO | Full flag set, count saturates at 8, extra events dropped |
| `test_pin_wait` | `WAIT_PIN0/1` on `ui_in[0]` | Level-sensitive stall and release, no missed edge |
| `test_opcode_sweep` | Every opcode/subop pair, fixed preamble, 30-cycle window | All 96 encodings execute identically on RTL and ISS |
| `test_random_cosim` | 48-instruction random program, 1,000 enabled clocks | Full architectural lock-step against the ISS after every clock |

The protocol tests use real timing relationships: UART at 417 cycles/bit, SPI
edges separated by `WAIT 2`, I2C open-drain with a bus model that pulls SDA low
for ACKs. They are not unit tests of isolated combinational blocks.

### Toolchain tests

```
7 passed
```

These cover encode/decode round-trip for all 96 defined encodings, every
assembler mnemonic, directives and data layout, assembler error handling, ISS
arithmetic/memory, exact `WAIT` semantics, and `DJNZ`/stack behaviour.

## 3. Synthesis and lint

Yosys with the IHP SG13CMOS5L `typ_1p20V_25C` liberty, `abc` mapping, and
`check -assert`:

| Metric | Value |
|---|---:|
| Mapped cell area | 257,363 µm² |
| Nominal 6×4 tile area | 751,440 µm² (24 × 202 × 155 µm) |
| Fraction of nominal area | 34.2% |
| Sequential cells | 151,963 µm² (59.05%) |
| Flip-flops | 3,102 |
| Program RAM | 162k µm² (63% of the design) |
| Latches inferred | 0 |
| Multiply/divide cells | 0 |

The 256-word variant was measured at 420,028 µm² (56%) and rejected; see
`AGENTS.md` D-009. The 128-word build leaves the remaining area for clock-tree
buffers, routing, and timing repair.

Verilator `-Wall` reports one warning: the `N` flag is not consumed by any
branch in ISA v1. It is architectural state, visible to the ISS and to future
instructions, so the warning is intentional rather than suppressed.

## 4. Hardened build

The Tiny Tapeout GDS action hardened the design on commit `abbebf2` and produced
a GDS, LEF, SPEF, and OASIS for the 6×4 SG13CMOS5L allocation. Run:
`actions/runs/40903018243`. This is the authority for the numbers below; the
local synthesis figure is only an estimate of them.

| Metric | Value |
|---|---:|
| Die bounding box | 1,289.28 × 710.64 µm (916,214 µm²) |
| Core area | 902,417 µm² |
| Placed standard-cell area | 383,307 µm² |
| Setup slack, slow `1p08V/125C` | **+6.103 ns** (0 violating paths) |
| Setup slack, typical `1p20V/25C` | +15.318 ns (0 violating paths) |
| Setup slack, fast `1p32V/-40C` | +20.144 ns (0 violating paths) |
| Hold slack, slow / typical / fast | +0.685 / +0.331 / +0.124 ns |
| Total power, typical | 7.35 mW (6.13 internal, 1.18 switching, 0.04 leakage) |
| DRC errors | 0 |
| LVS errors | 0 |

The worst path that broke the 48 MHz run needed 25.0 ns. At the declared
31.25 ns period the slow corner now reports 6.10 ns of margin, which matches
the 6.25 ns the retime predicted. Area is not the constraint: of the 902,417 µm²
core, only 383,307 µm² is standard-cell logic, and the rest is fill, decap, and
the pad ring.

Every job that gates the chip passed: `gds`, `precheck`, and `gl_test`. Only
the optional Pages `viewer` job failed, and its log shows GitHub Pages is not
enabled for the repository (HTTP 404 on deployment), not a design error.

### Gate-level tests

The `GATES=yes` path runs the same cocotb suite against a flattened netlist.
Three co-simulation tests read named core registers and are skipped there; the
other 17 drive real pins. They pass on **both** the synthesis netlist and the
post-place-and-route netlist, using the Icarus 13 build the action ships:

```
GATES=yes: 17 passed, 3 skipped, 0 failed
```

## 5. What is not proven

These are the honest gaps. They are not covered by the numbers above.

- **No silicon measurement.** Every timing and power number above is a
  signoff-tool result on the hardened netlist, not a measurement of a chip.
- **No FPGA run.** The repository keeps the template FPGA workflow, but it was
  not run for this baseline.
- **The SPI target is verified in mode 0 only.** The SPI master covers modes
  0–3; target-role CPOL/CPHA variants are firmware changes and are not tested.
- **PS/2 is device-to-host transmit only.** There is no keyboard/host receive
  path, no scan-code table, and no bidirectional inhibit handling.
- **No formal verification.** The loader FSM and return stack are tested by
  directed and random simulation, not by properties or equivalence checking.
- **Coverage is behavioural, not line/branch coverage.** No coverage tool was
  run, so no percentage is claimed.
- **The 48 MHz target was not met, and 32 MHz is the declared clock.** The
  first hardened run completed routing, DRC, LVS, and antenna checks, then
  failed post-route setup at the slow corner: WNS -4.1715 ns over 346 paths,
  with a 25.0 ns critical path. The retimed 32 MHz (31.25 ns) build passes with
  +6.10 ns of slow-corner slack. Every real-world rate in the docs assumes
  32 MHz.
- **Three co-simulation tests are RTL-only.** `test_timer_cosim`,
  `test_opcode_sweep`, and `test_random_cosim` read named core registers, which
  the flattened gate-level netlist does not preserve. They are skipped when
  `GATES=yes`; the other 17 pin-level tests exercise the netlist.

## 6. Reproducing

```sh
cd test
make -B

cd ..
python3 -m pytest -q tools/test_isa.py

PDK_ROOT=$HOME/pdk/IHP-Open-PDK ./scripts/synth_area.sh
verilator --lint-only -Wall -Wno-fatal --top-module tt_um_proteus -Isrc \
  src/tt_um_proteus.v src/proteus_core.v src/proteus_loader.v \
  src/proteus_prog_ram.v src/proteus_data_ram.v src/proteus_capture.v
```

The exact pass/fail table is printed by cocotb at the end of `make -B`.
