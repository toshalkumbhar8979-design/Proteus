# SPDX-FileCopyrightText: 2026 Proteus-1 contributors
# SPDX-License-Identifier: Apache-2.0

"""Cocotb tests for the Proteus-1 chip.

The tests use the real SPI loader, not a simulation backdoor, so they exercise
the same path the RP2350 host uses on the demo board.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import proteus_isa as isa  # noqa: E402
from proteus_asm import AsmError, Image, assemble  # noqa: E402
from proteus_iss import ProteusISS  # noqa: E402

CLK_NS = 10                  # 100 MHz simulation clock
SPI_HALF = 4                 # SCK half-period in clocks (<= clk/4 requirement)

# The hardened netlist is flattened, so the three white-box tests that read
# core registers cannot run against it. They stay enabled for every RTL run;
# the gate-level run executes the pin-level tests instead. test/Makefile
# exports GATES=yes for the gate-level branch.
GATE_LEVEL = os.environ.get("GATES", "").lower() == "yes"

CS_BIT = 7
SCK_BIT = 6
MOSI_BIT = 5


def ui_word(cs: int, sck: int, mosi: int, low: int = 0) -> int:
    return ((cs & 1) << CS_BIT) | ((sck & 1) << SCK_BIT) | ((mosi & 1) << MOSI_BIT) | (low & 0x1F)


async def reset_dut(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = ui_word(1, 0, 0)
    dut.sda_pull.value = 0
    dut.scl_drive_low.value = 0
    dut.sda_drive_low.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 8)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 8)


async def spi_frame(
    dut,
    cmd: int,
    addr: int = 0,
    data: int = 0,
    *,
    read: bool = False,
    hold_cs: bool = False,
    post_wait: int = 4,
) -> int | None:
    """Send one 32-bit loader frame. Optionally sample the 16-bit read reply."""
    word = ((cmd & 0xFF) << 24) | ((addr & 0xFF) << 16) | (data & 0xFFFF)
    dut.ui_in.value = ui_word(0, 0, 0)
    await ClockCycles(dut.clk, 4)

    reply = 0
    for i in range(32):
        bit = (word >> (31 - i)) & 1
        dut.ui_in.value = ui_word(0, 0, bit)
        await ClockCycles(dut.clk, 2)
        if read and i < 16:
            reply = (reply << 1) | (int(dut.uo_out.value) >> 7 & 1)
        dut.ui_in.value = ui_word(0, 1, bit)
        await ClockCycles(dut.clk, 2)
        dut.ui_in.value = ui_word(0, 0, bit)
        await ClockCycles(dut.clk, 2)

    if hold_cs:
        dut.ui_in.value = ui_word(0, 0, 0)
        return reply if read else None

    dut.ui_in.value = ui_word(1, 0, 0)
    if post_wait:
        await ClockCycles(dut.clk, post_wait)
    return reply if read else None


async def read_program_word(dut, addr: int) -> int:
    await spi_frame(dut, 0x04, addr, 0)
    got = await spi_frame(dut, 0x00, 0, 0, read=True)
    assert got is not None
    return got


async def load_image(dut, image: Image, *, verify: bool = True, settle: int = 1) -> None:
    # Stop and reset the core before touching memory.
    await spi_frame(dut, 0x03, 0, 0)
    for addr, word in sorted(image.program.items()):
        await spi_frame(dut, 0x01, addr, word)
    for addr, byte in sorted(image.data.items()):
        await spi_frame(dut, 0x02, addr, byte)

    if verify and image.program:
        first = sorted(image.program)[0]
        last = sorted(image.program)[-1]
        got = await read_program_word(dut, first)
        assert got == image.program[first], f"readback {first:02X}: {got:04X} != {image.program[first]:04X}"
        got = await read_program_word(dut, last)
        assert got == image.program[last], f"readback {last:02X}: {got:04X} != {image.program[last]:04X}"

    # Release run and do not burn clocks here; the caller starts monitoring.
    await spi_frame(dut, 0x03, 0, 1, post_wait=0)
    if settle:
        await ClockCycles(dut.clk, settle)


async def wait_for_uo(dut, value: int, limit: int = 20000) -> int:
    for cycle in range(limit):
        await RisingEdge(dut.clk)
        if int(dut.uo_out.value) == value:
            return cycle
    raise AssertionError(f"uo_out never became 0x{value:02X}")


async def collect_uo_changes(dut, stop_value: int, limit: int = 20000) -> list[int]:
    seen: list[int] = []
    last = int(dut.uo_out.value)
    for _ in range(limit):
        await RisingEdge(dut.clk)
        v = int(dut.uo_out.value)
        if v != last:
            seen.append(v)
            last = v
        if v == stop_value:
            return seen
    raise AssertionError(f"did not reach 0x{stop_value:02X}; saw {[hex(x) for x in seen]}")


def load_source(name: str) -> Image:
    path = ROOT / "programs" / name
    return assemble(path.read_text(encoding="utf-8"), str(path))


@cocotb.test()
async def test_reset(dut):
    await reset_dut(dut)
    assert int(dut.uo_out.value) == 0
    assert int(dut.uio_out.value) == 0
    assert int(dut.uio_oe.value) == 0


@cocotb.test()
async def test_loader_readback(dut):
    await reset_dut(dut)
    image = load_source("selftest_basic.s")
    await spi_frame(dut, 0x03, 0, 0)
    for addr, word in sorted(image.program.items()):
        await spi_frame(dut, 0x01, addr, word)
    first = sorted(image.program)[0]
    last = sorted(image.program)[-1]
    assert await read_program_word(dut, first) == image.program[first]
    assert await read_program_word(dut, last) == image.program[last]


@cocotb.test()
async def test_selftest_basic(dut):
    await reset_dut(dut)
    image = load_source("selftest_basic.s")
    await load_image(dut, image)
    seen = await collect_uo_changes(dut, 0xA1)
    expected = [0x55, 0xAA, 0x07, 0xC3, 0x03, 0x04, 0x11, 0x91, 0x90, 0x10, 0xA1]
    assert seen == expected, f"saw {[hex(x) for x in seen]}, expected {[hex(x) for x in expected]}"


@cocotb.test()
async def test_wait_timing(dut):
    await reset_dut(dut)
    src = """
        OUT UO, 0x01
        WAIT 10
        OUT UO, 0x02
        WAIT 20
        OUT UO, 0x03
        HALT
    """
    image = assemble(src)
    await load_image(dut, image, verify=False)

    await wait_for_uo(dut, 0x01)
    # Count clocks from the edge that made 0x01 visible.
    t2 = None
    t3 = None
    cycle = 0
    while t3 is None and cycle < 5000:
        await RisingEdge(dut.clk)
        cycle += 1
        v = int(dut.uo_out.value)
        if v == 0x02 and t2 is None:
            t2 = cycle
        elif v == 0x03 and t3 is None:
            t3 = cycle
    assert t2 is not None and t3 is not None
    assert t2 == 11, f"WAIT 10 delta {t2}, expected 11"
    assert t3 - t2 == 21, f"WAIT 20 delta {t3 - t2}, expected 21"


async def wait_cycles(dut, n: int) -> int:
    """Advance n rising edges and return uo_out afterwards."""
    for _ in range(n):
        await RisingEdge(dut.clk)
    return int(dut.uo_out.value)


async def uart_decode_byte(dut, bit_cycles: int = 417) -> int:
    """Wait for a start bit and decode one 8N1 byte from uo_out[7]."""
    # Find the falling edge that starts the frame.
    for _ in range(20000):
        await RisingEdge(dut.clk)
        if ((int(dut.uo_out.value) >> 7) & 1) == 0:
            break
    else:
        raise AssertionError("no UART start bit")

    # Sample at the middle of each bit. The start edge was just seen.
    await ClockCycles(dut.clk, bit_cycles // 2)
    assert ((int(dut.uo_out.value) >> 7) & 1) == 0, "start bit not low"

    value = 0
    for i in range(8):
        await ClockCycles(dut.clk, bit_cycles)
        bit = (int(dut.uo_out.value) >> 7) & 1
        value |= bit << i
    await ClockCycles(dut.clk, bit_cycles)
    stop = (int(dut.uo_out.value) >> 7) & 1
    assert stop == 1, "stop bit not high"
    return value


@cocotb.test()
async def test_uart_tx(dut):
    await reset_dut(dut)
    image = load_source("uart_tx.s")
    await load_image(dut, image)
    got = [await uart_decode_byte(dut) for _ in range(3)]
    assert got == [0x50, 0x31, 0x0A], f"UART decoded {[hex(x) for x in got]}"


async def spi_slave_receive(dut, nbits: int = 8, cpol: int = 0, cpha: int = 0,
                            limit: int = 20000) -> int:
    """Wait for CS low and sample MOSI on the mode's sample edge.

    CPHA=0 samples the first clock edge, CPHA=1 samples the second. The first
    edge is rising when CPOL=0 and falling when CPOL=1, so the sample edge is
    rising exactly when CPOL == CPHA.
    """
    for _ in range(limit):
        await RisingEdge(dut.clk)
        if (int(dut.uio_oe.value) & 0x01) and ((int(dut.uio_out.value) & 0x01) == 0):
            break
    else:
        raise AssertionError("SPI CS never asserted")

    value = 0
    count = 0
    sample_rising = cpol == cpha
    last_sck = (int(dut.uio_out.value) >> 3) & 1
    for _ in range(limit):
        await RisingEdge(dut.clk)
        uio = int(dut.uio_out.value)
        sck = (uio >> 3) & 1
        edge = (sck and not last_sck) if sample_rising else (last_sck and not sck)
        if edge:
            value = (value << 1) | ((uio >> 1) & 1)
            count += 1
            if count == nbits:
                break
        last_sck = sck
    else:
        raise AssertionError(f"only saw {count} SPI edges")

    for _ in range(limit):
        await RisingEdge(dut.clk)
        if int(dut.uio_out.value) & 0x01:
            break
    else:
        raise AssertionError("SPI CS never deasserted")
    return value


async def uart_send_byte(dut, value: int, bit_cycles: int = 417) -> None:
    """Drive one 8N1 byte on ui_in[3], LSB first."""
    dut.ui_in.value = ui_word(1, 0, 0, low=0x00)  # start bit low
    await ClockCycles(dut.clk, bit_cycles)
    for i in range(8):
        bit = (value >> i) & 1
        dut.ui_in.value = ui_word(1, 0, 0, low=(bit << 3))
        await ClockCycles(dut.clk, bit_cycles)
    dut.ui_in.value = ui_word(1, 0, 0, low=0x08)  # stop bit high
    await ClockCycles(dut.clk, bit_cycles)


@cocotb.test()
async def test_uart_rx(dut):
    await reset_dut(dut)
    image = load_source("uart_rx.s")
    await load_image(dut, image)
    await uart_send_byte(dut, 0x5A)
    await wait_for_uo(dut, 0x5A, limit=5000)
    assert int(dut.uo_out.value) == 0x5A


async def ps2_receive(dut, nbits: int = 11, limit: int = 200000) -> list[int]:
    """Decode a PS/2 frame from the open-drain uio[0]=DATA, uio[1]=CLK lines."""
    bits: list[int] = []
    last_clk = 1
    for _ in range(limit):
        await RisingEdge(dut.clk)
        oe = int(dut.uio_oe.value)
        out = int(dut.uio_out.value)
        clk = 0 if ((oe & 0x02) and not (out & 0x02)) else 1
        data = 0 if ((oe & 0x01) and not (out & 0x01)) else 1
        if last_clk and not clk:
            bits.append(data)
            if len(bits) == nbits:
                break
        last_clk = clk
    return bits


@cocotb.test()
async def test_ps2_device(dut):
    await reset_dut(dut)
    image = load_source("ps2_device.s")
    await load_image(dut, image)
    bits = await ps2_receive(dut, 11)
    assert len(bits) == 11, f"PS/2 frame had {len(bits)} bits"
    assert bits[0] == 0, "PS/2 start bit not low"
    value = 0
    for i, bit in enumerate(bits[1:9]):
        value |= bit << i
    assert value == 0x5A, f"PS/2 data 0x{value:02X}"
    assert (sum(bits[1:9]) + bits[9]) & 1 == 1, "PS/2 odd parity failed"
    assert bits[10] == 1, "PS/2 stop bit not high"
    await wait_for_uo(dut, 0x5A, limit=5000)


@cocotb.test()
async def test_spi_master(dut):
    await reset_dut(dut)
    image = load_source("spi_master.s")
    await load_image(dut, image)
    got = await spi_slave_receive(dut, 8)
    assert got == 0xA5, f"SPI received 0x{got:02X}"
    await ClockCycles(dut.clk, 4)
    assert int(dut.uo_out.value) == 0x5A, f"done marker 0x{int(dut.uo_out.value):02X}"


@cocotb.test()
async def test_spi_other_modes(dut):
    """SPI modes 1-3: the same data waveform, three other sampling edges."""
    cases = [
        ("spi_master.s", 0, 1),
        ("spi_master_cpol1.s", 1, 0),
        ("spi_master_cpol1.s", 1, 1),
    ]
    for name, cpol, cpha in cases:
        await reset_dut(dut)
        image = load_source(name)
        await load_image(dut, image)
        got = await spi_slave_receive(dut, 8, cpol=cpol, cpha=cpha)
        assert got == 0xA5, (
            f"SPI mode CPOL={cpol} CPHA={cpha} received 0x{got:02X}"
        )
        await ClockCycles(dut.clk, 4)
        assert int(dut.uo_out.value) == 0x5A, (
            f"mode CPOL={cpol} CPHA={cpha} done marker "
            f"0x{int(dut.uo_out.value):02X}"
        )


async def i2c_target_model(dut, expected_addr: int = 0x50, expected_data: int = 0x42):
    """Minimal I2C target: detect START, ACK address/data, detect STOP."""
    dut.sda_pull.value = 0

    def bus():
        v = int(dut.uio_in.value)
        return (v >> 2) & 1, (v >> 3) & 1  # SCL, SDA

    last_scl = bus()[0]

    async def wait_scl(level: int):
        nonlocal last_scl
        for _ in range(20000):
            await RisingEdge(dut.clk)
            scl, _ = bus()
            if scl != last_scl and scl == level:
                last_scl = scl
                return
            last_scl = scl
        raise AssertionError(f"SCL never reached {level}")

    async def receive_byte() -> int:
        value = 0
        for _ in range(8):
            await wait_scl(1)
            _, sda = bus()
            value = (value << 1) | sda
        return value

    async def ack() -> None:
        dut.sda_pull.value = 1
        await wait_scl(0)   # end of the eighth bit
        await wait_scl(1)   # ACK clock high
        await wait_scl(0)   # ACK clock low; release SDA
        dut.sda_pull.value = 0

    # START: SDA falls while SCL is high.
    prev_sda = 1
    for _ in range(20000):
        await RisingEdge(dut.clk)
        scl, sda = bus()
        if scl and prev_sda and not sda:
            break
        prev_sda = sda
    else:
        raise AssertionError("no I2C START")

    addr = await receive_byte()
    await ack()
    data = await receive_byte()
    await ack()

    # STOP: SDA rises while SCL is high.
    prev_sda = 0
    prev_scl = 0
    for _ in range(20000):
        await RisingEdge(dut.clk)
        scl, sda = bus()
        if scl and prev_scl and (not prev_sda) and sda:
            break
        prev_sda, prev_scl = sda, scl
    else:
        raise AssertionError("no I2C STOP")

    assert addr == expected_addr, f"I2C address 0x{addr:02X} != 0x{expected_addr:02X}"
    assert data == expected_data, f"I2C data 0x{data:02X} != 0x{expected_data:02X}"


@cocotb.test()
async def test_capture_overflow(dut):
    """More than eight pin changes must assert full and drop new entries."""
    src = """
        CAP_EN 1
        WAIT_PIN1 UI, 0x02
        CAP_STATUS
        OUT UO, A
        HALT
    """
    image = assemble(src)
    await reset_dut(dut)
    await load_image(dut, image)
    await ClockCycles(dut.clk, 5)

    # Ten toggles of ui[0] fill the eight-entry FIFO; the ninth and tenth are
    # dropped. Then ui[1] releases the firmware to read the status byte.
    for i in range(10):
        dut.ui_in.value = ui_word(1, 0, 0, low=(0x01 if i % 2 == 0 else 0x00))
        await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ui_word(1, 0, 0, low=0x02)

    await wait_for_uo(dut, 0x88, limit=5000)
    status = int(dut.uo_out.value)
    assert status == 0x88, f"capture status 0x{status:02X}, expected full+8"


@cocotb.test()
async def test_capture(dut):
    await reset_dut(dut)
    image = load_source("capture_demo.s")
    await load_image(dut, image)

    # The program enables capture, then waits 40 cycles. Toggle two ui bits
    # three times inside that window. CS_N stays high, so the loader is idle.
    await ClockCycles(dut.clk, 5)
    dut.ui_in.value = ui_word(1, 0, 0, low=0x01)
    await ClockCycles(dut.clk, 5)
    dut.ui_in.value = ui_word(1, 0, 0, low=0x03)
    await ClockCycles(dut.clk, 5)
    dut.ui_in.value = ui_word(1, 0, 0, low=0x02)

    seen = await collect_uo_changes(dut, 0xAA, limit=5000)
    assert len(seen) == 5, f"capture outputs {[hex(x) for x in seen]}"
    assert seen[0] == 0x03, f"capture count 0x{seen[0]:02X}, expected 3"
    assert seen[1] == 0x81, f"capture ui 0x{seen[1]:02X}, expected 0x81"
    assert seen[2] == 0x0C, f"capture uio 0x{seen[2]:02X}, expected 0x0C"
    assert 0 < seen[3] < 80, f"capture timestamp {seen[3]} out of range"
    assert seen[4] == 0xAA


async def spi_master_send_ui(dut, value: int) -> None:
    """Bit-bang an SPI mode-0 byte on ui[0]=CS, ui[1]=MOSI, ui[2]=SCK."""
    dut.ui_in.value = ui_word(1, 0, 0, low=0x00)  # CS low, SCK low
    await ClockCycles(dut.clk, 8)
    for i in range(7, -1, -1):
        bit = (value >> i) & 1
        dut.ui_in.value = ui_word(1, 0, 0, low=(bit << 1))  # MOSI
        await ClockCycles(dut.clk, 8)
        dut.ui_in.value = ui_word(1, 0, 0, low=(bit << 1) | 0x04)  # SCK high
        await ClockCycles(dut.clk, 10)
        dut.ui_in.value = ui_word(1, 0, 0, low=(bit << 1))  # SCK low
        await ClockCycles(dut.clk, 24)
    dut.ui_in.value = ui_word(1, 0, 0, low=0x01)  # CS high
    await ClockCycles(dut.clk, 8)


@cocotb.test()
async def test_spi_target(dut):
    await reset_dut(dut)
    image = load_source("spi_target.s")
    await load_image(dut, image)
    await spi_master_send_ui(dut, 0xA5)
    await wait_for_uo(dut, 0xA5, limit=5000)
    assert int(dut.uo_out.value) == 0xA5


@cocotb.test()
async def test_i2c_master(dut):
    await reset_dut(dut)
    image = load_source("i2c_master.s")
    target = cocotb.start_soon(i2c_target_model(dut))
    await load_image(dut, image)
    await wait_for_uo(dut, 0x5A, limit=50000)
    await target


async def i2c_scl_periods(dut, cycles: int = 2400) -> list[int]:
    """Return the clock counts between consecutive SCL rising edges."""
    periods: list[int] = []
    last_scl = 1
    last_rise = None
    for cycle in range(cycles):
        await RisingEdge(dut.clk)
        scl = (int(dut.uio_in.value) >> 2) & 1
        if scl and not last_scl:
            if last_rise is not None:
                periods.append(cycle - last_rise)
            last_rise = cycle
        last_scl = scl
    return periods


@cocotb.test()
async def test_i2c_master_400k(dut):
    """400 kHz variant: verify the exchange and the SCL bit period."""
    await reset_dut(dut)
    image = load_source("i2c_master_400k.s")
    target = cocotb.start_soon(i2c_target_model(dut))
    await load_image(dut, image)
    monitor = cocotb.start_soon(i2c_scl_periods(dut, 2400))
    await wait_for_uo(dut, 0x5A, limit=20000)
    periods = await monitor
    await target

    # At 32 MHz, 400 kHz is 80 clocks per SCL period. The firmware targets
    # 83; allow 80-84 for the instruction path and the ACK stretch.
    bit_periods = [p for p in periods if 76 <= p <= 86]
    assert len(bit_periods) >= 8, f"too few SCL periods: {periods}"
    assert all(80 <= p <= 84 for p in bit_periods), (
        f"SCL periods outside the 400 kHz window: {periods}"
    )


async def i2c_controller_exchange(dut, scl_half: int = 20) -> tuple[bool, bool]:
    """Drive an I2C write of 0x42 to 0x28 and return the two ACK bits.

    scl_half is the SCL high/low time in clocks. The default 20 matches the
    100 kHz controller model; 40 gives an 80-clock SCL period, which is 400 kHz
    at the declared 32 MHz clock.
    """
    dut.sda_pull.value = 0

    def sda() -> int:
        return (int(dut.uio_in.value) >> 3) & 1

    async def wait(n: int) -> None:
        await ClockCycles(dut.clk, n)

    quarter = max(1, scl_half // 2)

    def drive_scl(low: bool) -> None:
        dut.scl_drive_low.value = 1 if low else 0

    def drive_sda(low: bool) -> None:
        dut.sda_drive_low.value = 1 if low else 0

    # Idle high.
    drive_scl(False)
    drive_sda(False)
    await wait(scl_half + quarter)

    # START.
    drive_sda(True)
    await wait(scl_half)
    drive_scl(True)
    await wait(scl_half)

    async def send_bit(bit: int) -> None:
        drive_sda(bit == 0)
        await wait(quarter)
        drive_scl(False)   # release SCL high
        await wait(scl_half)
        drive_scl(True)    # pull SCL low
        await wait(scl_half)

    async def read_ack() -> bool:
        drive_sda(False)   # release SDA so the target can ACK
        await wait(quarter)
        drive_scl(False)   # ACK clock high
        await wait(scl_half)
        ack = sda() == 0
        drive_scl(True)
        await wait(scl_half)
        drive_sda(False)
        await wait(quarter)
        return ack

    async def send_byte(value: int) -> bool:
        for i in range(7, -1, -1):
            await send_bit((value >> i) & 1)
        return await read_ack()

    ack_addr = await send_byte(0x50)
    ack_data = await send_byte(0x42)

    # STOP.
    drive_sda(True)
    await wait(scl_half)
    drive_scl(False)
    await wait(scl_half)
    drive_sda(False)
    await wait(scl_half + quarter)
    return ack_addr, ack_data


@cocotb.test()
async def test_i2c_target(dut):
    await reset_dut(dut)
    image = load_source("i2c_target.s")
    await load_image(dut, image)
    ack_addr, ack_data = await i2c_controller_exchange(dut)
    assert ack_addr, "target did not ACK its address"
    assert ack_data, "target did not ACK the data byte"
    for _ in range(1000):
        await RisingEdge(dut.clk)
        if int(dut.uo_out.value) & 0x80:
            break
    else:
        raise AssertionError("target never set the done flag")
    assert (int(dut.uo_out.value) & 0x7F) == 0x42, f"target received 0x{int(dut.uo_out.value) & 0x7F:02X}"


@cocotb.test()
async def test_i2c_target_400k(dut):
    """Same target firmware with an 80-clock SCL period (400 kHz at 32 MHz)."""
    await reset_dut(dut)
    image = load_source("i2c_target.s")
    await load_image(dut, image)
    ack_addr, ack_data = await i2c_controller_exchange(dut, scl_half=40)
    assert ack_addr, "400 kHz target did not ACK its address"
    assert ack_data, "400 kHz target did not ACK the data byte"
    for _ in range(2000):
        await RisingEdge(dut.clk)
        if int(dut.uo_out.value) & 0x80:
            break
    else:
        raise AssertionError("400 kHz target never set the done flag")
    assert (int(dut.uo_out.value) & 0x7F) == 0x42, (
        f"400 kHz target received 0x{int(dut.uo_out.value) & 0x7F:02X}"
    )


def random_instruction(rng) -> int:
    """Generate one safe instruction for RTL/ISS co-simulation."""
    kind = rng.randrange(12)
    if kind < 4:
        return isa.encode(isa.OP_ALU, rng.randrange(8), rng.randrange(256))
    if kind == 4:
        return isa.encode(isa.OP_ALUX, rng.randrange(8), 0)
    if kind == 5:
        return isa.encode(isa.OP_ALUY, rng.randrange(8), 0)
    if kind == 6:
        return isa.encode(isa.OP_SHIFT, rng.randrange(8), 0)
    if kind == 7:
        sub = rng.randrange(8)
        imm = rng.randrange(6) if sub == 7 else rng.randrange(256)
        return isa.encode(isa.OP_LOAD, sub, imm)
    if kind == 8:
        # UO only: avoid changing the testbench bus model.
        sub = rng.choice([0, 4, 5, 6])
        return isa.encode(isa.OP_IO, sub, rng.randrange(256))
    if kind == 9:
        sub = rng.randrange(8)
        return isa.encode(isa.OP_BRANCH, sub, rng.randrange(128))
    if kind == 10:
        # WAIT or the UO-only BIT operations. Do not touch UIO here: the
        # testbench bus model would change uio_in and the ISS would need a
        # bus model too.
        which = rng.randrange(4)
        if which == 0:
            return isa.encode(isa.OP_TIME, 0, rng.randrange(9))
        return isa.encode(isa.OP_BIT, which - 1, rng.randrange(256))
    if kind == 11:
        which = rng.randrange(3)
        if which == 0:
            return isa.encode(isa.OP_MISC, rng.randrange(8), 0)
        if which == 1:
            return isa.encode(isa.OP_TIMER, rng.choice([0, 1, 2, 7]), 0)
        return isa.encode(isa.OP_CAP, rng.randrange(7), 0)
    return isa.encode(isa.OP_MISC, 0, 0)


def core_matches_iss(core, iss) -> tuple[bool, str]:
    pairs = [
        ("pc", int(core.pc.value), iss.pc),
        ("a", int(core.a.value), iss.a),
        ("x", int(core.x.value), iss.x),
        ("y", int(core.y.value), iss.y),
        ("z", int(core.z.value), iss.z),
        ("c", int(core.c.value), iss.c),
        ("n", int(core.n.value), iss.n),
        ("sp", int(core.sp.value), iss.sp),
        ("uo", int(core.uo_r.value), iss.uo),
        ("uio", int(core.uio_r.value), iss.uio),
        ("uio_oe", int(core.uio_oe_r.value), iss.uio_oe),
        ("uio_od", int(core.uio_od_r.value), iss.uio_od),
        ("timer", int(core.timer.value), iss.timer),
        ("wait", int(core.wait_active.value), int(iss.wait_active)),
        ("halt", int(core.halt.value), int(iss.halt)),
        ("cap_count", int(core.u_capture.count.value), iss.cap_count),
    ]
    for name, rtl, model in pairs:
        if rtl != model:
            return False, f"{name}: RTL={rtl} ISS={model}"
    return True, ""


@cocotb.test(skip=GATE_LEVEL)
async def test_timer_cosim(dut):
    """Directed timer program, compared to the ISS every enabled clock.

    RTL-only: reads core registers, which a flattened gate-level netlist does
    not preserve.
    """
    src = """
        TMR_CLR
        TMR_LO
        OUT UO, A
        TMR_HI
        OUT UO, A
        WAIT 20
        TMR_LO
        OUT UO, A
        TMR_HI
        OUT UO, A
        WAIT 255
        WAIT 20
        TMR_LO
        OUT UO, A
        TMR_HI
        OUT UO, A
        HALT
    """
    image = assemble(src)
    await reset_dut(dut)
    await load_image(dut, image, verify=False, settle=0)

    core = dut.user_project.u_core
    iss = ProteusISS(image.program, image.data)

    aligned = False
    for _ in range(16):
        await RisingEdge(dut.clk)
        if int(core.pc.value) != 0:
            iss.step(ui=0x80, uio=0x0C)
            ok, why = core_matches_iss(core, iss)
            assert ok, f"timer alignment mismatch: {why}"
            aligned = True
            break
    assert aligned, "core never started the timer program"

    for cycle in range(400):
        await RisingEdge(dut.clk)
        iss.step(ui=0x80, uio=0x0C)
        ok, why = core_matches_iss(core, iss)
        assert ok, f"timer mismatch at cycle {cycle}: {why}"

    assert iss.timer >= 270, f"timer only reached {iss.timer}"


@cocotb.test(skip=GATE_LEVEL)
async def test_opcode_sweep(dut):
    """Run every opcode/subop encoding and compare RTL to the ISS.

    RTL-only: the comparison reads architectural registers inside the core.
    """
    nop = isa.encode(isa.OP_MISC, 0, 0)
    for op in range(12):
        for sub in range(8):
            image = Image()
            image.program = {
                0: nop,
                1: isa.encode(isa.OP_LOAD, 0, 0xA5),
                2: isa.encode(isa.OP_LOAD, 1, 0x3C),
                3: isa.encode(isa.OP_LOAD, 2, 0x81),
                4: isa.encode(op, sub, 0x05),
                5: isa.encode(isa.OP_TIME, 7, 0),  # HALT
            }
            image.max_program = 6
            image.max_data = 0

            await reset_dut(dut)
            await load_image(dut, image, verify=False, settle=0)

            core = dut.user_project.u_core
            iss = ProteusISS(image.program, image.data)
            aligned = False
            for _ in range(16):
                await RisingEdge(dut.clk)
                if int(core.pc.value) != 0:
                    iss.step(ui=0x80, uio=0x0C)
                    ok, why = core_matches_iss(core, iss)
                    assert ok, f"opcode {op}/{sub} alignment: {why}"
                    aligned = True
                    break
            assert aligned, f"opcode {op}/{sub} never started"

            for cycle in range(30):
                await RisingEdge(dut.clk)
                iss.step(ui=0x80, uio=0x0C)
                ok, why = core_matches_iss(core, iss)
                if not ok:
                    dut._log.error(
                        "opcode op=%d sub=%d instr=0x%04X cycle=%d: %s",
                        op, sub, isa.encode(op, sub, 0x05), cycle, why,
                    )
                    assert False, f"opcode {op}/{sub}: {why}"


@cocotb.test(skip=GATE_LEVEL)
async def test_random_cosim(dut):
    """Randomized lock-step comparison against the Python ISS.

    RTL-only: the comparison reads architectural registers inside the core.
    """
    import random

    rng = random.Random(0xC0DE)
    image = Image()
    image.program = {i: isa.encode(isa.OP_MISC, 0, 0) for i in range(128)}
    for i in range(1, 49):
        image.program[i] = random_instruction(rng)
    image.data = {i: 0 for i in range(64)}
    image.max_program = 128
    image.max_data = 64

    await reset_dut(dut)
    await load_image(dut, image, verify=False, settle=0)

    core = dut.user_project.u_core
    iss = ProteusISS(image.program, image.data)

    # Align on the first executed instruction (address 0 is a NOP, so PC=1).
    aligned = False
    for _ in range(32):
        await RisingEdge(dut.clk)
        if int(core.pc.value) != 0:
            iss.step(ui=0x80, uio=0x0C)
            ok, why = core_matches_iss(core, iss)
            assert ok, f"co-sim alignment mismatch: {why}"
            aligned = True
            break
    assert aligned, "core never started"

    for cycle in range(1000):
        prev_pc = iss.pc
        prev_instr = iss.prog[prev_pc]
        await RisingEdge(dut.clk)
        iss.step(ui=0x80, uio=0x0C)
        ok, why = core_matches_iss(core, iss)
        if not ok:
            dut._log.error(
                "mismatch cycle %d after pc=0x%02X instr=0x%04X (%s): %s",
                cycle, prev_pc, prev_instr,
                isa.disassemble(prev_instr, prev_pc).text, why,
            )
            assert False, f"co-sim mismatch at cycle {cycle}: {why}"


@cocotb.test()
async def test_pin_wait(dut):
    await reset_dut(dut)
    src = """
        OUT UO, 0x01
        WAIT_PIN1 UI, 0x01
        OUT UO, 0x02
        WAIT_PIN0 UI, 0x01
        OUT UO, 0x04
        HALT
    """
    image = assemble(src)
    await load_image(dut, image, verify=False)

    await wait_for_uo(dut, 0x01)
    dut.ui_in.value = ui_word(1, 0, 0, low=0x01)
    await wait_for_uo(dut, 0x02)
    dut.ui_in.value = ui_word(1, 0, 0, low=0x00)
    await wait_for_uo(dut, 0x04)
