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
hex, and contains all twelve opcode classes.

## 2. Results

Environment: Icarus Verilog 12.0, cocotb 2.0.1, Python 3.13, Yosys 0.65,
Verilator 5.046, IHP-Open-PDK `2bbec75`.

```
TESTS=19 PASS=19 FAIL=0 SKIP=0
TOTAL SIM TIME=2,440,210 ns
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
| `test_i2c_master_400k` | Run `i2c_master_400k.s`, measure SCL rising-to-rising periods | Same exchange at ~400 kHz; every measured bit period is 110–130 clocks (396 kHz at 48 MHz) |
| `test_ps2_device` | Run `ps2_device.s`, decode DATA on CLK falling edges | Start, eight LSB-first data bits, odd parity, stop; data `0x5A` |
| `test_i2c_target` | Run `i2c_target.s` against a cocotb controller model | Address match, ACK, received byte `0x42`, open-drain bus behaviour |
| `test_i2c_target_400k` | Same target, 120-clock SCL periods | Address/data ACKs and `0x42` at 400 kHz timing |
| `test_capture` | Toggle pins with `CAP_EN=1`, drain with `CAP_POP` | Edge detection, timestamped entries, FIFO count/empty status, data ordering |
| `test_capture_overflow` | Ten pin changes into the eight-entry FIFO | Full flag set, count saturates at 8, extra events dropped |
| `test_pin_wait` | `WAIT_PIN0/1` on `ui_in[0]` | Level-sensitive stall and release, no missed edge |
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

## 4. What is not proven

These are the honest gaps. They are not covered by the numbers above.

- **No place-and-route, no post-route timing, no GDS, no precheck.** LibreLane
  is not installed in the development environment. The local area number is a
  synthesis estimate; the Tiny Tapeout GDS GitHub action is the authority.
- **No gate-level simulation.** The testbench has a `GATES=yes` path, but no
  hardened netlist exists yet to run it against.
- **No silicon.** All protocol results are RTL simulation.
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
- **The 48 MHz target is not measured.** It is the declared clock in
  `info.yaml`; if hardening misses it, the clock and UART constants must be
  reduced.

## 5. Reproducing

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
