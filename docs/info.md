## How it works

Proteus-1 is a field-reprogrammable protocol engine: one small chip that becomes
a UART, an SPI controller, an I2C target, or a logic analyzer after fabrication.
It is not a fixed set of peripherals. It is an 8-bit single-cycle CPU whose
instruction set is built around pins, edges, and exact cycle counts.

- **8-bit accumulator CPU** with `A`, `X`, `Y`, 7-bit `PC`, an 8-deep return
  stack, and `Z`/`C`/`N` flags.
- **128 x 16 program memory** and **64 x 8 data memory**, loaded by the host.
- **24 digital pins**: 8 inputs, 8 outputs, and 8 bidirectional pins with
  per-bit output enable and per-bit open-drain mode.
- **Exact timing instructions**: `WAIT n` burns exactly `n` clocks (0 = 256),
  `WAIT_PIN0/1` and `WAIT_EDGE` stall on a masked pin level or edge.
- **16-bit cycle counter** with an atomic low/high read sequence.
- **8-entry capture FIFO** that records `{timer[7:0], uio_in, ui_in}` on every
  pin change, so the chip can observe a bus as well as drive it.
- **SPI host loader** on `ui_in[7:5]`, status/readback on `uo_out[7]`.

Every ordinary instruction retires in one clock. There is no pipeline, no
branch penalty, and no hidden wait state, so firmware is written as a timing
diagram. New protocols are firmware loaded after fabrication.

## Pinout

| Pin | Loader mode (`CS_N` low) | Run mode |
|---|---|---|
| `ui_in[7]` | `CFG_CS_N` (active low) | GPIO input |
| `ui_in[6]` | `CFG_SCK` | GPIO input |
| `ui_in[5]` | `CFG_MOSI` | GPIO input |
| `ui_in[4:0]` | GPIO inputs | GPIO inputs |
| `uo_out[7]` | `CFG_MISO` | GPIO output / default UART TX |
| `uo_out[6:0]` | 0 | GPIO outputs |
| `uio[7:0]` | high impedance | GPIO, open-drain capable |

The default example firmware uses `uo_out[7]` for UART TX at 115200 8N1,
`ui_in[3]` for UART RX, and the standard Tiny Tapeout Pmod pinout for SPI
(`uio[0]` CS, `uio[1]` MOSI, `uio[2]` MISO, `uio[3]` SCK) and I2C
(`uio[2]` SCL, `uio[3]` SDA).

## Host loader

The loader is an SPI mode-0 target. A frame is 32 bits, MSB first:

```
{ command[7:0], address[7:0], data[15:0] }
```

| Command | Meaning |
|---|---|
| `0x00` | no operation / readback frame |
| `0x01` | write program word (`data` is the instruction) |
| `0x02` | write data byte (`data[7:0]`) |
| `0x03` | control: bit 0 = run |
| `0x04` | latch program word at `address` for the next frame's MISO |

`0x04` is pipelined: the next 32-bit frame shifts the latched word out on
`CFG_MISO` during its first 16 rising edges. The CPU is held in reset while
`run=0` and held (not reset) while `CS_N` is low. `SCK` must be at most `clk/4`;
the reference host runs at 100 kHz, far below that.

The loader pins are synchronized with two flip-flops. The protocol pins
(`ui_in`, `uio`) are deliberately **not** synchronized: the CPU samples the
actual pad, and protocol firmware owns debouncing and majority sampling.

## How to test

1. Load a program image with the MicroPython host script in `host/` or any
   SPI host that speaks the frame format above.
2. For UART, connect `uo_out[7]` to a 3.3 V USB-UART adapter's RX at 115200
   8N1 and load `programs/uart_tx.s`. The chip prints `P1\n`.
3. For SPI, connect the Pmod pins to a SPI target and load
   `programs/spi_master.s`; it sends `0xA5` in mode 0.
4. For I2C, add 4.7k pull-ups from `uio[2]`/`uio[3]` to 3.3 V and load
   `programs/i2c_master.s` or `programs/i2c_target.s`.
5. Rebuild and rerun the simulation with `cd test && make -B`; all 13 tests
   should pass.

On power-up the program memory is undefined, so the chip does nothing until the
host loads an image and sets `run=1`.

## External hardware

- A 3.3 V USB-UART adapter for the UART demo.
- 4.7k pull-up resistors for I2C (both controller and target roles).
- Optionally a Tiny Tapeout Pmod breakout for SPI/I2C.
- No external clock, crystal, or analog supply is required; the chip runs from
  the demo board clock and I/O voltage.
