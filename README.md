# Proteus-1

**A field-reprogrammable protocol engine for the Jane Street × Tiny Tapeout ASIC
competition.** One 6×4 CMOS5L tile set, reprogrammable after fabrication, with
an assembler, a cycle-accurate ISS, and a cocotb verification suite.

Proteus-1 is not a bag of fixed UART, SPI, and I2C peripherals. It is a
cycle-deterministic 8-bit CPU whose instruction set is built around pins, edges,
and time, plus a host loader and a capture FIFO for looking at live buses.

![Proteus-1 block diagram: the host loader feeding program and data memory, the
single-cycle core, pin registers and capture, and the pad ring](docs/images/block_diagram.png)

*One core, two memories, twenty-four pins. Each memory sits directly above the
core port that addresses it, so every net is a straight stub in a gutter and no
wire crosses a block. Every arrow is a net that exists in
[`src/tt_um_proteus.v`](src/tt_um_proteus.v). Source:
[`docs/figures/block_diagram.tex`](docs/figures/block_diagram.tex); rebuild with
`make figures`.*

## Why a protocol CPU?

Protocol emulation is a **timing** problem, not a peripheral checklist.

- Every ordinary instruction retires in **exactly one clock**. No pipeline, no
  branch penalty, no hidden wait state.
- `WAIT n` burns exactly `n` clocks (0 means 256).
- `WAIT_PIN0/1` and `WAIT_EDGE` stall on a masked pin level or edge.
- `SETB` / `CLRB` / `TGLB` change pins without touching the accumulator.
- A 16-bit cycle counter timestamps every capture.
- The 8-entry capture FIFO records `{timer[7:0], uio_in, ui_in}` on every pin
  change, so the same chip can **observe** a bus as well as drive it.
- Each bidirectional pin has output enable **and open-drain** control, which is
  what I2C, wired-OR buses, and target-role emulation need.

New protocols are firmware loaded over the configuration port after
fabrication. The same chip can be a UART, an SPI controller in modes 0–3, an
I2C target, a PS/2 device, a JTAG/SWD bit-banger, or a small logic analyzer.

## Verified today

