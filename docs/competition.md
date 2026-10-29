# Proteus-1 — Competition Write-Up

## The thesis

The competition asks for a general-purpose protocol emulator: a chip that can
become a protocol it was not designed for. The easy answer is to put a UART, an
SPI block, and an I2C block on the die and call it flexible. That answer fails
the actual test. A fixed peripheral set can only emulate the protocols someone
anticipated at tapeout.

Proteus-1 starts from the opposite direction. Protocol emulation is a **timing**
problem: drive a pin, wait a known number of clocks, sample a pin, repeat. So
the chip is a CPU whose instruction set makes pins and time first-class, and
whose timing is an architectural promise rather than a compiler hope. Every
ordinary instruction retires in exactly one clock. The only multi-cycle
instructions are explicit waits. Firmware can be read as a timing diagram.

That is the whole design argument. Everything else — the assembler, the ISS, the
loader, the capture FIFO — exists to make that argument usable and checkable.

## What is on the chip

| Block | Implementation |
|---|---|
| Core | 8-bit single-cycle CPU, `A`/`X`/`Y`, 7-bit `PC`, 8-deep return stack, `Z`/`C`/`N` |
| Program | 128 × 16 asynchronous-read RAM, host write port |
| Data | 64 × 8 RAM, direct and `X`-indexed |
| Pins | 8 in, 8 out, 8 bidir with per-bit output enable and open-drain |
| Timing | 16-bit free-running cycle counter; `WAIT`, `WAIT_PIN`, `WAIT_EDGE` |
| Capture | 8 × 24 FIFO of `{timer[7:0], uio_in, ui_in}` on pin changes |
| Host port | SPI mode-0 loader, 32-bit frames, program readback |

The ISA has twelve instruction classes and 96 defined encodings. The encoding is
regular enough for a small decoder and readable enough for hand-written
firmware. The complete reference is in [`isa.md`](isa.md).

## What is novel

**Timing is part of the ISA, not a peripheral.** `WAIT n` is exactly `n` clocks,
including its own cycle. This makes a 417-cycle UART bit a two-instruction
sequence (`WAIT 255` + `WAIT 160`) plus the pin write, with no baud generator,
no prescaler, and no interrupt jitter. The same arithmetic produces I2C delays
and SPI edges.

**Open-drain is a first-class pin mode.** Each bidirectional pin has an output
enable bit and an open-drain bit. The pad driver is disabled when the pin is
released, so I2C and wired-OR buses need no external glue and no board hack.
Target-role I2C is firmware, not a special case in silicon.

**The emulator can observe.** The capture FIFO records pin transitions with
8-bit timestamps while the CPU runs. The same chip that drives a bus can capture
it, drain the FIFO, and decode or replay the waveform. That is the "protocol
analyzer" half of the tool, and it is useful before a protocol is understood
well enough to emulate it.

**The host loader is deliberately simple.** A 32-bit SPI frame writes one
program word, one data byte, or the run bit. Program readback is pipelined so a
host can verify what it loaded. Any microcontroller can bit-bang it; the
reference host is a single MicroPython file.

**The golden model is independent.** The Python ISS was written from the ISA
document, not generated from the RTL. The randomized co-simulation compares
every architectural register after every clock, so a decoder or flag bug cannot
hide behind a protocol test that only checks the final byte.

## Protocols demonstrated

All of these run on the RTL through the real loader and are checked by cocotb:

