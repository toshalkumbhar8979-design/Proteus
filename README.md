# Proteus-1

**A field-reprogrammable protocol engine for the Jane Street × Tiny Tapeout ASIC
competition.** One 6×4 CMOS5L tile set, reprogrammable after fabrication, with
an assembler, a cycle-accurate ISS, and a cocotb verification suite.

Proteus-1 is not a bag of fixed UART, SPI, and I2C peripherals. It is a
cycle-deterministic 8-bit CPU whose instruction set is built around pins, edges,
and time, plus a host loader and a capture FIFO for looking at live buses.

```
          host loader (SPI)                  24 digital pins
 RP2350 ───────────────────────► ┌──────────────────────────────┐
        CS_N SCK MOSI      MISO ──│ loader → 128 × 16 program RAM│
                                  │           64 × 8 data RAM    │
                                  │   ┌──────────────────────┐   │
                                  │   │ Proteus-1 core       │──►│ uo_out[7:0]
                                  │   │ A X Y PC flags       │◄──│ ui_in[7:0]
                                  │   │ timer, capture FIFO  │◄─►│ uio[7:0]
                                  │   └──────────────────────┘   │
                                  └──────────────────────────────┘
```

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

| Item | Result |
|---|---|
| RTL | 6 Verilog-2001 modules, one clock, every flop reset |
| Cocotb tests | **14/14 pass** (reset, loader, ALU/memory, waits, UART, SPI modes 0–3, I2C, capture, co-simulation) |
| RTL vs ISS | 1,000-cycle randomized lock-step, every architecturally visible register compared |
| Assembler/ISS tests | **7/7 pass** |
| Synthesis | **257,363 µm²** mapped IHP `typ_1p20V_25C` cells, 34% of the nominal 6×4 area |
| Latches / multiply / divide | none (`check -assert` passes) |
| Lint | Verilator `-Wall`: one intentional warning (`N` flag has no branch in ISA v1) |
| GDS / precheck / post-route timing | run by the Tiny Tapeout GitHub action after push; not yet claimed |

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
| [`uart_tx.s`](programs/uart_tx.s) | 8N1 transmitter, 115200 baud at 48 MHz, exact 417-cycle bits |
| [`uart_rx.s`](programs/uart_rx.s) | 8N1 receiver, centre sampling, 115200 baud |
| [`spi_master.s`](programs/spi_master.s) | SPI modes 0–1 (CPOL=0), MSB first, `0xA5` |
| [`spi_master_cpol1.s`](programs/spi_master_cpol1.s) | SPI modes 2–3 (CPOL=1), MSB first, `0xA5` |
| [`spi_target.s`](programs/spi_target.s) | SPI target role on `ui_in`, mode 0 |
| [`i2c_master.s`](programs/i2c_master.s) | START/STOP, address `0x28`, write `0x42`, ACK |
| [`i2c_target.s`](programs/i2c_target.s) | Target role, address `0x50`, open-drain ACK |
| [`capture_demo.s`](programs/capture_demo.s) | Capture FIFO records pin changes, firmware drains it |

## Quick start

Prerequisites: Icarus Verilog 12+, Python 3.11+, `cocotb` 2.x, `pytest`, and
Yosys for synthesis.

```sh
# RTL simulation: 14 tests
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

## Status and limitations

The RTL, assembler, ISS, and tests are complete for the competition baseline.
The program memory is 128 words, not 256: synthesis showed the larger memory at
56% of the nominal tile area before routing, which is not a safe tapeout margin.
There is no SRAM macro, no interrupt controller, no data-memory readback command,
and no post-route timing result yet. The GDS action is the authority for timing
and precheck. See [`docs/verification.md`](docs/verification.md) for the honest
list of unproven items.

## Competition context

- [Jane Street protocol emulator competition](https://www.janestreet.com/tech-talks/)
- [Tiny Tapeout](https://tinytapeout.com/)
- [Tiny Tapeout IHP template](https://github.com/TinyTapeout/ttihp-verilog-template)
- [IHP Open PDK](https://github.com/IHP-GmbH/IHP-Open-PDK)

Target: 6×4 tiles, IHP SG13CMOS5L, March 2027 shuttle, deadline 2027-01-18.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
