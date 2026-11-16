# Proteus-1 Architecture

## 1. The problem

A protocol emulator is not a protocol checklist. It is a machine that has to
produce and sample edges with a known delay, then change its behaviour when a
new protocol appears. Fixed UART/SPI/I2C blocks are easy to add and impossible
to make future-proof. A general-purpose CPU is reprogrammable but usually hides
its timing behind a pipeline, interrupts, and variable-length instructions.

Proteus-1 takes the third path: a **single-cycle protocol CPU**. Every ordinary
instruction has a published one-clock cost, the pin registers are architectural
state, and the only multi-cycle instructions are explicit waits. Firmware can
therefore be written as a timing diagram.

## 2. Block diagram

```
                       ┌──────────────────────────────────────────────┐
  ui_in[7:5] ─────────►│ loader: SPI target, 32-bit frames, readback   │
  uo_out[7]  ◄─────────│ run control, program/data write ports        │
                       └───────┬───────────────────────┬──────────────┘
                               │ program words         │ data bytes
                               ▼                       ▼
                       ┌───────────────┐       ┌───────────────┐
                       │ 128 x 16      │       │ 64 x 8        │
                       │ program RAM   │       │ data RAM      │
                       └───────┬───────┘       └───────┬───────┘
                               │ instr                 │ data
                       ┌───────▼───────────────────────▼───────┐
  ui_in[4:0] ─────────►│                                       │
  uio_in[7:0] ────────►│  Proteus-1 core                       │──► uo_out[6:0]
                       │  A, X, Y, PC[6:0], Z/C/N, 8-deep stack│◄── uio_out[7:0]
                       │  ALU, shifts, pin ops, branches       │──► uio_oe[7:0]
                       │  16-bit cycle timer                   │──► uio_od[7:0]
                       │  CRC-16, CRC-5, NRZI line coder       │
                       │  32 x 24 capture FIFO                 │
                       └───────────────────────────────────────┘
```

## 3. Core

### 3.1 State

| State | Width | Reset |
|---|---|---|
| `A`, `X`, `Y` | 8 | 0 |
| `PC` | 7 | 0 |
| Return stack | 8 x 8, circular | 0 |
| `SP` | 3 | 0 |
| `Z`, `C`, `N` | 1 each | 0 |
| `uo_out`, `uio_out` | 8 each | 0 |
| `uio_oe`, `uio_od` | 8 each | 0 |
| Cycle timer | 16 | 0 |
| Capture pointers/count | 4 + 3 + 3 | 0 |

Every flop has an explicit reset. The program and data RAM arrays are the only
state without a hardware reset; the loader writes them before `run` is released.

### 3.2 Single-cycle execution

The instruction memory has an asynchronous read port. At each enabled rising
edge the core decodes the word at `PC`, updates the architectural state, and
loads `PC+1` unless the instruction says otherwise. There is no pipeline and no
branch penalty. The critical path is therefore:

```
PC -> 128:1 instruction mux -> decode -> ALU/next-PC mux -> PC
```

This is the path the area report and the future place-and-route run have to
close at the target clock. The 7-bit PC and a 128-word memory keep the mux
small; the 256-word experiment was rejected in D-009 because it consumed 56% of
the nominal tile area before routing.

### 3.3 Cycle accounting

| Instruction class | Cycles |
|---|---|
| ALU, shifts, loads, stores, I/O, bit ops, branches, calls, returns | 1 |
| `WAIT n` | n (0 means 256) |
| `WAIT_PIN0/1` | at least 1, until the masked level matches |
| `WAIT_EDGE` | at least 1, until a masked input changes |
| `HALT` | 1, then the core holds |

`WAIT n` includes the instruction's own cycle. A sequence of `WAIT`
instructions therefore adds exactly. This property is what makes the UART
firmware possible without a hardware baud generator: `WAIT 255` + `WAIT 160`
is 415 cycles, and the two-instruction pin write in front of it makes a 417-cycle
bit.

### 3.4 Flags