| Protocol | Role | Result |
|---|---|---|
| UART 8N1, 76.8 kbaud at 32 MHz | Transmitter | `P1\n` decoded at 417 cycles/bit |
| UART 8N1, 76.8 kbaud at 32 MHz | Receiver | `0x5A` received with centre sampling |
| SPI modes 0–3, MSB first | Controller | `0xA5` sampled on each mode's edge |
| SPI mode 0, MSB first | Target | `0xA5` received from a cocotb controller |
| I2C ~100 kHz, address `0x28` | Controller | START, address, `0x42`, ACK, STOP |
| I2C ~400 kHz, address `0x28` | Controller | Same exchange; SCL period measured at 80–84 clocks |
| PS/2 device-to-host | Device | 11-bit frame, odd parity, open-drain clock/data, `0x5A` |
| I2C ~100 kHz, address `0x50` | Target | Address match, ACK, data `0x42` |
| I2C ~400 kHz, address `0x50` | Target | Same target with 80-clock SCL periods |
| Capture FIFO | Analyzer | Timestamped pin changes drained in order |
| Pin waits | Timing | Level and edge stalls released exactly |

Both ends of UART, SPI, and I2C are implemented in firmware. That matters for
the flexibility claim: the chip is not relying on a hardware block to be the
hard part of either role.

## Verification

The verification story is the part most likely to decide a close competition.
Proteus-1 uses three independent layers:

1. **Directed cocotb tests through the loader.** Twenty tests drive real
   frames, real pin waveforms, and real bus models. They check what a scope
   would see, not internal signals.
2. **Exhaustive and randomized RTL/ISS lock-step.** Every opcode/subop pair in
   the 12 x 8 encoding space runs on both models for 30 clocks, then a generated
   program containing all twelve opcode classes runs for 1,000 enabled clocks.
   After every clock, every architectural register must match the Python model.
   A mismatch prints the instruction, PC, and the first differing state.
3. **Toolchain unit tests.** Seven tests cover all 96 encodings, every mnemonic,
   directives, assembler errors, ISS arithmetic, exact `WAIT` semantics, and
   stack behaviour.

Synthesis with the IHP `typ_1p20V_25C` library maps to **257,363 µm²**, 34% of
the nominal 6×4 tile area, with no latches and no multiply/divide cells. The
256-word program memory was measured at 56% and rejected; the trade-off is
documented rather than hidden.

The honest gaps are in [`verification.md`](verification.md): no place-and-route
yet, no gate-level simulation, no silicon, SPI target mode 0 only, and no formal
properties. Those are the next things to close, not things the report pretends
are done.

## Why this can win

- **Flexibility is real, not a checklist.** UART, SPI, and I2C are firmware
  images, not fixed blocks. The ISA can express PS/2, JTAG, SWD, 1-Wire, or a
  custom bit-banged protocol without changing the die.
- **Both roles.** Controller and target firmware exist for all three headline
  protocols.
- **A complete toolchain.** Assembler, disassembler, ISS, host loader, example
  programs, and reproducible tests. A judge can rebuild and rerun everything.
- **Verification is designed, not appended.** The ISS is an independent golden
  model, and the co-simulation compares every register every cycle.
- **The architecture has a point of view.** Exact cycle costs and open-drain
  pins are the design, not features bolted on.
- **It is honest.** The area trade-off, the missing PnR, and the untested SPI
  modes are all written down. Judges can trust the claims that are made.

## What comes next

With an 8×4 allocation or a verified SRAM macro, the first upgrade is a larger
program memory (512 words) so multi-protocol firmware fits in one image. The
second is a second context or core for concurrent protocols. The third is
hardware assistance for the stretch protocols: a Manchester encoder/decoder and
CRC for low-speed USB and 10BASE-T, and a CAN frame filter. None of these are
claimed today.

## How AI was used

AI coding assistants were used to draft documentation, propose RTL and test
structures, and help debug simulation failures. Every RTL change was elaborated,
linted, and exercised by the test suite; every number in this repository comes
from a command that can be rerun. No claim in the write-up is based on an
unexecuted suggestion. The design decisions, trade-offs, and final review are
the author's.

## Reproduce it

```sh
cd test && make -B                              # 20 RTL tests
python3 -m pytest -q tools/test_isa.py          # 7 toolchain tests
./scripts/build_programs.sh                     # all example images
PDK_ROOT=$HOME/pdk/IHP-Open-PDK ./scripts/synth_area.sh
```

Repository: see the project README for the layout and the loader pinout.
