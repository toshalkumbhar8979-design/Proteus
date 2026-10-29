# Proteus-1 RTL tests

The suite uses cocotb 2.x with Icarus Verilog. It drives the chip through its
real SPI loader and checks the pins, not internal state, except in the
randomized co-simulation test, which compares every architectural register
against the Python ISS.

## Run

```sh
python3 -m pip install -r requirements.txt
make -B
```

Expected result: `TESTS=14 PASS=14 FAIL=0 SKIP=0`.

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
| `test_i2c_master` / `test_i2c_target` | open-drain I2C, both roles |
| `test_capture` | timestamped pin-change FIFO |
| `test_pin_wait` | level waits on `ui_in` |
| `test_random_cosim` | 1,000-clock RTL/ISS lock-step |

## Gate level

`make -B GATES=yes` expects `gate_level_netlist.v` in this directory, produced
by the Tiny Tapeout GDS action. No hardened netlist exists in the repository
yet, so gate-level simulation has not been run. Do not report it as passing.

## Waveforms

The testbench writes `tb.fst`. View it with `gtkwave tb.fst` or `surfer tb.fst`.
Use `make -B FST=` for a VCD instead.