`Z` and `N` are the zero and sign of the last flag-affecting result. `C` is the
carry/borrow or the shifted-out bit. `INC`/`DEC`, `LDI`, `LOAD`, `ST`, `TFR`,
`IO`, `BIT`, and non-`DJNZ` branches preserve `C`. The flags are visible to the
ISS and the co-simulation; there is no conditional branch on `N` in ISA v1.

### 3.5 Pin model

- `ui_in` is always an input.
- `uo_out` is always an output.
- `uio` has per-bit `uio_oe` and per-bit `uio_od`.
- `IN UI` and `IN UIO` read the actual pad.

Open-drain is implemented in the top level:

```
uio_oe_pad = uio_oe & ~(uio_out & uio_od)
```

When `uio_oe=1`, `uio_od=1`, and `uio_out=1`, the pad driver is disabled and an
external pull-up wins. When `uio_out=0`, the pad drives low. This is the exact
behaviour I2C needs, and it is also useful for wired-OR buses and target-role
SPI.

### 3.6 Timer and capture

The 16-bit timer increments once per enabled core clock. `TMR_LO` reads the low
byte and latches the high byte; `TMR_HI` reads the latched byte. This gives an
atomic 16-bit timestamp without a critical-section dance.

The capture engine samples `{uio_in, ui_in}` every enabled clock while
`CAP_EN=1`. When the 16-bit vector changes it pushes
`{timer[7:0], uio_in, ui_in}` into a 32-entry buffer, which is the deepest it can
go and still describe itself in one status byte: full, empty, and a six-bit
count. Thirty-two edges is a whole I2C or SPI transaction, or a UART byte with
its framing.

Two modes share the buffer. In FIFO mode new events are dropped once it is full
and `CAP_STATUS` says so, which is what a directed test wants. In roll mode the
oldest entry is overwritten instead, so the buffer always holds the newest 32
edges: run the protocol, stop, and drain the window that just happened without
having armed the capture in advance or known where the interesting edge would
be. `CAP_STATUS` reports full/empty/count; `CAP_POP` reads the oldest entry and
advances the pointer in the same cycle.

### 3.7 Protocol helpers

Two blocks exist because a protocol is not only timing: line coding and checksums
are what separate "bit-banged" from "the chip does it".

The CRC block holds two reflected registers, a 16-bit one that consumes a whole
byte per instruction (polynomial 0x8005, init 0xFFFF, final XOR 0xFFFF) and a
5-bit one that consumes one bit (polynomial 0x05, init 0x1F), because a USB token
field is 11 bits rather than a byte. Both use the USB conventions, and the 16-bit
one reproduces the published check value 0xB4C8 for `123456789`.

The serialiser holds the byte being sent, a count of bits left, a count of
consecutive ones, the current line level, and whether a stuffed zero is owed.
`SER_NEXT` advances one bit time and returns the next level in `A`; it drives no
pad, so firmware still owns the pins and the pin rules of section 3.3 are
unchanged. A bit is therefore `SER_NEXT` plus an `OUT`, and the `WAIT` that sets
the bit period is the same instruction UART uses.

Both blocks cost 4,171 um2 together, 1.4% of the mapped area, and both are
covered by tests rather than asserted: the CRC test checks the standard check
value and a reference CRC-5, and the line-coder test compares the emitted level
sequence against an independent NRZI + stuffing reference, including the stuffed
zero after six ones.

## 4. Host loader

The loader is a write-mostly SPI mode-0 target on `ui_in[7:5]` and `uo_out[7]`.
It is independent of the CPU and remains alive across core resets.

- 32-bit frame: `{command[7:0], address[7:0], data[15:0]}`, MSB first.
- `0x01` writes a 16-bit program word.
- `0x02` writes an 8-bit data byte.
- `0x03` controls `run` (bit 0).
- `0x04` latches a program word for the next frame's MISO readback.
- `0x00` is a no-op / readback frame.

`SCK`, `CS_N`, and `MOSI` are synchronized with two flops. The host must keep
`SCK <= clk/4` and hold `CS_N` for at least two clocks around a frame. The CPU
is held while `CS_N` is low, and held in reset while `run=0`. The normal
sequence is: write control 0, load words/bytes, write control 1.

The configuration pins are still readable as GPIO in run mode. The host must
leave them static while the CPU is running if the firmware uses them.

