# AGENTS.md — The Proteus Agent Bible

> **THIS FILE IS APPEND-ONLY.**
>
> Never delete it, rename it, truncate it, reorder it, or rewrite an existing line.
> Never "clean up", reformat, or regenerate this file with a tool.
> If a decision changes, **strike through** the old text with `~~...~~`, then
> append a new dated entry that explains the replacement. The history stays
> visible forever. Corrections are additions, not deletions.
>
> If you are an automated agent: read this file completely before changing
> anything in this repository. Treat every line above your edit as immutable.

Project: **Proteus-1**, a field-reprogrammable protocol emulator ASIC.
Target: Jane Street Protocol Emulator ASIC Competition.
Process: IHP SG13CMOS5L via Tiny Tapeout (6x4 tiles, 8x4 upgrade planned).
Deadline: **2027-01-18**.

---

## 1. Mission

Build the most flexible, best-verified, best-documented open-source protocol
emulator that fits a 6x4 Tiny Tapeout CMOS5L allocation. The chip must be
reprogrammable after fabrication and must demonstrate UART, SPI, and I2C with
controller and target roles. Stretch targets are low-speed USB, 10BASE-T,
JTAG/SWD, PS/2, and CAN. Novel architecture and rigorous verification are worth
more than a long protocol checklist.

## 2. Non-negotiable engineering rules

1. **Synthesizable RTL only.** Verilog-2001-compatible constructs unless the
   Tiny Tapeout flow explicitly accepts the construct. No latches, no
   combinational loops, no `initial` blocks in synthesized code, no delays.
2. **Reset every flop.** ASIC flops power up to an unknown value. Every register
   must have a defined reset value or be loaded before use. The CPU is held in
   reset until the host releases it.
3. **One clock domain.** `clk` only. Asynchronous host pins are synchronized
   with two flip-flops before use.
4. **Every output assigned.** `uo_out`, `uio_out`, and `uio_oe` must never be
   left floating or undriven in any mode.
5. **No hidden state.** The ISA, assembler, instruction-set simulator, RTL, and
   tests must agree. An ISA change is one atomic commit touching all five.
6. **Tests before push.** `make -B` in `test/` and the Python assembler/ISS
   tests must pass. A failing test is never "fixed" by weakening the assertion.
7. **Public artifacts are competition artifacts.** Commit messages, README,
   docs, comments, issue text, and PR descriptions must not contain AI tool
   names, AI attribution, or generated-by trailers. Do not tag any AI service.
8. **Open source.** RTL, tools, tests, and documentation are public and
   Apache-2.0 licensed. Third-party code keeps its original license and notice.
9. **Area is a feature.** Prefer combinational sharing, narrow counters, and
   small memories. Run synthesis after every non-trivial RTL change.
10. **Document the why.** Every non-obvious block gets a comment explaining the
    protocol or timing reason, not just the signal names.

## 3. Repository map

| Path | Purpose |
|---|---|
| `src/` | Synthesizable RTL and the Tiny Tapeout top module |
| `src/proteus_defs.vh` | Opcode and configuration constants shared by RTL |
| `tools/` | Assembler, disassembler, ISS, program builder, host loader |
| `programs/` | Assembly sources for UART, SPI, I2C, and self-tests |
| `test/` | Cocotb testbench, RTL tests, gate-level test hooks |
| `docs/` | Architecture, ISA, verification report, competition write-up |
| `host/` | RP2350 / MicroPython host loader and demo scripts |
| `scripts/` | Synthesis, area, lint, and formatting helpers |
| `AGENTS.md` | This append-only constitution |

## 4. Architecture decisions (append-only log)

### 2026-10-29 — D-001: Project name and identity

The project is **Proteus-1**. The name refers to a shape-changing protocol
engine: one small chip that becomes a UART, an SPI controller, an I2C target,
or a logic analyzer after fabrication. Top module: `tt_um_proteus`.

### 2026-10-29 — D-002: Core shape

Proteus-1 is a **single-cycle 8-bit accumulator CPU** with an instruction set
specialized for pin-level timing. All ordinary instructions retire in one clock.
Only `WAIT`, `WAIT_PIN`, `WAIT_EDGE`, and `HALT` hold the program counter. This
gives exact, documented cycle counts without a pipeline or branch penalties.

Registers: 8-bit `A`, `X`, `Y`; 8-bit `PC`; 8-deep return stack; `Z`, `C`, `N`
flags. Data memory: 64 bytes. Program memory: 128 or 256 16-bit words, decided
by the area measurement (D-006).

