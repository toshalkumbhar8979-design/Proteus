# Proteus-1 Instruction Set Architecture (v1.0)

Status: **normative for RTL, assembler, and ISS.** If this document and the RTL
disagree, that is a bug; fix one of them in the same commit.

## 1. Programming model

| Resource | Size | Notes |
|---|---|---|
| `A` accumulator | 8 bits | Main data register |
| `X` index | 8 bits | Data memory index, loop counter, second operand |
| `Y` index | 8 bits | Loop counter (`DJNZ`), second operand |
| `PC` | 7 bits | 128 instruction words |
| Return stack | 8 × 8 bits | Circular; `CALL` pushes `PC+1`, `RET` pops |
| Flags | `Z`, `C`, `N` | Zero, carry/borrow, negative (bit 7) |
| Program memory | 128 × 16 bits | Loaded by host; 7-bit address |
| Data memory | 64 × 8 bits | Byte-addressed; `X[5:0]` or direct `imm[5:0]` |
| Cycle counter | 16 bits | Free-running when the core is enabled |
| Capture FIFO | 8 × 24 bits | `{cycle[7:0], uio_in[7:0], ui_in[7:0]}` |

All ordinary instructions retire in **one enabled clock**. The only instructions
that hold `PC` are `WAIT`, `WAIT_PIN0/1`, `WAIT_EDGE`, and `HALT`.

The CPU is held in reset while the host loader's `run` bit is 0. Releasing
`run` starts execution at `PC = 0`. The program counter is 7 bits wide, so a
sequential fetch from address 127 wraps to 0. Branch and call targets use
`imm[6:0]`; the assembler rejects programs that need more than 128 words.

## 2. Instruction encoding

Every instruction is 16 bits:

```
 15   14   13   12   11 | 10   9   8 | 7 ............ 0
+----+----+----+----+---+----+----+--+------------------+
|      opcode (5)       | subop (3) |     immediate     |
+-----------------------+-----------+-------------------+
```

- `opcode = instr[15:11]`
- `subop  = instr[10:8]`
- `imm    = instr[7:0]`

The assembler accepts labels, numeric literals (`0x..`, `0b..`, decimal), and
the directives in §8.

## 3. Opcode map

### 3.1 `ALU` — immediate arithmetic/logic (`opcode = 0`)

`A ← A op imm`; updates `Z`, `C`, `N`.

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `ADD A, imm` | `A + imm`; `C` = carry |
| 1 | `ADC A, imm` | `A + imm + C`; `C` = carry |
| 2 | `SUB A, imm` | `A - imm`; `C` = borrow |
| 3 | `SBC A, imm` | `A - imm - C`; `C` = borrow |
| 4 | `AND A, imm` | bitwise AND; `C = 0` |
| 5 | `OR  A, imm` | bitwise OR; `C = 0` |
| 6 | `XOR A, imm` | bitwise XOR; `C = 0` |
| 7 | `CMP A, imm` | flags from `A - imm`; `A` unchanged |

### 3.2 `SHIFT` — shifts, rotates, increment/decrement (`opcode = 1`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `SHL A` | `A ← {A[6:0], 1'b0}`; `C ← A[7]` |
| 1 | `SHR A` | `A ← {1'b0, A[7:1]}`; `C ← A[0]` |
| 2 | `ROL A` | `A ← {A[6:0], C}`; `C ← A[7]` |
| 3 | `ROR A` | `A ← {C, A[7:1]}`; `C ← A[0]` |
| 4 | `ASR A` | arithmetic right shift; `C ← A[0]` |
| 5 | `SWAP A` | `A ← {A[3:0], A[7:4]}`; `C` unchanged |
| 6 | `INC A` | `A ← A + 1`; `C` unchanged |
| 7 | `DEC A` | `A ← A - 1`; `C` unchanged |

All except `SWAP`, `INC`, and `DEC` update `C`. All update `Z` and `N`.

### 3.3 `LOAD` — constants, memory, register moves (`opcode = 2`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `LDI A, imm` | `A ← imm` |
| 1 | `LDI X, imm` | `X ← imm` |
| 2 | `LDI Y, imm` | `Y ← imm` |
| 3 | `LD A, (X)` | `A ← data[X[5:0]]` |
| 4 | `ST (X), A` | `data[X[5:0]] ← A` |
| 5 | `LD A, (imm)` | `A ← data[imm[5:0]]` |
| 6 | `ST (imm), A` | `data[imm[5:0]] ← A` |
| 7 | `TFR` | register move selected by `imm[2:0]`, see below |

`TFR` codes:

| imm[2:0] | Operation |
|---|---|
| 0 | `A ← X` |
| 1 | `X ← A` |
| 2 | `A ← Y` |
| 3 | `Y ← A` |
| 4 | `X ← Y` |
| 5 | `Y ← X` |
| 6 | reserved (no effect) |
| 7 | reserved (no effect) |

