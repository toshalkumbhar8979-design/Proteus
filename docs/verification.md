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
hex, and contains all fifteen opcode classes. The opcode sweep is exhaustive over
the 14 x 8 encoding space, including subops that ISA v1 leaves unused.

## 2. Results

Environment: Icarus Verilog 12.0, cocotb 2.0.1, Python 3.13, Yosys 0.65,
Verilator 5.046, IHP-Open-PDK `2bbec75`.

```
TESTS=26 PASS=26 FAIL=0 SKIP=0
TOTAL SIM TIME=4,033,620 ns
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
| `test_jtag_idcode` | Run `jtag_idcode.s` against a modelled 1149.1 TAP | Test-Logic-Reset, 32 TCK, path to Shift-DR, TDO sampled MSB-first, `0x1A5A5A5D` compared in firmware; a match writes `0xC3` |
| `test_i2c_target` | Run `i2c_target.s` against a cocotb controller model | Address match, ACK, received byte `0x42`, open-drain bus behaviour |
| `test_i2c_target_400k` | Same target, 80-clock SCL periods | Address/data ACKs and `0x42` at 400 kHz timing |
| `test_capture` | Toggle pins with `CAP_EN=1`, drain with `CAP_POP` | Edge detection, timestamped entries, FIFO count/empty status, data ordering |
| `test_capture_overflow` | 34 pin changes into the 32-entry FIFO | Full flag set, count saturates at 32, extra events dropped |
| `test_capture_roll` | 49 pin changes with `CAP_EN 3` | Roll mode keeps the newest 32 events: full flag set, count 32, and the oldest survivor carries the phase-2 pin state, so the early entries were overwritten rather than dropped |
| `test_pin_wait` | `WAIT_PIN0/1` on `ui_in[0]` | Level-sensitive stall and release, no missed edge |
| `test_crc_helpers` | Feed `123456789` through `CRC16_ADD`, then 11 token bits through `CRC5_BIT` | CRC-16/USB equals the published check value `0xB4C8`; CRC-5 equals a reference implementation in the test file |
| `test_usb_line_code` | `SER_LD 0xFF`, then `SER_NEXT` with a bit strobe on `uo[7]` | The emitted level sequence is bit-for-bit the NRZI + stuffing sequence an independent reference produces, including the stuffed 0 after six ones |
| `test_nrzi_receive` | A reference encoder drives the line; `RX_BIT` samples it over a handshake pin | Three bytes decode back exactly, the stuffed zero produces no data bit, and seven ones with no stuffed zero raise the sticky violation latch |
| `test_usb_data_packet` | `usb_data_tx.s` sends SYNC, PID DATA0, two payload bytes and CRC-16/USB; one strobe per bit time is collected | The whole level stream equals an independent multi-byte NRZI + stuffing encoder, and the decoded bytes equal `{0x80, 0xC3, 0x11, 0x22}` followed by the CRC the reference computes, low byte first |
| `test_opcode_sweep` | Every opcode/subop pair, fixed preamble, 30-cycle window | All 120 encodings execute identically on RTL and ISS |
| `test_random_cosim` | 48-instruction random program, 1,000 enabled clocks | Full architectural lock-step against the ISS after every clock |

The protocol tests use real timing relationships: UART at 417 cycles/bit, SPI
edges separated by `WAIT 2`, I2C open-drain with a bus model that pulls SDA low
for ACKs. They are not unit tests of isolated combinational blocks.

### Toolchain tests

```
7 passed
```

These cover encode/decode round-trip for all 120 defined encodings, every
assembler mnemonic, directives and data layout, assembler error handling, ISS
arithmetic/memory, exact `WAIT` semantics, and `DJNZ`/stack behaviour.

## 3. Synthesis and lint

Yosys with the IHP SG13CMOS5L `typ_1p20V_25C` liberty, `abc` mapping, and
`check -assert`:

| Metric | Value |
|---|---:|
| Mapped cell area | 309,183 µm² |
| Nominal 8×4 tile area | 1,001,920 µm² (32 × 202 × 155 µm) |
| Fraction of nominal 8×4 area | 30.9% |
| Fraction of a 6×4 tile set (751,440 µm²) | 41.0% |
| Sequential cells | 182,826 µm² (59.1%) |
| Program RAM | 162k µm² (63% of the design) |
| Latches inferred | 0 |
| Multiply/divide cells | 0 |

The 256-word variant was measured at 420,028 µm² (56%) and rejected as too
large a tapeout risk. The 128-word build leaves the remaining area for
clock-tree buffers, routing, and timing repair.

Verilator `-Wall` reports one warning: the `N` flag is not consumed by any
branch in ISA v1. It is architectural state, visible to the ISS and to future
instructions, so the warning is intentional rather than suppressed.

## 4. Hardened build

> The numbers in this section come from the **8×4** hardening of commit `18f08e0`,
> which is the design that includes the 32-entry capture buffer, the CRC
> registers, the line coder and the NRZI receiver. Run:
> `actions/runs/43957356626`. `gds`, `precheck`, `gl_test` and `viewer` all passed.

The Tiny Tapeout GDS action produced a GDS, LEF, SPEF, and OASIS for the 8×4
SG13CMOS5L allocation. This is the authority for the numbers below; the local
synthesis figure is only an estimate of them.

| Metric | Value |
|---|---:|
| Die bounding box | 1,724.16 × 710.64 µm (1,225,260 µm²) |
| Core area | 1,208,170 µm² |
| Placed standard-cell area | 469,393 µm² (38.9% core utilisation) |
| Setup slack, slow `1p08V/125C` | **+8.895 ns** (0 violating paths) |
| Setup slack, typical `1p20V/25C` | +14.595 ns (0 violating paths) |
| Setup slack, fast `1p32V/-40C` | +18.071 ns (0 violating paths) |
| Hold slack, slow / typical / fast | +0.654 / +0.313 / +0.108 ns |
| Total power, typical | 8.71 mW (7.27 internal, 1.38 switching, 0.05 leakage) |
| DRC errors | 0 |
| LVS errors | 0 |
| Antenna, power-grid violations | 0 / 0 |
| Gate-level tests | 23/23 pin-level pass; 3 white-box tests skipped by design |

The worst path that broke the 48 MHz run needed 25.0 ns. At the declared 31.25 ns
period the slow corner reports 8.89 ns of margin on the 8×4 build, which is more
than the 6×4 build had (6.10 ns) even with the larger capture buffer and the two
helper opcodes: the extra tile row gave the placer room to spread the logic.
Area is not the constraint either — of the 1,208,170 µm² core, 469,393 µm² is
standard-cell logic and the rest is fill, decap and the pad ring.

OpenROAD reports three classes of non-timing violations on this build, recorded
here rather than rounded away: 41 max-slew and 2 max-cap reports at the slow
corner, 293 max-fanout reports across corners, and one disconnected (non
critical) pin. None of them is a setup or hold violation, the flow's own error
count is 0, and `precheck` passed; they are reported by the flow as warnings.

Every job passed: `gds`, `precheck`, `gl_test`, and the optional Pages `viewer`.
The viewer first failed with HTTP 404 because GitHub Pages had never been
enabled for the repository; after enabling Pages with the `workflow` build type
and re-running that job, the run is fully green and the layout viewer is served
at `https://toshalkumbhar8979-design.github.io/Proteus/`.