### 2026-10-29 — D-003: Pin model

24 digital pins: 8 dedicated inputs (`ui_in`), 8 dedicated outputs (`uo_out`),
8 bidirectional pins (`uio`). The bidirectional pins have per-bit output enable
and per-bit open-drain mode, so I2C, wired-OR buses, and shared SPI/I2C pinouts
are possible without external glue. `uio_in` always reads the actual pad.

### 2026-10-29 — D-004: Host loader

Programs are loaded over a **write-only synchronous serial port** on
`ui_in[7:5]` (`CS_N`, `SCK`, `MOSI`) with status on `uo_out[7]` (`MISO`). The
32-bit frame is `{command[7:0], address[7:0], data[15:0]}`, MSB first. The CPU
is held in reset while `CS_N` is low. Commands: `0x01` write program word,
`0x02` write data byte, `0x03` control (bit 0 = run). SCK is synchronized and
must be at most `clk/4`. The config pins remain usable as GPIO after `CS_N`
returns high, but the host must not toggle them while the CPU is running.

### 2026-10-29 — D-005: Timing assistance

The core includes a free-running 16-bit cycle counter with an atomic low/high
read sequence, a pin-wait instruction family (level and edge, on `ui` or `uio`),
and an 8-entry capture FIFO that records `{cycle[7:0], uio_in, ui_in}` on every
pin change. The capture FIFO is the "protocol analyzer" half of the emulator:
capture a waveform, read it back, decode or replay it.

### 2026-10-29 — D-006: Program memory size is decided by synthesis

Program memory is inferred as flip-flops with an asynchronous read port and a
synchronous loader write port. It is parameterized. The initial target is 128 x
16; if synthesis against the IHP CMOS5L standard cells shows comfortable area
headroom in a 6x4 tile, the final target is 256 x 16. Do not add an SRAM macro
unless the LibreLane flow is actually run and the macro placement, power grid,
and LVS checks are verified. A safe 128-word design that tapes out beats a
failed 512-word design.

### 2026-10-29 — D-007: Verification gates

A change is not "done" until these pass:

1. `iverilog` elaboration with no implicit-wire warnings.
2. Cocotb self-tests for reset, loader, ALU, branches, stack, memory, I/O,
   wait, timer, and capture.
3. Python ISS co-simulation on randomized instruction sequences, comparing
   every retired instruction and the final architectural state.
4. Protocol loopback tests: UART TX/RX, SPI modes 0-3, I2C controller and
   target waveforms.
5. Yosys synthesis with the IHP `typ_1p20V_25C` liberty; no latches, no
   multiply/divide cells, and a reported cell area well inside the tile budget.
6. Gate-level smoke test after hardening, if the local LibreLane flow is
   available.

### 2026-10-29 — D-008: What "winning" means

Judging weighs flexibility, protocols demonstrated, architecture, and
verification. The submission therefore includes: a readable ISA, a real
assembler and ISS (not a hand-written hex blob), example firmware for UART,
SPI, and I2C, a capture/analysis demo, a verification report with coverage
numbers, a reproducible host script, and honest limitations. Claims must match
what the tests actually prove.

### 2026-10-29 — D-009: Program memory fixed at 128 x 16

The 256-word experiment synthesized to **420,028 µm²**, or 56% of the nominal
6x4 tile area (751,440 µm²), before clock-tree buffers and routing. The
128-word build synthesizes to **257,363 µm²** (34%), with 3,102 flip-flops and
59% of the area in sequential cells. The 128-word configuration is selected.
The two-instruction-per-word budget is worked around with assembler macros and
separate protocol images. Do not revisit SRAM or 8x4 unless the LibreLane macro
flow is actually run and verified (D-006).

### 2026-10-29 — D-010: Verified baseline and clock target

Baseline evidence for the submission:

- 13 cocotb tests pass: reset, loader readback, ALU/memory self-test, exact
  `WAIT` timing, UART TX and RX, SPI controller and target, I2C controller and
  target, capture FIFO, pin waits, and a 1,000-cycle randomized lock-step
  comparison against the Python ISS.
- Seven assembler/disassembler/ISS unit tests pass.
- Yosys maps the design to 257,363 µm² of IHP `typ_1p20V_25C` cells with no
  latches or multiply/divide cells.
- Verilator `-Wall` reports one intentional warning: the `N` flag is
  architectural state but no branch consumes it in ISA v1.

The declared clock is **48 MHz**. That is a target, not a measured post-route
result; the Tiny Tapeout GDS action has the final say. The UART examples use
417 cycles per bit, which is 115.2 kbaud at 48 MHz with 0.08% error.

