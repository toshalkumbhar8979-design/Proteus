# Submission Checklist

Mapped against the competition rules and the "What do I submit?" FAQ. Update
the status column only with evidence; do not tick an item because it is planned.

| Requirement | Where it lives | Status |
|---|---|---|
| Public open-source repository | this repository, Apache-2.0 | **done (public GitHub repository)** |
| RTL for a reprogrammable protocol emulator | `src/` | **done** |
| 6×4 tile allocation | `info.yaml` (`tiles: "6x4"`) | **done** |
| IHP CMOS5L target | `info.yaml`, `src/config.json`, `.github/workflows/gds.yaml` | **done** |
| Architecture documentation | `docs/architecture.md` | **done** |
| Instruction-set documentation | `docs/isa.md` | **done** |
| Assembler or toolchain | `tools/proteus_asm.py`, `tools/proteus_isa.py` | **done** |
| Example programs | `programs/*.s` (12 images) | **done** |
| Verification write-up | `docs/verification.md` | **done** |
| UART demonstrated | `programs/uart_tx.s`, `uart_rx.s`; tests | **done (RTL)** |
| SPI demonstrated | `programs/spi_master.s`, `spi_master_cpol1.s`, `spi_target.s`; tests | **done (RTL, master modes 0–3, target mode 0)** |
| I2C demonstrated | `programs/i2c_master.s`, `i2c_master_400k.s`, `i2c_target.s`; tests | **done (RTL, master and target 100/400 kHz)** |
| Both controller and target roles | UART, SPI, I2C firmware and tests | **done** |
| Other protocol beyond the headline three | PS/2 device transmitter and a JTAG master, each with a test | **done** |
| Host loader documented | `docs/info.md`, `host/proteus_host.py` | **done** |
| GDS build | `.github/workflows/gds.yaml` | **passes** (run 40903018243, commit `abbebf2`); 0 DRC, 0 LVS, antenna clean |
| Tiny Tapeout precheck | `precheck` job in `gds.yaml` | **passes** |
| Post-route timing | GDS action report | **32 MHz passes**: slow-corner setup +6.10 ns, 0 violating paths, hold positive |
| Gate-level smoke test | `test/Makefile GATES=yes`, `gl_test` job | **18/18 pass** on synthesis and post-PnR netlists; 3 white-box tests skipped by design |
| Formal verification | `scripts/formal.sh`, `formal` CI job | **6 invariants proved** (BMC + induction), including the return stack |
| FPGA check without hardware | `scripts/synth_fpga.sh` | **ECP5 map + PnR**: 1,611 LUT4, 544 FF, 65.9 MHz vs 32 MHz target |
| AI-use disclosure | `docs/competition.md` | **done** |
| Stretch protocols (USB, 10BASE-T) | not attempted | **honest gap** |
| FPGA board run | no hardware available | **honest gap** (mapping, PnR, and timing verified instead) |
| Optional demo video | not recorded | **optional** |
| Competition submission form | Jane Street, closer to 2027-01-18 | **external** |

## Remaining before submission

1. Keep `test`, `gds`, `precheck`, and `gl_test` green on every push. A change
   that touches timing constants must update the firmware, its test, and the
   documentation together.
2. If `gds` fails on timing or density, fix the RTL/config and rerun; never
   lower the declared clock alone.
3. Pages is enabled with the `workflow` build type, so the layout `viewer` job
   deploys to `https://toshalkumbhar8979-design.github.io/Proteus/`. If that job
   ever reports HTTP 404 from the Pages API, check Settings → Pages first; it is
   configuration, not a design failure.
4. Record the final passing run URL in the README and the competition write-up.
5. Submit the repository link through the official form.

## Bottom line

Ready to hand over, not yet handed in. The chip, toolchain, tests, timing
signoff, and documentation are complete and green; what is missing is the
submission form itself, which Jane Street has not opened yet.

If there is one more push before January, the highest-value additions, in order:

1. A short capture/replay demo video — the cheapest way to make the chip
   legible to a human judge.

The two engineering items on that list are done:

- **JTAG master.** `programs/jtag_idcode.s` resets a TAP, walks it to Shift-DR
  with the existing pin instructions, clocks out 32 bits, and checks a default
  IDCODE. `test_jtag_idcode` models the TAP, asserts the state path, the
  31 shift clocks, and the `0xC3` success marker.
- **Return-stack property.** `scripts/formal.sh` now proves the sixth
  invariant: after a CALL, the slot below the new `sp` holds `PC+1`; after a
  RET, the PC equals the slot the pointer popped, through the same truncation
  the instruction performs.
3. A return-stack formal property — closes the one piece of architectural state
   that currently relies on simulation alone.

## Claims to keep honest

- The local 257,363 µm² number is a synthesis estimate; the hardened numbers
  are 383,307 µm² of placed cells in a 902,417 µm² core.
- The SPI target is mode 0 only.
- The 48 MHz build failed slow-corner setup. The declared clock is 32 MHz, and
  that build passed post-route timing with +6.10 ns of slow-corner slack.
- No silicon exists. Timing, power, DRC, and LVS are signoff-tool results on the
  hardened netlist, and every protocol result is simulation.
- Formal coverage is six invariants, not ISA equivalence or liveness.
- JTAG is a master-side bit-banger checked against a modelled TAP: no IR scan,
  no boundary scan, no multi-device chain, and no target role.
- The FPGA result is synthesis, place-and-route, and an Fmax estimate without a
  board; it is not a hardware run.