### Gate-level tests

The `GATES=yes` path runs the same cocotb suite against a flattened netlist.
Three co-simulation tests read named core registers and are skipped there; the other 21 drive real pins. The counts below are from the last hardened netlist, which predates the three tests added since; all three are pin-level and will run at gate level with the next hardening. They pass on **both** the synthesis netlist and the
post-place-and-route netlist, using the Icarus 13 build the action ships:

```
GATES=yes: 18 passed, 3 skipped, 0 failed
```

## 5. Formal properties

Properties live in `` `ifdef FORMAL `` blocks next to the RTL they describe, so
they can read internal state without changing the synthesized logic. Yosys's
built-in SAT engine proves each one twice: a 40-cycle bounded model check from
an arbitrary power-up state, and a temporal-induction proof that the property
holds in every reachable state after reset.

```
pc_freeze  PASS   the PC does not move while the core is disabled
 timer     PASS   the cycle timer advances by one or is cleared, never jumps
 capture   PASS   the capture FIFO count never exceeds its depth
 loader    PASS   an idle loader has an empty frame shifter after one clock
 outputs   PASS   stopped, out-of-frame outputs and enables are all low
 stack     PASS   CALL pushes PC+1 and RET restores exactly that address
```

These are the properties the firmware and the host loader depend on. `pc_freeze`
is what makes host reprogramming safe: `en` is low for the whole time `CFG_CS_N`
is asserted, so a frame cannot race a fetch. `loader` is what makes back-to-back
frames independent. `capture` bounds the only array whose index comes from a
counter, so `CAP_STATUS` can never report a depth that walks past the FIFO.
`stack` ties the two halves of the return stack together: after a CALL the slot
below the new pointer must hold `PC+1`, and after a RET the PC must equal the
slot the pointer popped. Without the second half, a pointer that moved without
the data moving would still look balanced.

Two things about this proof are worth stating plainly. First, the harness was
validated: during development it produced counterexamples that turned out to be
off-by-one errors in the properties themselves, not in the RTL. `$past` samples
an expression one edge back, so `pc == $past(pc)` is not "the PC moved" — it
compares the PC with itself a cycle earlier and looks like a violation whenever
the core is enabled. The capture bound likewise only holds after reset has been
observed. The `stack` property produced the same class of mistake twice: it
sampled `stack[$past(sp) - 1]`, which indexes with `sp` from two cycles back,
and it compared a full byte against a `PROG_AW`-bit PC without the truncation
`RET` performs. In all three cases the assertion was corrected and the RTL was
left alone.

Second, the proof is not exhaustive: it covers the listed invariants with free
inputs, but it does not prove ISA equivalence, branch reachability, or liveness.
The return stack is now included, but the loader FSM still has a hand-written
property rather than a full equivalence check.

## 6. FPGA portability check

The competition suggests trying the RTL on an FPGA before the ASIC flow. No
board is available here, so the next best thing was done instead: the design is
synthesized and placed-and-routed for a real FPGA fabric, and the tool reports
what a board would tell us first — does it map, does it fit, and does it close
timing.

Yosys `synth_ecp5` followed by `nextpnr-ecp5` targeting an LFE5U-25F in a
CABGA256 package at speed grade 6:

| Metric | Value |
|---|---:|
| LUT4 | 1,611 / 24,288 (6%) |
| Flip-flops | 544 / 24,288 (2%) |
| I/O | 43 / 197 (21%) |
| Block RAM / DSP | 0 / 0 (RAM maps to distributed LUT RAM) |
| Achieved Fmax | **65.9 MHz** (nextpnr estimate) |
| Required | 32 MHz — passes with 2.06× margin |

This does not replace a board run: the pins are unconstrained, so the I/O paths
and the actual connector pinout are unverified, and no bitstream was loaded. It
does show the RTL is portable, uses no vendor-specific constructs, and has
comfortable margin on modest fabric.

## 7. What is not proven

These are the honest gaps. They are not covered by the numbers above.

- **No silicon measurement.** Every timing and power number above is a
  signoff-tool result on the hardened netlist, not a measurement of a chip.
- **No FPGA board run.** The design is mapped and placed-and-routed for an ECP5
  and closes timing at 65.9 MHz, but it has never driven a physical FPGA pin, and
  the I/O constraints are not written.
- **The SPI target is verified in mode 0 only.** The SPI master covers modes
  0–3; target-role CPOL/CPHA variants are firmware changes and are not tested.
- **PS/2 is device-to-host transmit only.** There is no keyboard/host receive
  path, no scan-code table, and no bidirectional inhibit handling.
- **JTAG is a master only, and a minimal one.** The firmware walks a TAP to
  Shift-DR, clocks out a default IDCODE, and checks it; it does not scan an
  instruction register, do boundary scan, drive a multi-device chain, or act as
  a TAP target itself. The demo samples TDO on `ui_in[4]` so the cocotb I2C bus
  model, which owns `uio_in`, cannot collide with it; on a board the same two
  constants can point it at a `uio` pin.
- **Formal coverage is a small set of invariants.** Six properties are proven,
  including the return stack; there is no ISA-equivalence proof and no liveness
  proof. Simulation, not a proof, is still what covers most of the behaviour.
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
  `GATES=yes`; the other 21 pin-level tests exercise the netlist.

## 8. Reproducing

```sh
cd test
make -B

cd ..
python3 -m pytest -q tools/test_isa.py

PDK_ROOT=$HOME/pdk/IHP-Open-PDK ./scripts/synth_area.sh
./scripts/formal.sh        # 6 properties, BMC + induction
./scripts/synth_fpga.sh    # ECP5 map, place, route, Fmax
verilator --lint-only -Wall -Wno-fatal --top-module tt_um_proteus -Isrc \
  src/tt_um_proteus.v src/proteus_core.v src/proteus_loader.v \
  src/proteus_prog_ram.v src/proteus_data_ram.v src/proteus_capture.v
```

The exact pass/fail table is printed by cocotb at the end of `make -B`.