### 2026-10-29 — D-011: SPI modes 0–3 verified; test count now 14

D-010 recorded 13 tests and SPI mode 0 only. The master examples now cover
CPOL=0 (`spi_master.s`) and CPOL=1 (`spi_master_cpol1.s`), and
`test_spi_other_modes` checks the three remaining sampling conventions against a
mode-aware cocotb receiver. All 14 tests pass. The SPI target remains mode 0
only. This supersedes the test count and SPI-coverage sentence in D-010; the
rest of D-010 stands.

### 2026-10-29 — D-012: 400 kHz I2C master verified; test count now 15

D-011 recorded 14 tests and I2C at roughly 100 kHz. `i2c_master_400k.s` now uses
a 57-cycle half-period bit loop (about 121 clocks per SCL period, 396.7 kHz at
48 MHz), and `test_i2c_master_400k` verifies both the exchange and a measured
110–130-clock SCL period. All 15 tests pass. The I2C target remains 100 kHz.
This supersedes the test count and I2C-coverage sentence in D-011; the rest of
D-011 stands.

### 2026-10-29 — D-013: PS/2 device transmitter verified; test count now 16

D-012 recorded 15 tests and no protocol outside UART/SPI/I2C. `ps2_device.s` now
implements a device-to-host PS/2 frame on `uio[0]` (DATA) and `uio[1]` (CLK),
using open-drain pins and a 9 x `WAIT 250` bit delay (about 10.5 kHz).
`test_ps2_device` decodes start, eight LSB-first data bits, odd parity, and stop
for `0x5A`. All 16 tests pass. This adds a fourth protocol to the demonstration
set; it does not claim host/keyboard receive support. The rest of D-012 stands.

### 2026-10-29 — D-014: 400 kHz I2C target verified; test count now 17

D-013 recorded 16 tests and a 100 kHz I2C target. `test_i2c_target_400k` drives
the same `i2c_target.s` firmware with 120-clock SCL periods, which is 400 kHz at
the declared 48 MHz clock. Address and data ACKs plus the received `0x42` are
checked. All 17 tests pass. The target firmware is unchanged; this is a timing
coverage addition, not a new fixed-function block. The rest of D-013 stands.

### 2026-10-29 — D-015: Directed timer regression; test count now 18

D-014 recorded 17 tests. `test_timer_cosim` runs a directed program that clears
the 16-bit timer, reads the atomic low/high pair, waits past 255 cycles, and
reads again. Every enabled clock is compared against the ISS, including the
timer, latched high byte, wait state, and halt state. All 18 tests pass. This
closes the timer item in D-007's gate; the rest of D-014 stands.

### 2026-10-29 — D-016: Capture FIFO overflow asserted; test count now 19

D-015 recorded 18 tests and left the capture overflow path unasserted.
`test_capture_overflow` drives ten pin changes into the eight-entry FIFO and
checks that `CAP_STATUS` returns full with count 8, so the drop path is now a
tested guarantee rather than an implementation detail. All 19 tests pass. The
rest of D-015 stands.

## 5. Open questions (append answers, do not delete)

- Q-001: Final GitHub username for `top_module` and repo URL. Until known, use
  `tt_um_proteus` and the repository name `proteus-protocol-engine`.
- Q-002: 6x4 or 8x4 final tile count. 6x4 is the safe submission; 8x4 is an
  upgrade only if the template and flow are available and area requires it.
- Q-003: Whether a full LibreLane hardening can run locally in the available
  environment. If not, the GitHub GDS action is the authority and the local
  synthesis report is an estimate, clearly labeled as such.
- A-003: LibreLane is not installed in the available WSL environment and the
  IHP PDK is present only for synthesis. Local hardening is therefore not
  claimed; the repository ships the Tiny Tapeout GDS workflow, and its
  precheck/timing results become the authority once the repository is pushed.
- A-002: Staying at 6x4. The 128-word design uses 34% of nominal tile area, so
  the 8x4 upgrade is not needed and would add packaging risk.

## 6. How to append to this file

Append only. Use this shape:

```
### YYYY-MM-DD — D-0NN: Short title

What changed, why, and what evidence supports it. If this supersedes an earlier
decision, reproduce the old text with ~~strikethrough~~ here and state the
replacement. Never edit the old entry in place.
```

If a line is wrong, strike it through where it stands and add the correction
below. Do not delete the wrong line. The visible history is part of the
competition submission.
