# Proteus-1 RTL tests

The suite uses cocotb 2.x with Icarus Verilog. It drives the chip through its
real SPI loader and checks the pins. Three white-box tests (`test_timer_cosim`,
`test_opcode_sweep`, and `test_random_cosim`) also compare architectural
registers against the Python ISS; they are RTL-only because the hardened
netlist is flattened.

## Run

```sh
python3 -m pip install -r requirements.txt
make -B
```

Expected result: `TESTS=20 PASS=20 FAIL=0 SKIP=0`. Under `GATES=yes` the three
white-box tests are skipped: `TESTS=20 PASS=17 FAIL=0 SKIP=3`.

## What is covered

| Test | Check |
|---|---|
| `test_reset` | outputs driven low, no floating pins |
| `test_loader_readback` | program write and pipelined readback |
| `test_selftest_basic` | ALU, flags, memory, bit ops, timer signature |
| `test_wait_timing` | exact `WAIT` cycle deltas |
| `test_uart_tx` / `test_uart_rx` | 8N1 at 417 cycles/bit, both directions |
| `test_spi_master` / `test_spi_other_modes` | SPI master modes 0–3 |
| `test_spi_target` | SPI target role, mode 0 |
| `test_i2c_master` / `test_i2c_master_400k` | open-drain I2C master at 100 and 400 kHz |
| `test_i2c_target` / `test_i2c_target_400k` | open-drain I2C target at 100 and 400 kHz |
| `test_ps2_device` | PS/2 11-bit device frame, odd parity |
| `test_capture` / `test_capture_overflow` | timestamped pin-change FIFO, full/overflow status |
| `test_pin_wait` | level waits on `ui_in` |
| `test_timer_cosim` | timer clear, atomic latch, wrap past 255 cycles |
| `test_opcode_sweep` | all 96 opcode/subop encodings against the ISS |
| `test_random_cosim` | 1,000-clock RTL/ISS lock-step |

## Gate level

`make -B GATES=yes` expects `gate_level_netlist.v` in this directory, produced
by the Tiny Tapeout GDS action. `GATES=yes` is exported to cocotb, which skips
the three tests that read core registers; the remaining 17 tests exercise the
chip only through its pins. The first GDS run failed post-route setup at
48 MHz, so no gate-level result is claimed yet. Do not report it as passing
until the rerun's `gl_test` job is green.

## Waveforms

The testbench writes `tb.fst`. View it with `gtkwave tb.fst` or `surfer tb.fst`.
Use `make -B FST=` for a VCD instead.