## 5. Program memory choice

| Configuration | Mapped cell area | Fraction of nominal 6x4 | Decision |
|---|---:|---:|---|
| 256 x 16 program, 64 x 8 data | 420,028 µm² | 56% | rejected (D-009) |
| 128 x 16 program, 64 x 8 data | 257,363 µm² | 34% | **selected** |

The 128-word build leaves room for clock-tree buffers, routing, and the
inevitable timing repair. The trade-off is code size; each protocol demo is
loaded separately, and macros/the assembler keep the sources compact. A future
revision can use the IHP SRAM macro for a larger program memory, but only after
the LibreLane macro placement/power/LVS flow is verified (see D-006).

## 6. Why this is not just another 8-bit CPU

- The ISA has **pin-level operations** (`SETB`/`CLRB`/`TGLB`, immediate pin
  writes, `WAIT_PIN`, `WAIT_EDGE`) rather than a memory-mapped GPIO block that
  costs a load/store pair per edge.
- **Exact cycle costs** are an architectural promise, not a compiler hope.
- **Open-drain is part of the pin model**, so target-role I2C is firmware, not a
  board hack.
- The **capture FIFO** makes the same chip a protocol analyzer; the emulator can
  observe the bus it is about to emulate.
- The **loader is simple enough to bit-bang** from any host microcontroller,
  including the RP2350 on the Tiny Tapeout demo board.

Compared with an RP2040 PIO state machine, Proteus-1 has a conventional
processor programming model and a real assembler/ISS, at the cost of less
parallelism. Compared with a fixed peripheral set, it can become a protocol
that did not exist at tapeout. The next step is a dual-core or multi-context
version if the 8x4 template becomes the target.

## 7. Timing and clocking

Target: **32 MHz** (31.25 ns). The first hardened run at 48 MHz passed DRC,
LVS, and antenna checks but missed the slow-corner setup constraint by 4.17 ns
over 346 paths; the critical path needs 25.0 ns. At 32 MHz the same path has
6.25 ns of margin. The UART examples keep 417 cycles/bit, which is 76.8 kbaud
with 0.08% error. `i2c_master.s` uses `WAIT 156` for roughly 100 kHz, and
`i2c_master_400k.s` uses `WAIT 38` for roughly 386 kHz. `ps2_device.s` uses
`WAIT 167` to stay near 10.5 kHz. SPI master uses a slower, branchy bit loop for
easy probing; the target role samples on `SCK` and can be sped up by shortening
the waits.

The local Yosys/ABC area run does not include place-and-route parasitics. The
Tiny Tapeout GDS action is the authority for the final timing and precheck, and
the 32 MHz build passed it: slow-corner setup slack is +6.10 ns with 0 violating
paths, and the hardened netlist uses 383,307 µm² of placed cells. `src/config.json`
and `info.yaml` declare 31.25 ns / 32 MHz; do not raise the clock without a new
hardened timing run and a fresh protocol-rate check.

## 8. Risks and limitations

- 128 instruction words is a real constraint. Multi-protocol firmware has to be
  split into separate images or written with macros.
- The loader is write-only except for program readback; there is no data-memory
  readback command. Firmware can report data on pins.
- The capture FIFO is 32 entries with 8-bit timestamps; it is for bursts, not
  long traces.
- No interrupts. A blocking `WAIT_PIN` stalls the CPU; concurrent protocols
  require interleaving by hand.
- No SRAM macro. The flop-based program memory is the largest block and the
  main reason to consider an 8x4 or SRAM revision.
- The I2C examples require external pull-ups and a shared ground, as any I2C bus
  does.

## 9. Future work

1. SRAM-backed 512-word program memory after a verified LibreLane macro flow.
2. Dual core or four contexts for concurrent protocols.
3. Hardware Manchester encoder/decoder and CRC for low-speed USB / 10BASE-T.
4. A host GUI that loads images and plots capture FIFO traces.
5. An ISA-equivalence proof, or a full formal model of the loader FSM. The six
   proven invariants cover PC freeze, the timer, the capture bound, loader
   framing, idle outputs, and the CALL/RET return stack.
