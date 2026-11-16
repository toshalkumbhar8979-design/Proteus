#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Toshal Kumbhar
# SPDX-License-Identifier: Apache-2.0
"""Cycle-accurate Proteus-1 instruction-set simulator.

This is the golden model for RTL co-simulation. It models one enabled core
clock per step, including wait states, the free-running timer, and the capture
FIFO. It intentionally does not model the loader or the chip-level pin mux; the
testbench drives the core after run=1 and compares core-visible state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from proteus_isa import (
    ALU_NAMES,
    OP_ALU,
    OP_ALUX,
    OP_ALUY,
    OP_BIT,
    OP_BRANCH,
    OP_CAP,
    OP_CRC,
    OP_IO,
    OP_LOAD,
    OP_MISC,
    OP_SER,
    OP_SHIFT,
    OP_TIME,
    OP_TIMER,
    SIGNATURE,
)

MASK8 = 0xFF
MASK16 = 0xFFFF
PC_MASK = 0x7F  # 128-word program memory; PC is 7 bits


def crc16_byte(crc: int, byte: int) -> int:
    """One CRC-16/USB byte step: reflected 0xA001, init 0xFFFF, xorout on read."""
    crc ^= byte & 0xFF
    for _ in range(8):
        crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def crc5_bit(crc: int, bit: int) -> int:
    """One USB token CRC-5 bit step: reflected 0x14, init 0x1F."""
    mix = (crc & 1) ^ (bit & 1)
    crc >>= 1
    if mix:
        crc ^= 0x14
    return crc & 0x1F


@dataclass
class CaptureEntry:
    timestamp: int
    pins: int


class ProteusISS:
    def __init__(self, program: dict[int, int] | None = None, data: dict[int, int] | None = None):
        self.prog = [0] * 256
        self.data = [0] * 64
        if program:
            for addr, word in program.items():
                self.prog[addr & 0xFF] = word & 0xFFFF
        if data:
            for addr, byte in data.items():
                self.data[addr & 0x3F] = byte & 0xFF
        self.reset()

    def reset(self) -> None:
        self.a = 0
        self.x = 0
        self.y = 0
        self.pc = 0
        self.sp = 0
        self.stack = [0] * 8
        self.z = 0
        self.c = 0
        self.n = 0
        self.uo = 0
        self.uio = 0
        self.uio_oe = 0
        self.uio_od = 0
        self.timer = 0
        self.timer_hi = 0
        self.halt = False
        self.wait_active = False
        self.wait_cnt = 0
        self.wait_kind = 0
        self.wait_mask = 0
        self.wait_ref = 0
        self.cap_rd = 0
        self.cap_en = 0
        # 32 entries is the most the status byte can describe: full, empty, and a
        # six-bit count. Keep this in step with CAP_AW in proteus_capture.v.
        self.cap_depth = 32
        self.cap_mode = 0
        self.cap_mem: list[CaptureEntry] = [
            CaptureEntry(0, 0) for _ in range(self.cap_depth)
        ]
        self.cap_wr = 0
        self.cap_rd_ptr = 0
        self.cap_count = 0
        self.cap_last_pins = 0
        self.crc16 = 0xFFFF
        self.crc5 = 0x1F
        self.ser_shift = 0
        self.ser_bits = 0
        self.ser_ones = 0
        self.ser_level = 1
        self.ser_pend = 0
        self.ui = 0
        self.uio_in = 0
        self.cycles = 0

    # ------------------------------------------------------------------ helpers
    @property
    def pins(self) -> int:
        return ((self.uio_in & MASK8) << 8) | (self.ui & MASK8)

    @property
    def cap_status(self) -> int:
        full = 1 if self.cap_count >= self.cap_depth else 0
        empty = 1 if self.cap_count == 0 else 0
        return (full << 7) | (empty << 6) | (self.cap_count & 0x3F)

    def head(self) -> int:
        if self.cap_count == 0:
            return 0
        e = self.cap_mem[self.cap_rd_ptr]
        return ((e.timestamp & MASK8) << 16) | ((e.pins >> 8) & MASK8) << 8 | (e.pins & MASK8)

    def _set_flags(self, result: int, carry: int | None = None) -> None:
        self.z = 1 if (result & MASK8) == 0 else 0
        self.n = 1 if (result & 0x80) else 0
        if carry is not None:
            self.c = carry & 1

    # ------------------------------------------------------------------- execute
    def step(self, ui: int | None = None, uio: int | None = None) -> None:
        if ui is not None:
            self.ui = ui & MASK8
        if uio is not None:
            self.uio_in = uio & MASK8

        pins = self.pins
        old_timer = self.timer & MASK16
        instr = self.prog[self.pc & PC_MASK]
        op = (instr >> 11) & 0x1F
        sub = (instr >> 8) & 0x7
        imm = instr & 0xFF

        cpu_active = (not self.halt) and (not self.wait_active)
        cap_insn = cpu_active and op == OP_CAP
        cap_set_en = cap_insn and sub == 0
        cap_pop = cap_insn and sub == 1
        cap_clear = cap_insn and sub == 6
        cap_en_val = imm & 1

        head_before = self.head()
        status_before = self.cap_status

        data_write: tuple[int, int] | None = None
        clear_timer = False

        if self.halt:
            pass
        elif self.wait_active:
            if self.wait_kind == 0:
                if self.wait_cnt == 1:
                    self.wait_active = False
                    self.pc = (self.pc + 1) & PC_MASK
                else:
                    self.wait_cnt -= 1
            elif self.wait_kind == 1:
                if (self.ui & self.wait_mask) == 0:
                    self.wait_active = False
                    self.pc = (self.pc + 1) & PC_MASK
            elif self.wait_kind == 2:
                if (self.ui & self.wait_mask) == self.wait_mask:
                    self.wait_active = False
                    self.pc = (self.pc + 1) & PC_MASK
            elif self.wait_kind == 3:
                if (self.uio_in & self.wait_mask) == 0:
                    self.wait_active = False
                    self.pc = (self.pc + 1) & PC_MASK
            elif self.wait_kind == 4:
                if (self.uio_in & self.wait_mask) == self.wait_mask:
                    self.wait_active = False
                    self.pc = (self.pc + 1) & PC_MASK
            elif self.wait_kind == 5:
                if ((pins ^ self.wait_ref) & self.wait_mask) != 0:
                    self.wait_active = False
                    self.pc = (self.pc + 1) & PC_MASK
            elif self.wait_kind == 6:
                if ((pins ^ self.wait_ref) & (self.wait_mask << 8)) != 0:
                    self.wait_active = False
                    self.pc = (self.pc + 1) & PC_MASK
            else:
                self.wait_active = False
                self.pc = (self.pc + 1) & PC_MASK
        else:
            self.pc = (self.pc + 1) & PC_MASK

            if op in (OP_ALU, OP_ALUX, OP_ALUY):
                rhs = imm if op == OP_ALU else (self.x if op == OP_ALUX else self.y)
                cin = self.c if sub in (1, 3) else 0
                if sub in (0, 1):
                    res = self.a + rhs + cin
                    self.a = res & MASK8
                    self._set_flags(self.a, (res >> 8) & 1)
                elif sub in (2, 3):
                    res = (self.a - rhs - cin) & 0x1FF
                    self.a = res & MASK8
                    self._set_flags(self.a, (res >> 8) & 1)
                elif sub == 4:
                    self.a = self.a & rhs
                    self._set_flags(self.a, 0)
                elif sub == 5:
                    self.a = self.a | rhs
                    self._set_flags(self.a, 0)
                elif sub == 6:
                    self.a = self.a ^ rhs
                    self._set_flags(self.a, 0)
                elif sub == 7:
                    res = (self.a - rhs) & 0x1FF
                    self._set_flags(res & MASK8, (res >> 8) & 1)

            elif op == OP_SHIFT:
                if sub == 0:
                    carry = (self.a >> 7) & 1
                    self.a = (self.a << 1) & MASK8
                    self._set_flags(self.a, carry)
                elif sub == 1:
                    carry = self.a & 1
                    self.a = (self.a >> 1) & MASK8
                    self._set_flags(self.a, carry)
                elif sub == 2:
                    carry = (self.a >> 7) & 1
                    self.a = ((self.a << 1) | self.c) & MASK8
                    self._set_flags(self.a, carry)
                elif sub == 3:
                    carry = self.a & 1
                    self.a = ((self.a >> 1) | (self.c << 7)) & MASK8
                    self._set_flags(self.a, carry)
                elif sub == 4:
                    carry = self.a & 1
                    self.a = ((self.a >> 1) | (self.a & 0x80)) & MASK8
                    self._set_flags(self.a, carry)
                elif sub == 5:
                    self.a = ((self.a & 0x0F) << 4) | ((self.a >> 4) & 0x0F)
                    self._set_flags(self.a)
                elif sub == 6:
                    self.a = (self.a + 1) & MASK8
                    self._set_flags(self.a)
                elif sub == 7:
                    self.a = (self.a - 1) & MASK8
                    self._set_flags(self.a)

            elif op == OP_LOAD:
                if sub == 0:
                    self.a = imm
                elif sub == 1:
                    self.x = imm
                elif sub == 2:
                    self.y = imm
                elif sub == 3:
                    self.a = self.data[self.x & 0x3F]
                elif sub == 4:
                    data_write = (self.x & 0x3F, self.a)
                elif sub == 5:
                    self.a = self.data[imm & 0x3F]
                elif sub == 6:
                    data_write = (imm & 0x3F, self.a)
                elif sub == 7:
                    code = imm & 0x7
                    if code == 0:
                        self.a = self.x
                    elif code == 1:
                        self.x = self.a
                    elif code == 2:
                        self.a = self.y
                    elif code == 3:
                        self.y = self.a
                    elif code == 4:
                        self.x = self.y
                    elif code == 5:
                        self.y = self.x

            elif op == OP_IO:
                if sub == 0:
                    self.uo = self.a
                elif sub == 1:
                    self.uio = self.a
                elif sub == 2:
                    self.uio_oe = self.a
                elif sub == 3:
                    self.uio_od = self.a
                elif sub == 4:
                    self.a = self.ui
                elif sub == 5:
                    self.a = self.uio_in
                elif sub == 6:
                    self.uo = imm
                elif sub == 7:
                    self.uio = imm

            elif op == OP_BRANCH:
                if sub == 0:
                    self.pc = imm & PC_MASK
                elif sub == 1:
                    if self.z:
                        self.pc = imm & PC_MASK
                elif sub == 2:
                    if not self.z:
                        self.pc = imm & PC_MASK
                elif sub == 3:
                    if self.c:
                        self.pc = imm & PC_MASK
                elif sub == 4:
                    if not self.c:
                        self.pc = imm & PC_MASK
                elif sub == 5:
                    self.stack[self.sp] = (self.pc) & MASK8
                    self.sp = (self.sp + 1) & 0x7
                    self.pc = imm & PC_MASK
                elif sub == 6:
                    self.sp = (self.sp - 1) & 0x7
                    self.pc = self.stack[self.sp] & PC_MASK
                elif sub == 7:
                    old_y = self.y
                    self.y = (self.y - 1) & MASK8
                    self.z = 1 if self.y == 0 else 0
                    self.n = (self.y >> 7) & 1
                    if old_y != 1:
                        self.pc = imm & PC_MASK

            elif op == OP_TIME:
                if sub == 0:
                    n = 256 if imm == 0 else imm
                    if n != 1:
                        self.wait_cnt = n - 1
                        self.wait_kind = 0
                        self.wait_active = True
                        self.pc = (self.pc - 1) & PC_MASK
                elif sub in (1, 2, 3, 4):
                    self.wait_kind = sub
                    self.wait_mask = imm
                    cond = False
                    if sub == 1:
                        cond = (self.ui & imm) == 0
                    elif sub == 2:
                        cond = (self.ui & imm) == imm
                    elif sub == 3:
                        cond = (self.uio_in & imm) == 0
                    else:
                        cond = (self.uio_in & imm) == imm
                    if not cond:
                        self.wait_active = True
                        self.pc = (self.pc - 1) & PC_MASK
                elif sub in (5, 6):
                    self.wait_ref = pins
                    self.wait_kind = sub
                    self.wait_mask = imm
                    self.wait_active = True
                    self.pc = (self.pc - 1) & PC_MASK
                elif sub == 7:
                    self.halt = True
                    self.pc = (self.pc - 1) & PC_MASK

            elif op == OP_BIT:
                if sub == 0:
                    self.uo |= imm
                elif sub == 1:
                    self.uo &= ~imm & MASK8
                elif sub == 2:
                    self.uo ^= imm
                elif sub == 3:
                    self.uio |= imm
                elif sub == 4:
                    self.uio &= ~imm & MASK8
                elif sub == 5:
                    self.uio ^= imm
                elif sub == 6:
                    self.uio_oe |= imm
                elif sub == 7:
                    self.uio_oe &= ~imm & MASK8

            elif op == OP_MISC:
                if sub == 1:
                    self.x = (self.x + 1) & MASK8
                    self.z = 1 if self.x == 0 else 0
                    self.n = (self.x >> 7) & 1
                elif sub == 2:
                    self.x = (self.x - 1) & MASK8
                    self.z = 1 if self.x == 0 else 0
                    self.n = (self.x >> 7) & 1
                elif sub == 3:
                    self.y = (self.y + 1) & MASK8
                    self.z = 1 if self.y == 0 else 0
                    self.n = (self.y >> 7) & 1
                elif sub == 4:
                    self.y = (self.y - 1) & MASK8
                    self.z = 1 if self.y == 0 else 0
                    self.n = (self.y >> 7) & 1
                elif sub == 5:
                    self.a = self.x
                elif sub == 6:
                    self.x = self.a
                elif sub == 7:
                    self.y = self.a

            elif op == OP_TIMER:
                if sub == 0:
                    self.a = self.timer & MASK8
                    self.timer_hi = (self.timer >> 8) & MASK8
                elif sub == 1:
                    self.a = self.timer_hi
                elif sub == 2:
                    clear_timer = True
                    self.timer_hi = 0
                elif sub == 7:
                    self.a = SIGNATURE

            elif op == OP_CAP:
                if sub == 0:
                    pass
                elif sub == 1:
                    self.cap_rd = head_before
                elif sub == 2:
                    self.a = self.cap_rd & MASK8
                elif sub == 3:
                    self.a = (self.cap_rd >> 8) & MASK8
                elif sub == 4:
                    self.a = (self.cap_rd >> 16) & MASK8
                elif sub == 5:
                    self.a = status_before
                elif sub == 6:
                    self.cap_rd = 0

            elif op == OP_CRC:
                if sub == 0:
                    self.crc16 = 0xFFFF
                elif sub == 1:
                    self.crc16 = crc16_byte(self.crc16, self.a)
                elif sub == 2:
                    v = (self.crc16 & 0xFF) ^ 0xFF
                    self.a = v
                    self.z = 1 if v == 0 else 0
                    self.n = (v >> 7) & 1
                elif sub == 3:
                    v = ((self.crc16 >> 8) & 0xFF) ^ 0xFF
                    self.a = v
                    self.z = 1 if v == 0 else 0
                    self.n = (v >> 7) & 1
                elif sub == 4:
                    self.crc5 = 0x1F
                elif sub == 5:
                    self.crc5 = crc5_bit(self.crc5, imm & 1)
                elif sub == 6:
                    v = (self.crc5 ^ 0x1F) & 0xFF
                    self.a = v
                    self.z = 1 if v == 0 else 0
                    self.n = (v >> 7) & 1

            elif op == OP_SER:
                if sub == 0:
                    self.ser_shift = self.a & 0xFF
                    self.ser_bits = 8
                    self.ser_pend = 0
                elif sub == 1:
                    busy = self.ser_bits != 0 or self.ser_pend
                    nxt = (~self.ser_level) & 1 if self.ser_pend else (
                        self.ser_level if (self.ser_shift & 1) else (~self.ser_level) & 1
                    )
                    if self.ser_pend:
                        self.ser_level = nxt
                        self.ser_pend = 0
                        self.ser_ones = 0
                        self.a = nxt
                    elif self.ser_bits != 0:
                        bit = self.ser_shift & 1
                        self.ser_shift = (self.ser_shift >> 1) & 0xFF
                        self.ser_bits -= 1
                        self.ser_level = nxt
                        self.a = nxt
                        if bit:
                            self.ser_ones += 1
                            if self.ser_ones == 6:
                                self.ser_pend = 1
                                self.ser_ones = 0
                        else:
                            self.ser_ones = 0
                    else:
                        self.a = self.ser_level
                elif sub == 2:
                    self.a = self.ser_level & 1
                elif sub == 3:
                    busy = 1 if (self.ser_bits != 0 or self.ser_pend) else 0
                    self.a = busy
                    self.z = 1 if busy == 0 else 0
                    self.n = 0
                elif sub == 4:
                    self.a = self.ser_ones & 0xFF
                elif sub == 5:
                    self.ser_level = imm & 1
                    self.ser_pend = 0
                    self.ser_ones = 0

        # ---- data memory write lands at the end of the tick ----
        if data_write is not None:
            addr, value = data_write
            self.data[addr] = value & MASK8

        # ---- capture FIFO update (same edge as the CPU) ----
        enabling = cap_set_en and bool(cap_en_val) and not self.cap_en
        if cap_clear:
            self.cap_wr = 0
            self.cap_rd_ptr = 0
            self.cap_count = 0
            self.cap_last_pins = 0
            # cap_en is not changed by CAP_CLR
        else:
            if cap_set_en:
                self.cap_en = 1 if cap_en_val else 0
                self.cap_mode = 1 if (imm >> 1) & 1 else 0

            pushing = self.cap_en and (not enabling) and (pins != self.cap_last_pins)
            if enabling:
                self.cap_last_pins = pins
            elif pushing:
                self.cap_last_pins = pins

            full = self.cap_count >= self.cap_depth
            # FIFO mode drops a new event when full; roll mode overwrites the
            # oldest entry so the last cap_depth events survive.
            push_ok = pushing and (not full or bool(self.cap_mode))
            drop = push_ok and full
            pop_ok = cap_pop and self.cap_count > 0
            if push_ok:
                self.cap_mem[self.cap_wr] = CaptureEntry(old_timer & MASK8, pins)
                self.cap_wr = (self.cap_wr + 1) % self.cap_depth
            if pop_ok or drop:
                self.cap_rd_ptr = (self.cap_rd_ptr + 1) % self.cap_depth
            if push_ok and not pop_ok and not drop:
                self.cap_count += 1
            elif pop_ok and not push_ok:
                self.cap_count -= 1

        # ---- timer: reads see the pre-increment value; TMR_CLR wins ----
        if clear_timer:
            self.timer = 0
        else:
            self.timer = (self.timer + 1) & MASK16

        self.cycles += 1

    # -------------------------------------------------------------------- batch
    def run(self, cycles: int, ui: int | None = None, uio: int | None = None) -> None:
        for _ in range(cycles):
            self.step(ui, uio)

    def snapshot(self) -> dict:
        return {
            "cycles": self.cycles,
            "pc": self.pc,
            "a": self.a,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "c": self.c,
            "n": self.n,
            "sp": self.sp,
            "uo": self.uo,
            "uio": self.uio,
            "uio_oe": self.uio_oe,
            "uio_od": self.uio_od,
            "timer": self.timer,
            "halt": int(self.halt),
            "wait_active": int(self.wait_active),
            "cap_count": self.cap_count,
        }

    @classmethod
    def from_json(cls, path: str | Path) -> "ProteusISS":
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        program = {int(a): int(w) for a, w in doc.get("program", [])}
        data = {int(a): int(b) for a, b in doc.get("data", [])}
        return cls(program, data)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Proteus-1 ISS")
    ap.add_argument("image", type=Path)
    ap.add_argument("--cycles", type=int, default=100)
    ap.add_argument("--ui", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--uio", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--trace", action="store_true")
    args = ap.parse_args()
    iss = ProteusISS.from_json(args.image)
    for _ in range(args.cycles):
        if args.trace:
            from proteus_isa import disassemble

            print(f"{iss.cycles:04d} pc={iss.pc:02X} A={iss.a:02X} X={iss.x:02X} Y={iss.y:02X} "
                  f"uo={iss.uo:02X} uio={iss.uio:02X} :: {disassemble(iss.prog[iss.pc], iss.pc).text}")
        iss.step(args.ui, args.uio)
        if iss.halt:
            break
    print(iss.snapshot())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
