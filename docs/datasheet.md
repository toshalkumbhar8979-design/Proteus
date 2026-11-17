# Proteus-1 — datasheet

| | |
|---|---|
| Part | **Proteus-1** (`tt_um_proteus`), field-reprogrammable protocol engine |
| Process | IHP SG13CMOS5L, 130 nm BiCMOS, 5 metal layers, via Tiny Tapeout |
| Allocation | 8 × 4 tiles; die 1,724.16 × 710.64 µm (1,225,260 µm²) |
| Clock | **32 MHz** (31.25 ns), single clock domain, fully static |
| Core logic | 469,393 µm² placed (38.9% of a 1,208,170 µm² core), 28,191 standard cells |
| Power | **8.71 mW** typical at 32 MHz, 25 °C |
| Pins | 24 digital I/O: 8 in, 8 out, 8 bidirectional with per-bit enable and open-drain |
| Program store | 128 × 16 bit, host-loaded, volatile |
| Status | **Silicon not fabricated.** All figures are from the signed-off netlist (run 43957356626) |
| License | Apache-2.0 |

---

## 1. Description

Proteus-1 is a single-chip protocol emulator. It is not a collection of
peripherals: it is an 8-bit, single-cycle CPU whose instruction set is built
around pins, edges and exact cycle counts, so a protocol is a firmware image
rather than a fixed block. After fabrication the chip can become a UART, an SPI
controller, an I2C target, a PS/2 device, a JTAG master or a 32-entry logic
analyser, and can be reprogrammed again for the next role.

Every ordinary instruction retires in one clock. There is no pipeline, no branch
penalty and no hidden wait state, so firmware timing is arithmetic rather than
measurement: `WAIT 417` is 417 clocks, every time. That determinism is the whole
product — it is what lets bit-banging reach 76.8 kbaud with 0.08% error and what
makes a captured waveform reproducible in simulation.

The design occupies 38.9% of its granted 8 × 4 allocation. The remaining area is
fill, decap, tap cells and routing, which is the normal headroom a routed die
carries rather than unused capability.

## 2. Features

- **8-bit accumulator CPU** — `A`, `X`, `Y`; 7-bit `PC`; 8-deep circular return
  stack; `Z`/`C`/`N` flags. 15 opcode classes, one clock each.
- **128 × 16 program memory** and **64 × 8 data memory**, written by the host.
- **24 digital pins** — 8 dedicated inputs, 8 dedicated outputs, 8 bidirectional
  pins with per-bit output enable and per-bit open-drain mode, so I2C, wired-OR
  buses and shared pinouts need no external glue.
- **Exact delays** — `WAIT n` (1…255, `0` = 256), `WAIT_PIN0/1` on a mask,
  `WAIT_EDGE` on any masked change.
- **16-bit cycle counter** with an atomic low/high read pair.
- **32-entry capture buffer** recording `{cycle[7:0], uio_in, ui_in}` on every pin
  change, in drop-on-full FIFO mode or roll mode (newest 32 edges).
- **CRC helpers** — CRC-16/USB (byte per instruction, check value `0xB4C8` for
  `"123456789"`) and CRC-5/USB (bit per instruction).
- **NRZI line coder with bit stuffing** (`SER`) and its matching **receiver with
  stuffing removal and a sticky error latch** (`RX`), for low-speed USB framing.
- **Host loader** on `ui_in[7:5]` with readback on `uo_out[7]`, which stays a
  normal output once configuration ends.

## 3. Pin configuration

All pins are digital. `clk`, `rst_n` and `ena` come from the carrier and are not
listed below. Reset values are the state after `rst_n` is released and before
the host loads a program.

