"""Proteus-1 ISA definitions shared by the assembler and ISS.

Keep this table in lock-step with docs/isa.md and src/proteus_core.v.
"""

from __future__ import annotations

from dataclasses import dataclass

# Major opcodes.
OP_ALU = 0
OP_SHIFT = 1
OP_LOAD = 2
OP_IO = 3
OP_BRANCH = 4
OP_TIME = 5
OP_BIT = 6
OP_MISC = 7
OP_ALUX = 8
OP_ALUY = 9
OP_TIMER = 10
OP_CAP = 11

OPCODE_NAMES = {
    OP_ALU: "ALU",
    OP_SHIFT: "SHIFT",
    OP_LOAD: "LOAD",
    OP_IO: "IO",
    OP_BRANCH: "BRANCH",
    OP_TIME: "TIME",
    OP_BIT: "BIT",
    OP_MISC: "MISC",
    OP_ALUX: "ALUX",
    OP_ALUY: "ALUY",
    OP_TIMER: "TIMER",
    OP_CAP: "CAP",
}

ALU_NAMES = ["ADD", "ADC", "SUB", "SBC", "AND", "OR", "XOR", "CMP"]
SHIFT_NAMES = ["SHL", "SHR", "ROL", "ROR", "ASR", "SWAP", "INC A", "DEC A"]

TFR_CODES = {
    ("A", "X"): 0,
    ("X", "A"): 1,
    ("A", "Y"): 2,
    ("Y", "A"): 3,
    ("X", "Y"): 4,
    ("Y", "X"): 5,
}

TFR_NAMES = {v: k for k, v in TFR_CODES.items()}

SIGNATURE = 0xA1


def encode(op: int, sub: int, imm: int = 0) -> int:
    """Encode a 16-bit instruction. Raises on out-of-range fields."""
    if not 0 <= op <= 0x1F:
        raise ValueError(f"opcode out of range: {op}")
    if not 0 <= sub <= 0x7:
        raise ValueError(f"subop out of range: {sub}")
    if not 0 <= imm <= 0xFF:
        raise ValueError(f"immediate out of range: {imm}")
    return ((op & 0x1F) << 11) | ((sub & 0x7) << 8) | (imm & 0xFF)


@dataclass(frozen=True)
class Decoded:
    op: int
    sub: int
    imm: int
    text: str


def _hex(v: int) -> str:
    return f"0x{v:02X}"


def disassemble(word: int, pc: int | None = None) -> Decoded:
    """Decode one instruction into a human-readable line."""
    word &= 0xFFFF
    op = (word >> 11) & 0x1F
    sub = (word >> 8) & 0x7
    imm = word & 0xFF
    prefix = f"{pc:02X}: " if pc is not None else ""

    if op in (OP_ALU, OP_ALUX, OP_ALUY):
        name = ALU_NAMES[sub]
        if op == OP_ALU:
            text = f"{name} A, {_hex(imm)}"
        elif op == OP_ALUX:
            text = f"{name} A, X"
        else:
            text = f"{name} A, Y"
    elif op == OP_SHIFT:
        text = SHIFT_NAMES[sub]
    elif op == OP_LOAD:
        if sub == 0:
            text = f"LDI A, {_hex(imm)}"
        elif sub == 1:
            text = f"LDI X, {_hex(imm)}"
        elif sub == 2:
            text = f"LDI Y, {_hex(imm)}"
        elif sub == 3:
            text = "LD A, (X)"
        elif sub == 4:
            text = "ST (X), A"
        elif sub == 5:
            text = f"LD A, ({_hex(imm)})"
        elif sub == 6:
            text = f"ST ({_hex(imm)}), A"
        else:
            pair = TFR_NAMES.get(imm & 0x7)
            text = f"TFR {pair[0]}, {pair[1]}" if pair else f"TFR {imm & 0x7} ; reserved"
    elif op == OP_IO:
        io = {
            0: "OUT UO, A",
            1: "OUT UIO, A",
            2: "OUT UIO_OE, A",
            3: "OUT UIO_OD, A",
            4: "IN UI",
            5: "IN UIO",
            6: f"OUT UO, {_hex(imm)}",
            7: f"OUT UIO, {_hex(imm)}",
        }[sub]
        text = io
    elif op == OP_BRANCH:
        branch = {
            0: f"JMP {_hex(imm)}",
            1: f"JZ {_hex(imm)}",
            2: f"JNZ {_hex(imm)}",
            3: f"JC {_hex(imm)}",
            4: f"JNC {_hex(imm)}",
            5: f"CALL {_hex(imm)}",
            6: "RET",
            7: f"DJNZ Y, {_hex(imm)}",
        }[sub]
        text = branch
    elif op == OP_TIME:
        time_ops = {
            0: f"WAIT {_hex(imm)}",
            1: f"WAIT_PIN0 UI, {_hex(imm)}",
            2: f"WAIT_PIN1 UI, {_hex(imm)}",
            3: f"WAIT_PIN0 UIO, {_hex(imm)}",
            4: f"WAIT_PIN1 UIO, {_hex(imm)}",
            5: f"WAIT_EDGE UI, {_hex(imm)}",
            6: f"WAIT_EDGE UIO, {_hex(imm)}",
            7: "HALT",
        }[sub]
        text = time_ops
    elif op == OP_BIT:
        bit_ops = {
            0: f"SETB UO, {_hex(imm)}",
            1: f"CLRB UO, {_hex(imm)}",
            2: f"TGLB UO, {_hex(imm)}",
            3: f"SETB UIO, {_hex(imm)}",
            4: f"CLRB UIO, {_hex(imm)}",
            5: f"TGLB UIO, {_hex(imm)}",
            6: f"SETB UIO_OE, {_hex(imm)}",
            7: f"CLRB UIO_OE, {_hex(imm)}",
        }[sub]
        text = bit_ops
    elif op == OP_MISC:
        misc = {
            0: "NOP",
            1: "INC X",
            2: "DEC X",
            3: "INC Y",
            4: "DEC Y",
            5: "A = X",
            6: "X = A",
            7: "Y = A",
        }[sub]
        text = misc
    elif op == OP_TIMER:
        timer_ops = {
            0: "TMR_LO",
            1: "TMR_HI",
            2: "TMR_CLR",
            3: ".word ; reserved TIMER 3",
            4: ".word ; reserved TIMER 4",
            5: ".word ; reserved TIMER 5",
            6: ".word ; reserved TIMER 6",
            7: "ID",
        }[sub]
        text = timer_ops
    elif op == OP_CAP:
        cap_ops = {
            0: f"CAP_EN {_hex(imm)}",
            1: "CAP_POP",
            2: "CAP_UI",
            3: "CAP_UIO",
            4: "CAP_TS",
            5: "CAP_STATUS",
            6: "CAP_CLR",
            7: ".word ; reserved CAP 7",
        }[sub]
        text = cap_ops
    else:
        text = f".word 0x{word:04X} ; reserved opcode"

    return Decoded(op, sub, imm, prefix + text)


def decode(word: int) -> tuple[int, int, int]:
    word &= 0xFFFF
    return ((word >> 11) & 0x1F, (word >> 8) & 0x7, word & 0xFF)