Every claim below is reproducible from this repository. The hardened numbers
come from the passing [GDS run](https://github.com/toshalkumbhar8979-design/Proteus/actions/runs/40903018243).

| Item | Result |
|---|---|
| RTL | 6 Verilog-2001 modules, one clock, every flop reset |
| Cocotb tests | **21/21 pass** (reset, loader, ALU/memory, waits, timer, UART, SPI modes 0–3, I2C master/target 100/400 kHz, PS/2, JTAG master, capture + overflow, opcode sweep, co-simulation) |
| RTL vs ISS | all 96 opcode/subop encodings executed in lock-step, plus 1,000 randomized cycles; every architecturally visible register compared |
| Assembler/ISS tests | **7/7 pass** |
| Synthesis | **257,363 µm²** mapped IHP `typ_1p20V_25C` cells, 34% of the nominal 6×4 area |
| Latches / multiply / divide | none (`check -assert` passes) |
| Lint | Verilator `-Wall`: one intentional warning (`N` flag has no branch in ISA v1) |
| GDS / precheck | **hardened and clean**: 0 DRC errors, 0 LVS errors, precheck and gate-level test pass |
| Post-route timing | **32 MHz passes all three corners**: slow-corner setup slack **+6.10 ns**, 0 violating paths, hold positive everywhere |
| Hardened area | 1,289 × 711 µm die; 383,307 µm² of placed standard cells; 7.35 mW typical at 32 MHz |
| Formal | **6 invariants proved** with yosys SAT, bounded and by induction (PC freeze, timer monotonicity, FIFO bound, loader frame isolation, idle outputs, CALL/RET return stack) |
| FPGA portability | ECP5 25k: 1,611 LUT4 (6%), 544 FF (2%), **65.9 MHz** against the 32 MHz target — mapped and routed, no board needed |

## The layout

![Proteus-1 layout rendered from the submitted GDS with KLayout: standard-cell
rows under Metal1 to Metal4, with the Metal4 power straps running the full
height of the die](docs/images/die.png)

*Rendered by KLayout 0.30 from `tt_um_proteus.gds` in the `tt_submission`
artifact of the passing GDS run, 1800 px across the 1.29 × 0.71 mm 6×4
allocation. The dense field is standard-cell logic under Metal1–Metal3, the
dark vertical bars are the Metal4 power straps, and the pale margins are fill
cells. The submitted GDS carries the design only — 58 cells, no pad instances —
so this is the design area, not the assembled chip. Rebuild with `make die`
after `gh run download -n tt_submission -D build/sub`.*

## One core, every protocol

There is no UART block, no SPI block, no I2C block. The table below is the same
hardened core — 383,307 µm² of placed cells — running eight different images.
Every row is a cocotb test against the RTL through the real loader, not a
hand-written waveform.

| Protocol | Role | Timing at 32 MHz | Mechanism in firmware | Test |
|---|---|---|---|---|
| UART 8N1 | transmitter | 76.8 kbaud, 417 clocks per bit | `WAIT 417` per bit, `SETB`/`CLRB` on the TX pin | `test_uart_tx` |
| UART 8N1 | receiver | 76.8 kbaud | `WAIT` to the bit centre, sample `ui_in` | `test_uart_rx` |
| SPI | controller | modes 0–3, both clock polarities | drive SCK, sample on the active edge | `test_spi_master`, `test_spi_other_modes` |
| SPI | target | mode 0 | `WAIT_EDGE` on SCK, shift on the pad | `test_spi_target` |
| I2C | controller | ~100 kHz and ~386 kHz (156 and 38-clock half periods) | open-drain `uio`, `WAIT` per phase | `test_i2c_master`, `test_i2c_master_400k` |
| I2C | target | 100 kHz and 400 kHz | open-drain ACK, edge waits on SCL | `test_i2c_target`, `test_i2c_target_400k` |
| PS/2 | device | ~10.5 kHz (9 × `WAIT 167`) | open-drain clock and data, odd parity | `test_ps2_device` |
| JTAG | master | TCK half period from `WAIT` | TAP walk to Shift-DR, 32-bit DR scan | `test_jtag_idcode` |
| Capture | analyzer | every pin change, 8 entries deep | `CAP_EN`, drain through `CAP_UI`/`CAP_UIO` | `test_capture`, `test_capture_overflow` |

Both ends of UART, SPI and I2C are firmware. That is the flexibility claim made
concrete: the hard part of either role is a program, not a hard macro. The price
is that peak throughput is set by the instruction loop, so this design competes
on exactness and reconfigurability, not on raw bit rate.

![JTAG scan waveform: TCK, TMS, TDI and TDO captured from the cocotb run, with
the sampled bits under the clock edges](docs/images/jtag_waveform.png)

*Captured from the simulation, not drawn: eight of the 32 shift clocks of
`test_jtag_idcode`. `TCK` idles high and is pulsed low by the firmware, `TMS` is
held low for the whole scan, and `TDO` is the modelled TAP shifting out its
IDCODE. Regenerate with `python scripts/make_waveform.py` after
`fst2vcd test/tb.fst > test/tb.vcd`.*

## ISA at a glance

Sixteen-bit words: 4-bit opcode, 3-bit sub-opcode, 1-bit port/immediate selector,
8-bit immediate. Twelve instruction classes cover ALU, shifts, load/store, pin
I/O, branches, calls, waits, timer, and capture. The full encoding, flag rules,
and cycle costs are in [`docs/isa.md`](docs/isa.md).

```
LDI A, 0x50        ; one cycle
OUT UO, A          ; one cycle
WAIT 255           ; exactly 255 cycles
SETB UIO, 0x08     ; one cycle, no accumulator clobber
WAIT_PIN1 UI, 0x08 ; stall until the pin is high
CALL uart_tx       ; one cycle, 8-deep return stack
```

## Memory and I/O map

| Region | Size | Notes |
|---|---|---|
| Program | 128 × 16 | asynchronous read, loader write |
| Data | 64 × 8 | direct and `X`-indexed addressing |
| Pins | 24 | `ui_in`, `uo_out`, `uio` with OE/OD |
| Timer | 16 | free-running, atomic low/high read |
| Capture | 8 × 24 | `{timer[7:0], uio_in, ui_in}` per pin change |

## Host loader

SPI mode 0, 32-bit frames `{command, address, data}`, MSB first:

| Command | Action |
|---|---|
| `0x01` | write program word |
| `0x02` | write data byte |
| `0x03` | control (bit 0 = run) |
| `0x04` | latch program word for the next frame's MISO readback |
| `0x00` | no-op / readback frame |

`SCK ≤ clk/4`. The CPU is held in reset while `run=0` and held while `CS_N` is
low. The reference MicroPython host in [`host/proteus_host.py`](host/proteus_host.py)
fills unused program words with `NOP` and data bytes with zero before loading,
because ASIC RAM powers up undefined.

## Example firmware

| Program | Demonstrates |
|---|---|
| [`selftest_basic.s`](programs/selftest_basic.s) | ALU, flags, direct/indexed memory, bit ops, timer signature |
| [`uart_tx.s`](programs/uart_tx.s) | 8N1 transmitter, 76.8 kbaud at 32 MHz, exact 417-cycle bits |
| [`uart_rx.s`](programs/uart_rx.s) | 8N1 receiver, centre sampling, 76.8 kbaud |
| [`spi_master.s`](programs/spi_master.s) | SPI modes 0–1 (CPOL=0), MSB first, `0xA5` |
| [`spi_master_cpol1.s`](programs/spi_master_cpol1.s) | SPI modes 2–3 (CPOL=1), MSB first, `0xA5` |
| [`spi_target.s`](programs/spi_target.s) | SPI target role on `ui_in`, mode 0 |
| [`i2c_master.s`](programs/i2c_master.s) | START/STOP, address `0x28`, write `0x42`, ACK, ~100 kHz |
| [`i2c_master_400k.s`](programs/i2c_master_400k.s) | Same exchange at ~400 kHz; SCL period is measured by the test |
| [`i2c_target.s`](programs/i2c_target.s) | Target role, address `0x50`, open-drain ACK |
| [`ps2_device.s`](programs/ps2_device.s) | PS/2 device transmit: 11-bit frame, odd parity, open-drain clock/data |
| [`jtag_idcode.s`](programs/jtag_idcode.s) | JTAG master: resets a TAP, walks to Shift-DR, clocks 32 bits, checks a default IDCODE |
| [`capture_demo.s`](programs/capture_demo.s) | Capture FIFO records pin changes, firmware drains it |

## Quick start

Prerequisites: Icarus Verilog 12+, Python 3.11+, `cocotb` 2.x, `pytest`, and
Yosys for synthesis.

```sh
# RTL simulation: 21 tests
cd test
python3 -m pip install -r requirements.txt
make -B

# Toolchain unit tests: 7 tests
cd ..
python3 -m pytest -q tools/test_isa.py

# Assemble every example into build/programs
./scripts/build_programs.sh

# Run one image in the ISS
python3 tools/proteus_iss.py build/programs/uart_tx.json --cycles 2000 --trace

# Area estimate against the IHP cells (PDK_ROOT must point at IHP-Open-PDK)
PDK_ROOT=$HOME/pdk/IHP-Open-PDK ./scripts/synth_area.sh
```

## Repository layout

```
src/       synthesizable Verilog and the Tiny Tapeout top module
tools/     assembler, disassembler, ISS, toolchain tests
programs/  assembly sources for UART, SPI, I2C, capture, self-test
test/      cocotb testbench and protocol tests
docs/      architecture, ISA, datasheet, verification report, competition write-up
host/      MicroPython loader for RP2350 / any SPI host
scripts/   synthesis and program-build helpers
```

## Documentation

- [Architecture](docs/architecture.md) — blocks, cycle accounting, pin model, area trade-offs
- [ISA reference](docs/isa.md) — every encoding, flag, and cycle count
- [Datasheet](docs/info.md) — pinout, loader frames, bring-up steps
- [Verification report](docs/verification.md) — what each test proves, and what it does not
- [Competition write-up](docs/competition.md) — design rationale, novelty, AI-use disclosure
- [Submission checklist](docs/submission-checklist.md) — every competition requirement and its evidence
- [Layout viewer](https://toshalkumbhar8979-design.github.io/Proteus/) — interactive 3D view of the hardened GDS

## Status and limitations

The RTL, assembler, ISS, and tests are complete for the competition baseline.
The program memory is 128 words, not 256: synthesis showed the larger memory at
56% of the nominal tile area before routing, which is not a safe tapeout margin.
There is no SRAM macro, no interrupt controller, and no data-memory readback
command. The first hardened run passed DRC, LVS, and antenna checks but missed
post-route setup at 48 MHz; the design was retimed to 32 MHz and the rerun
**passed**, with +6.10 ns of slow-corner setup slack and zero violating paths.
Both the GDS and gate-level jobs are green in CI. See
[`docs/verification.md`](docs/verification.md) for the exact numbers and the
honest list of unproven items, and the
[submission checklist](docs/submission-checklist.md#bottom-line) for what is
still open.

In short: **ready to hand over, not yet handed in.** The design is complete and
green; the competition's submission form has not been opened yet.

## Competition context

- [Jane Street protocol emulator competition](https://www.janestreet.com/tech-talks/)
- [Tiny Tapeout](https://tinytapeout.com/)
- [Tiny Tapeout IHP template](https://github.com/TinyTapeout/ttihp-verilog-template)
- [IHP Open PDK](https://github.com/IHP-GmbH/IHP-Open-PDK)

Target: 6×4 tiles, IHP SG13CMOS5L, March 2027 shuttle, deadline 2027-01-18.

## License

© 2026 Toshal Kumbhar. Apache-2.0 — see [`LICENSE`](LICENSE).

Apache-2.0 rather than MIT, deliberately: it carries an express patent grant,
which matters for a design meant to be built and reused in hardware, and it is
the license the Tiny Tapeout template and the IHP PDK already use. MIT would be
shorter but would leave patent rights implicit. Contributions are accepted under
the same terms.