| Pin | Reset state | Run-mode function | Notes |
|---|---|---|---|
| `ui_in[0]` | input | GPIO / `IN0` | firmware-defined |
| `ui_in[1]` | input | GPIO / `IN1` | used by the capture demo |
| `ui_in[2]` | input | GPIO / `IN2` | |
| `ui_in[3]` | input | GPIO / **UART RX** | `uart_rx.s`, 8N1 |
| `ui_in[4]` | input | GPIO / **JTAG TDO** | `jtag_idcode.s` samples here |
| `ui_in[5]` | input | **`CFG_MOSI`** while `CS_N` low | GPIO after configuration |
| `ui_in[6]` | input | **`CFG_SCK`** while `CS_N` low | GPIO after configuration |
| `ui_in[7]` | input | **`CFG_CS_N`**, active low | holding it low holds the CPU |
| `uo_out[0..6]` | 0 | GPIO outputs | any protocol, any pin |
| `uo_out[7]` | 0 | **`CFG_MISO`** while `CS_N` low | **UART TX** (`uart_tx.s`) otherwise |
| `uio[0]` | Z | GPIO, OE and open-drain per bit | SPI `CS_N`, PS/2 DATA, JTAG TCK |
| `uio[1]` | Z | GPIO | SPI MOSI, PS/2 CLK, JTAG TMS |
| `uio[2]` | Z | GPIO | SPI MISO, I2C SCL, JTAG TDI |
| `uio[3]` | Z | GPIO | SPI SCK, I2C SDA |
| `uio[4..7]` | Z | GPIO | free |

`uio` pins power up with output enable off, so a carrier can drive them safely
before a program is loaded. `IN` always reads the actual pad, not the output
register, which is what makes open-drain buses readable.

**Open-drain rule.** With `uio_oe[i] = 1` and `uio_od[i] = 1`, the pad drives 0
when `uio_out[i] = 0` and releases when `uio_out[i] = 1`. No direction swapping
is needed per bit.

## 4. Electrical characteristics

These are post-route numbers from the hardened netlist, not measurements. No
silicon exists yet; the shuttle's carrier supplies the rails and the design adds
no supply, analog or clock requirement of its own. Consult the Tiny Tapeout
carrier pinout for rail voltages.

### 4.1 Power

| Parameter | Condition | Value |
|---|---|---|
| Total power, typical | `typ_1p20V_25C`, 32 MHz | **8.71 mW** |
| — internal | | 7.27 mW |
| — switching | | 1.38 mW |
| — leakage | | 0.05 mW |

Power scales with clock frequency and with how hard the firmware drives pins;
8.71 mW is the placer/STA estimate at the declared clock, not a worst case.

### 4.2 Area

| Parameter | Value |
|---|---|
| Die | 1,724.16 × 710.64 µm (1,225,260 µm²) |
| Core | 1,208,170 µm² |
| Placed standard cells | 469,393 µm² (38.9%) |
| Standard-cell instances | 28,191 (3,734 sequential) |
| DRC / LVS / antenna | 0 / 0 / 0 |

## 5. AC timing

| Parameter | Symbol | Value |
|---|---|---|
| Clock frequency | `f_clk` | **32 MHz** max |
| Clock period | `t_clk` | 31.25 ns |
| Setup slack, slow `1p08V/125C` | | **+8.895 ns**, 0 violators |
| Setup slack, typical / fast | | +14.595 / +18.071 ns |
| Hold slack, slow / typ / fast | | +0.654 / +0.313 / +0.108 ns |
| Loader SCK | `f_SCK` | ≤ `f_clk` / 4 = 8 MHz |
| Reset | `t_rst` | ≥ 1 clock, active low |

There is no minimum clock frequency: a single clock domain with fully static
timing means the part runs down to DC. On an ECP5-25F FPGA the same RTL closes at
65.9 MHz, which is a portability check rather than a silicon claim.

## 6. Memory and register map

| Resource | Size | Address / access |
|---|---|---|
| Program memory | 128 × 16 bit | word address `0x00`–`0x7F`; loaded by host, PC is 7 bits |
| Data memory | 64 × 8 bit | byte address `0x00`–`0x3F`; `(X)`, `(imm[5:0])` |
| Return stack | 8 × 8 bit | managed by `CALL` / `RET`; circular, overflow wraps |
| Capture buffer | 32 × 32 bit | `{cycle[15:0], uio_in, ui_in}`; `CAP_POP` then `CAP_UI/UIO/TS/TSH` |
| Cycle counter | 16 bit | `TMR_LO` latches high byte, `TMR_HI` reads it |
| CRC-16 / CRC-5 | 16 / 5 bit | `CRC16_*`, `CRC5_*`; reset to `0xFFFF` / `0x1F` |
| Identity | 8 bit | `ID` returns `0xA1` |

