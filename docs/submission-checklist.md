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
| Example programs | `programs/*.s` (11 images) | **done** |
| Verification write-up | `docs/verification.md` | **done** |
| UART demonstrated | `programs/uart_tx.s`, `uart_rx.s`; tests | **done (RTL)** |
| SPI demonstrated | `programs/spi_master.s`, `spi_master_cpol1.s`, `spi_target.s`; tests | **done (RTL, master modes 0–3, target mode 0)** |
| I2C demonstrated | `programs/i2c_master.s`, `i2c_master_400k.s`, `i2c_target.s`; tests | **done (RTL, master and target 100/400 kHz)** |
| Both controller and target roles | UART, SPI, I2C firmware and tests | **done** |
| Other protocol beyond the headline three | PS/2 device transmitter, test | **done** |
| Host loader documented | `docs/info.md`, `host/proteus_host.py` | **done** |
| GDS build | `.github/workflows/gds.yaml` | **first run: DRC/LVS/antenna pass; setup failed at 48 MHz; 32 MHz rerun pending** |
| Tiny Tapeout precheck | `precheck` job in `gds.yaml` | **blocked on a green GDS run** |
| Post-route timing | GDS action report | **48 MHz WNS -4.17 ns; 32 MHz retime pending** |
| Gate-level smoke test | `test/Makefile GATES=yes` | **not run yet; 3 white-box tests skipped by design, 17 pin-level tests ready** |
| AI-use disclosure | `docs/competition.md` | **done** |
| Stretch protocols (USB, 10BASE-T) | not attempted | **honest gap** |
| Optional demo video | not recorded | **optional** |
| Competition submission form | Jane Street, closer to 2027-01-18 | **external** |

## After the first push

1. Open the **Actions** tab and let `test`, `gds`, `precheck`, and `gl_test` run.
2. If `gds` fails on timing or density, fix the RTL/config and rerun. Do not
   change the declared clock without updating every protocol timing constant,
   its test, and the documentation together.
3. If `precheck` fails, read the report before changing `info.yaml`.
4. Copy the passing GDS/precheck run URL into the README and the competition
   write-up.
5. Only then submit the repository link through the official form.

## Claims to keep honest

- The local 257,363 µm² number is synthesis, not place-and-route.
- The SPI target is mode 0 only.
- The 48 MHz build failed slow-corner setup. The declared clock is now 32 MHz;
  a post-route pass at 32 MHz is not claimed until the GDS rerun completes.
- No silicon, no FPGA run, and no formal verification are claimed.
