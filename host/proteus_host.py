#!/usr/bin/env python3
"""Proteus-1 host loader.

MicroPython for the RP2350 on the Tiny Tapeout demo board, or any board that
exposes four GPIOs. It speaks the loader frame format directly:

    32 bits, MSB first: {command[7:0], address[7:0], data[15:0]}

Wiring (defaults, change to match your board):

    host GPIO 0 -> CFG_CS_N   (chip ui_in[7])
    host GPIO 1 -> CFG_SCK    (chip ui_in[6])
    host GPIO 2 -> CFG_MOSI   (chip ui_in[5])
    host GPIO 3 <- CFG_MISO   (chip uo_out[7])
    host GND    -> chip GND

The loader runs at 100 kHz by default, well below the chip's clk/4 limit.
Program memory powers up undefined, so load_image() writes NOP to every unused
program word and zero to every unused data byte before writing the image.

Usage:
    import proteus_host
    host = proteus_host.ProteusHost(cs=0, sck=1, mosi=2, miso=3)
    host.load_file("uart_tx.json")
    host.control(1)
"""

from machine import Pin
import json
import sys
import time

PROG_WORDS = 128
DATA_BYTES = 64
NOP = 0x0000

CMD_NOP = 0x00
CMD_WRITE_PROG = 0x01
CMD_WRITE_DATA = 0x02
CMD_CONTROL = 0x03
CMD_READ_PROG = 0x04


class ProteusHost:
    def __init__(self, cs, sck, mosi, miso, half_period_us=5):
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.sck = Pin(sck, Pin.OUT, value=0)
        self.mosi = Pin(mosi, Pin.OUT, value=0)
        self.miso = Pin(miso, Pin.IN, Pin.PULL_DOWN)
        self.half = half_period_us

    # ------------------------------------------------------------------ framing
    def _frame(self, command, address, data):
        """Shift one 32-bit frame and return the 32 MISO bits.

        The loader updates MISO on the rising SCK edge, so the host samples
        MISO just before each rising edge and changes MOSI after sampling.
        This is the mode-0 relationship with the sample point on the falling
        side, which the pipelined readback requires.
        """
        word = ((command & 0xFF) << 24) | ((address & 0xFF) << 16) | (data & 0xFFFF)

        self.cs.value(0)
        time.sleep_us(self.half)  # let the two-flop CS synchronizer settle

        rx = 0
        for i in range(32):
            rx = (rx << 1) | self.miso.value()
            self.mosi.value((word >> (31 - i)) & 1)
            time.sleep_us(self.half)
            self.sck.value(1)
            time.sleep_us(self.half)
            self.sck.value(0)

        self.cs.value(1)
        time.sleep_us(self.half)
        return rx

    # ----------------------------------------------------------------- commands
    def control(self, run):
        self._frame(CMD_CONTROL, 0, 1 if run else 0)

    def write_program(self, address, word):
        self._frame(CMD_WRITE_PROG, address, word)

    def write_data(self, address, byte):
        self._frame(CMD_WRITE_DATA, address, byte & 0xFF)

    def read_program(self, address):
        """Pipelined readback: command frame, then a dummy frame shifts it out."""
        self._frame(CMD_READ_PROG, address, 0)
        rx = self._frame(CMD_NOP, 0, 0)
        return (rx >> 16) & 0xFFFF

    # -------------------------------------------------------------------- image
    def load_image(self, doc, verify=True):
        """Load an assembler JSON image: {'program': [[addr, word], ...], ...}."""
        program = {int(a): int(w) & 0xFFFF for a, w in doc.get("program", [])}
        data = {int(a): int(b) & 0xFF for a, b in doc.get("data", [])}

        self.control(0)
        for address in range(PROG_WORDS):
            self.write_program(address, program.get(address, NOP))
        for address in range(DATA_BYTES):
            self.write_data(address, data.get(address, 0))

        if verify:
            # Verify the whole memory, including the NOP fill. A failed write to
            # an unused word would otherwise be invisible until the CPU ran off
            # the end of the loaded image.
            for address in range(PROG_WORDS):
                expected = program.get(address, NOP)
                got = self.read_program(address)
                if got != expected:
                    raise ValueError(
                        "verify failed at 0x%02X: wrote 0x%04X, read 0x%04X"
                        % (address, expected, got)
                    )

    def load_file(self, path, verify=True):
        with open(path, "r") as handle:
            doc = json.load(handle)
        self.load_image(doc, verify=verify)


def _usage():
    print("usage: proteus_host.py IMAGE.json [--no-run] [--no-verify]")
    print("       [--cs PIN] [--sck PIN] [--mosi PIN] [--miso PIN]")
    print("Defaults: cs=0 sck=1 mosi=2 miso=3, 100 kHz, run after load.")


def main():
    args = sys.argv[1:]
    if not args:
        _usage()
        return 1

    path = args[0]
    pins = {"cs": 0, "sck": 1, "mosi": 2, "miso": 3}
    run = True
    verify = True

    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "--no-run":
            run = False
        elif arg == "--no-verify":
            verify = False
        elif arg.startswith("--") and arg[2:] in pins and i + 1 < len(args):
            pins[arg[2:]] = int(args[i + 1], 0)
            i += 1
        else:
            print("unknown argument: %s" % arg)
            _usage()
            return 1
        i += 1

    host = ProteusHost(pins["cs"], pins["sck"], pins["mosi"], pins["miso"])
    host.load_file(path, verify=verify)
    if run:
        host.control(1)
    print("loaded %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