`LOAD` does not affect flags.

### 3.4 `IO` — pins (`opcode = 3`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `OUT UO, A` | `uo_out ← A` |
| 1 | `OUT UIO, A` | `uio_out ← A` |
| 2 | `OUT UIO_OE, A` | `uio_oe ← A` (1 = drive) |
| 3 | `OUT UIO_OD, A` | `uio_od ← A` (1 = open-drain) |
| 4 | `IN UI` | `A ← ui_in` |
| 5 | `IN UIO` | `A ← uio_in` |
| 6 | `OUT UO, imm` | `uo_out ← imm` |
| 7 | `OUT UIO, imm` | `uio_out ← imm` |

`IN` reads the actual pad. `OUT UIO` changes only the output data register; a
pin is driven only where `uio_oe` is 1. `IO` does not affect flags.

**Open-drain rule:** if `uio_oe[i] = 1` and `uio_od[i] = 1`, the pad driver is
disabled whenever `uio_out[i] = 1`, and drives 0 when `uio_out[i] = 0`. This
implements a wired-AND/open-drain pin without external direction juggling.

### 3.5 `BRANCH` — control flow (`opcode = 4`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `JMP imm` | `PC ← imm[6:0]` |
| 1 | `JZ imm` | if `Z`, `PC ← imm[6:0]`, else `PC ← PC+1` |
| 2 | `JNZ imm` | if `!Z`, `PC ← imm[6:0]` |
| 3 | `JC imm` | if `C`, `PC ← imm[6:0]` |
| 4 | `JNC imm` | if `!C`, `PC ← imm[6:0]` |
| 5 | `CALL imm` | push `PC+1`; `PC ← imm[6:0]` |
| 6 | `RET` | pop `PC[6:0]` |
| 7 | `DJNZ Y, imm` | `Y ← Y-1`; if `Y != 0`, `PC ← imm[6:0]`, else `PC ← PC+1` |

All branches retire in one clock. `DJNZ` updates `Z` and `N` from the new `Y`;
`C` is unchanged. The return stack is circular and 8 entries deep; overflow
wraps. Firmware should keep call depth ≤ 8.

### 3.6 `TIME` — delays and pin waits (`opcode = 5`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `WAIT imm` | wait exactly `imm` cycles; `imm = 0` means 256 |
| 1 | `WAIT_PIN0 UI, mask` | wait until `(ui_in & mask) == 0` |
| 2 | `WAIT_PIN1 UI, mask` | wait until `(ui_in & mask) == mask` |
| 3 | `WAIT_PIN0 UIO, mask` | wait until `(uio_in & mask) == 0` |
| 4 | `WAIT_PIN1 UIO, mask` | wait until `(uio_in & mask) == mask` |
| 5 | `WAIT_EDGE UI, mask` | wait until any masked `ui_in` bit changes |
| 6 | `WAIT_EDGE UIO, mask` | wait until any masked `uio_in` bit changes |
| 7 | `HALT` | stop the CPU until the core is reset |

`WAIT n` includes the instruction's own cycle: `WAIT 1` is one cycle, `WAIT 0`
is 256 cycles. `WAIT_PIN*` and `WAIT_EDGE` retire in one cycle if the condition
is already true; otherwise they hold `PC` and sample the pins once per clock.
`WAIT_EDGE` captures the reference pin value on the first cycle of the
instruction and completes when a masked bit differs from that reference.

### 3.7 `BIT` — atomic pin bit operations (`opcode = 6`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `SETB UO, imm` | `uo_out ← uo_out | imm` |
| 1 | `CLRB UO, imm` | `uo_out ← uo_out & ~imm` |
| 2 | `TGLB UO, imm` | `uo_out ← uo_out ^ imm` |
| 3 | `SETB UIO, imm` | `uio_out ← uio_out | imm` |
| 4 | `CLRB UIO, imm` | `uio_out ← uio_out & ~imm` |
| 5 | `TGLB UIO, imm` | `uio_out ← uio_out ^ imm` |
| 6 | `SETB UIO_OE, imm` | `uio_oe ← uio_oe | imm` |
| 7 | `CLRB UIO_OE, imm` | `uio_oe ← uio_oe & ~imm` |

These do not touch `A` and do not affect flags. They are the fastest way to
toggle a clock or chip-select line: one instruction, one cycle.

### 3.8 `MISC` — register and small operations (`opcode = 7`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `NOP` | no effect; 1 cycle |
| 1 | `INC X` | `X ← X+1`; updates `Z`, `N` |
| 2 | `DEC X` | `X ← X-1`; updates `Z`, `N` |
| 3 | `INC Y` | `Y ← Y+1`; updates `Z`, `N` |
| 4 | `DEC Y` | `Y ← Y-1`; updates `Z`, `N` |
| 5 | `A = X` | alias for `TFR 0` |
| 6 | `X = A` | alias for `TFR 1` |
| 7 | `Y = A` | alias for `TFR 3` |