Program memory is flip-flop based and undefined at power-up, so the chip does
nothing useful until the host has loaded an image and set `run = 1`. That is the
one boot requirement, and it is what makes the part reprogrammable without a
mask change.

## 7. Instruction set summary

Sixteen bits per instruction: `opcode[15:11]`, `subop[10:8]`, `imm[7:0]`.
`docs/isa.md` is normative; this table is the index.

| Opcode | Class | Covers |
|---:|---|---|
| 0 | `ALU` | `ADD`, `ADC`, `SUB`, `SBC`, `AND`, `OR`, `XOR`, `CMP` with an immediate |
| 1 | `SHIFT` | `SHL`, `SHR`, `ROL`, `ROR`, `ASR`, `SWAP`, `INC`, `DEC` on `A` |
| 2 | `LOAD` | immediates to `A`/`X`/`Y`, `LD`/`ST` through `X` or direct, `TFR` moves |
| 3 | `IO` | `OUT` to `uo`/`uio`/OE/open-drain, `IN` from `ui`/`uio`, immediate forms |
| 4 | `BRANCH` | `JMP`, `JZ`, `JNZ`, `JC`, `JNC`, `CALL`, `RET`, `DJNZ Y` |
| 5 | `TIME` | `WAIT`, `WAIT_PIN0/1` on `ui` or `uio`, `WAIT_EDGE`, `HALT` |
| 6 | `BIT` | `SETB`/`CLRB`/`TGLB` on `uo`, `uio`, `uio_oe` — one clock per pin change |
| 7 | `MISC` | `NOP`, `INC`/`DEC` of `X`/`Y`, register aliases |
| 8 | `ALUX` | the ALU table with `X` as the operand |
| 9 | `ALUY` | the ALU table with `Y` as the operand |
| 10 | `TIMER` | `TMR_LO`, `TMR_HI`, `TMR_CLR`, `ID` |
| 11 | `CAP` | `CAP_EN` (FIFO/roll), `CAP_POP`, `CAP_UI`, `CAP_UIO`, `CAP_TS`, `CAP_TSH`, `CAP_STATUS`, `CAP_CLR` |
| 12 | `CRC` | `CRC16_RST`, `CRC16_ADD`, `CRC16_LO/HI`, `CRC5_RST`, `CRC5_BIT`, `CRC5` |
| 13 | `SER` | `SER_LD`, `SER_NEXT`, `SER_LEVEL`, `SER_BUSY`, `SER_ONES`, `SER_SET`, `SER_JK` |
| 14 | `RX` | `RX_RST`, `RX_BIT`, `RX_ONES`, `RX_ERR` |
| 15–31 | reserved | execute as `NOP`; the assembler rejects them |

Cycle cost: 1 clock for everything except `WAIT n` (exactly `n`, `0` = 256),
`WAIT_PIN*`/`WAIT_EDGE` (≥ 1, until the condition holds) and `HALT` (1, then
stops until reset).

## 8. Host loader interface

An SPI mode-0 target on `ui_in[7:5]`, with `uo_out[7]` as MISO while `CS_N` is
low. Frames are 32 bits, MSB first:

```
{ command[7:0], address[7:0], data[15:0] }
```

| Command | Meaning |
|---|---|
| `0x00` | no operation (also the read-response frame) |
| `0x01` | write program word: `prog[address[6:0]] ← data` |
| `0x02` | write data byte: `data[address[5:0]] ← data[7:0]` |
| `0x03` | control: `run ← data[0]`; `run = 0` resets and holds the core |
| `0x04` | latch the program word at `address` for the next frame's MISO |

Readback is pipelined: `0x04` latches a word, and the **next** frame shifts it
out during its first 16 rising edges. Release the CPU with `0x03`/`data = 1`.
The reference host in `host/` runs at 100 kHz, far below the 8 MHz limit.