`INC`/`DEC` of `X`/`Y` leave `C` unchanged.

### 3.9 `ALUX` — accumulator with `X` (`opcode = 8`)

Same suboperations as `ALU`, but the operand is `X` instead of `imm`:
`ADD A,X`, `ADC A,X`, `SUB A,X`, `SBC A,X`, `AND A,X`, `OR A,X`,
`XOR A,X`, `CMP A,X`.

### 3.10 `ALUY` — accumulator with `Y` (`opcode = 9`)

Same table as `ALUX`, with `Y` as the operand.

### 3.11 `TIMER` — cycle counter (`opcode = 10`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `TMR_LO` | `A ← timer[7:0]`; latch `timer[15:8]` |
| 1 | `TMR_HI` | `A ← latched timer[15:8]` |
| 2 | `TMR_CLR` | `timer ← 0` |
| 3 | reserved | no effect |
| 4 | reserved | no effect |
| 5 | reserved | no effect |
| 6 | reserved | no effect |
| 7 | `ID` | `A ← 0xA1` (Proteus-1 signature) |

`TMR_LO` followed by `TMR_HI` gives an atomic 16-bit read. The counter
increments once per enabled clock. It is cleared by core reset and `TMR_CLR`.

### 3.12 `CAP` — capture FIFO (`opcode = 11`)

| sub | Mnemonic | Operation |
|---|---|---|
| 0 | `CAP_EN imm` | `cap_en ← imm[0]`; enabling resets the edge detector |
| 1 | `CAP_POP` | `cap_rd ← oldest entry`; advance read pointer |
| 2 | `CAP_UI` | `A ← cap_rd[7:0]` (ui_in byte) |
| 3 | `CAP_UIO` | `A ← cap_rd[15:8]` (uio_in byte) |
| 4 | `CAP_TS` | `A ← cap_rd[23:16]` (cycle timestamp) |
| 5 | `CAP_STATUS` | `A ← {full, empty, 4'b0, count[3:0]}` |
| 6 | `CAP_CLR` | clear FIFO, pointers, and `cap_rd` |
| 7 | reserved | no effect |

The capture engine samples `{uio_in, ui_in}` every enabled clock while
`cap_en=1`. Whenever the 16-bit pin vector differs from the previous sample, it
pushes `{timer[7:0], uio_in, ui_in}`. The FIFO holds 8 entries; new events are
dropped when full. `CAP_POP` on an empty FIFO is a no-op (the previous `cap_rd`
is retained). `CAP_STATUS` bits: `[7]=full`, `[6]=empty`, `[3:0]=count`.

`CAP_POP` and the subsequent `CAP_UI/UIO/TS` are separated by one instruction
boundary; the popped value is available to the next instruction.

### 3.13 Reserved opcodes

`opcode = 12..31` are reserved. They execute as `NOP` and must not be used.
The assembler emits an error for them.

## 4. Flags

- `Z` = 1 when the last flag-affecting result is zero.
- `N` = bit 7 of the last flag-affecting result.
- `C` = carry/borrow for arithmetic, shifted-out bit for shifts/rotates, 0 for
  logic operations. `INC`/`DEC`, `SWAP`, `LDI`, `LOAD`, `ST`, `TFR`, `IO`,
  `BIT`, `BRANCH` (except `DJNZ`), `WAIT`, `TIMER`, and `CAP` do not change `C`.

## 5. Cycle-accurate timing

The core advances on every rising `clk` where `run=1`, `CFG_CS_N=1`, and
`HALT=0`. One instruction per clock unless it is a waiting instruction.

| Instruction | Cycles |
|---|---|
| all ordinary instructions | 1 |
| `WAIT n` | `n` (n=1..255; n=0 → 256) |
| `WAIT_PIN*`, `WAIT_EDGE` | ≥1, until condition |
| `HALT` | 1, then no further execution |

Pin writes take effect at the clock edge that retires the instruction. Software
therefore sees a stable one-cycle grid: a `TGLB UO, 1` instruction toggles the
pin once every cycle when placed in a loop, and a `WAIT` sequence produces exact
delays.

## 6. Reset

`rst_n` low resets the entire chip, including the loader. The loader's `run`
bit is also cleared. The core is held in reset while `run=0`, so writing
`run=0` is the software reset. On `run=1`, the core starts at `PC=0` with
`A=X=Y=0`, flags clear, outputs 0, and `cap_en=0`.

## 7. Host loader protocol

The configuration port is a write-mostly synchronous serial target:

| Signal | Pin | Direction |
|---|---|---|
| `CFG_CS_N` | `ui_in[7]` | host → chip, active low |
| `CFG_SCK` | `ui_in[6]` | host → chip |
| `CFG_MOSI` | `ui_in[5]` | host → chip |
| `CFG_MISO` | `uo_out[7]` | chip → host (readback) |

`CFG_SCK` is synchronized to `clk`; use `f_SCK ≤ f_clk/4`.

Each frame is 32 bits, MSB first:

```
bit 31..24   bit 23..16   bit 15..0
 command      address      data
```

| Command | Meaning |
|---|---|
| `0x01` | write program word: `prog[address] ← data[15:0]` |
| `0x02` | write data byte: `data[address[5:0]] ← data[7:0]` |
| `0x03` | control: `run ← data[0]` (all other bits ignored) |
| `0x04` | read program word at `address[6:0]` into the MISO holding register |
| `0x00` | no operation (useful as a read-response frame) |

Readback is pipelined. Command `0x04` loads the 16-bit holding register; the
**next** frame shifts it out on `CFG_MISO`, MSB first, during its first 16 SCK
rising edges. The host samples MISO on the rising edge (SPI mode 0). Keep
`CFG_CS_N` low across the two frames, or at least do not reset the chip.

The loader carries an 8-bit address on the wire, but only `address[6:0]`
reaches the 128-word program memory. Address bit 7 is ignored. The CPU is
halted while `CFG_CS_N` is low. To reprogram safely:

1. Send control `0x03` with `data=0x0000` (run=0, core reset).
2. Send program/data frames.
3. Send control `0x03` with `data=0x0001` (run=1).

`uo_out[7]` is MISO only while `CFG_CS_N` is low. After configuration it is a
normal CPU-controlled output. The host must leave `ui_in[7:5]` static while the
CPU is running if the firmware uses them as GPIO.

## 8. Assembler syntax

```asm
; comment
.equ NAME, value
.org 0x00
start:
    LDI A, 0x55
    OUT UO, A
    WAIT 10
    JMP start
```

- Labels end with `:` and resolve to word addresses.
- `.equ` defines a constant (no forward references).
- `.org` sets the current word address.
- `.byte`, `.word`, `.fill`, `.align` emit data into the program image; they
  are useful for lookup tables and self-test vectors.
- `DB`/`DW` are aliases for `.byte`/`.word`.
- `TFR n` accepts a numeric code or the symbolic names in §3.3.
- Immediate operands may be labels (low 8 bits are used), numbers, or
  expressions with `+ - * / & | ^ << >>` and parentheses.

The assembler emits Intel HEX, a listing, and a JSON metadata file with the
symbol table and cycle count. `tools/proteus_asm.py --help` is the authority for
command-line flags.

## 9. Version

ISA v1.0, 2026-10-29. Program memory is 128 x 16; PC is 7 bits. An ISA change is
one atomic commit that updates this document, the RTL, the assembler, the ISS,
and the tests together.

## 10. Reference firmware pinouts

These are the pin assignments used by the example programs. They are firmware
choices, not silicon constraints; the CPU can read and drive any pin.

| Example | Pins |
|---|---|
| `uart_tx.s` | TX on `uo_out[7]` (bit-rotated byte), 8N1, 417 cycles/bit at 32 MHz (76.8 kbaud) |
| `uart_rx.s` | RX on `ui_in[3]`, 8N1, 417 cycles/bit at 32 MHz (76.8 kbaud) |
| `spi_master.s` | `uio[0]=CS_N`, `uio[1]=MOSI`, `uio[2]=MISO`, `uio[3]=SCK`; CPOL=0, modes 0–1 |
| `spi_master_cpol1.s` | same pins; SCK idles high, CPOL=1, modes 2–3 |
| `spi_target.s` | `ui[0]=CS_N`, `ui[1]=MOSI`, `ui[2]=SCK`; received byte on `uo_out`, mode 0 |
| `i2c_master.s` | `uio[2]=SCL`, `uio[3]=SDA`, open-drain, external pull-ups, ~100 kHz |
| `i2c_master_400k.s` | same pins; WAIT 38 bit loop, ~386 kHz at 32 MHz |
| `i2c_target.s` | `uio[2]=SCL`, `uio[3]=SDA`, address 0x28, received byte on `uo_out[6:0]` |
| `ps2_device.s` | `uio[0]=DATA`, `uio[1]=CLK`, open-drain, 11-bit device frame |
| `capture_demo.s` | captures `ui_in[1:0]` changes; reports on `uo_out` |

The configuration port is always `ui_in[7]=CS_N`, `ui_in[6]=SCK`,
`ui_in[5]=MOSI`, and `uo_out[7]=MISO` while CS_N is low.