## 9. Protocol capability matrix

Rates are for the 32 MHz clock and are set by firmware, not by fixed dividers.

| Role | Image | Rate | Limits |
|---|---|---|---|
| UART transmit | `uart_tx.s` | 76.8 kbaud 8N1 (417 clocks/bit, 0.08% error) | TX on `uo_out[7]` |
| UART receive | `uart_rx.s` | 76.8 kbaud 8N1 | samples `ui_in[3]` mid-bit |
| SPI controller | `spi_master.s`, `spi_master_cpol1.s` | firmware-paced; CPOL=0 and CPOL=1 images cover modes 0–3 | full duplex on `uio[0..3]` |
| SPI target | `spi_target.s` | | **mode 0 only** |
| I2C controller | `i2c_master.s`, `i2c_master_400k.s` | ~100 kHz / ~386 kHz | needs external pull-ups |
| I2C target | `i2c_target.s` | address `0x28`, both rates | 7-bit addressing |
| PS/2 device | `ps2_device.s` | ~10.5 kHz, 11-bit frame | **transmit only** |
| JTAG master | `jtag_idcode.s` | firmware-paced | reads IDCODE; **no IR scan** |
| USB low-speed framing | `usb_data_tx.s` | 21/22-clock dither, 1.506 Mbit/s | differential J/K on D-/D+, SE0 end-of-packet; rate inside ±1.5% |
| Logic analyser | `capture_demo.s` | every clock | 32 entries, FIFO or roll |

## 10. Errata and limitations

1. **No silicon.** Every number here is from static timing, power and DRC/LVS on
   the hardened netlist. Nothing on this part has been measured on a die.
2. **The submitter's cached GDS has three flow warnings** at the slow corner —
   41 max-slew and 2 max-cap reports, 293 max-fanout reports across corners, and
   one non-critical disconnected pin. None is a setup or hold violation and the
   flow error count is 0; they are listed in `docs/verification.md` rather than
   suppressed.
3. **SPI target is mode 0 only.** The controller covers modes 0–3 via two images.
4. **PS/2 is transmit-only.** A keyboard/host receiver is not implemented.
5. **JTAG is a master that reads IDCODE without an IR scan**, valid because
   IEEE 1149.1 puts IDCODE in the instruction register out of reset.
6. **USB is a framing demonstration, not a PHY.** The bit rate is dithered inside
   ±1.5% and SE0 is driven, but there is no transceiver, no 1.5 k pull-up on the
   board, and the eight bit slots in `usb_data_tx.s` assume this packet needs no
   stuffed bit. A packet that does need one still transmits correctly through the
   `SER` helper; it just shifts the slots, so that case wants a timer-paced loop.
7. **Program memory is volatile and undefined at power-up**; the host must load
   an image before `run = 1`.
8. **Opcodes 15–31 are reserved** and execute as `NOP`. Firmware must not use
   them; the assembler refuses to emit them.
9. **Formal verification is bounded** (40-cycle BMC plus temporal induction over
   six properties), not full ISA equivalence.

## 11. Documents and support

| Document | Contents |
|---|---|
| [`docs/isa.md`](isa.md) | normative instruction set, encodings, flags, cycle counts |
| [`docs/architecture.md`](architecture.md) | blocks, area trade-offs, retime history |
| [`docs/verification.md`](verification.md) | what each test proves, signoff numbers, gaps |
| [`docs/info.md`](info.md) | bring-up walkthrough and per-protocol hookup |
| [`docs/competition.md`](competition.md) | design rationale and novelty |
| [`docs/submission-checklist.md`](submission-checklist.md) | requirement-by-requirement evidence |

Ordering: this part is not for sale. It is fabricated through the Tiny Tapeout
shuttle from this repository, and the RTL, tools, tests and documentation are
Apache-2.0.

## 12. Revision history

| Revision | Date | Basis |
|---|---|---|
| 1.0 | 2026-11-17 | First datasheet; numbers from run 43957356626, commit `18f08e0`, 8 × 4 hardening |
