#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Toshal Kumbhar
# SPDX-License-Identifier: Apache-2.0
"""Proteus-1 assembler.

Two passes:
  1. resolve labels, .equ constants, and addresses;
  2. encode instructions and emit program/data images.

The output JSON is the canonical image used by the RTL testbench and host
loader. The Intel HEX file is a convenience for generic programmers; program
words are stored big-endian at byte address word*2, data bytes live at 0x8000.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from proteus_isa import (
    ALU_NAMES,
    OP_ALU,
    OP_ALUX,
    OP_ALUY,
    OP_BIT,
    OP_BRANCH,
    OP_CAP,
    OP_IO,
    OP_LOAD,
    OP_MISC,
    OP_SHIFT,
    OP_TIME,
    OP_TIMER,
    TFR_CODES,
    encode,
)

PROG_WORDS = 128
DATA_BYTES = 64


class AsmError(Exception):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


@dataclass
class Line:
    lineno: int
    source: str
    label: str | None
    op: str | None
    operands: list[str]


@dataclass
class Image:
    program: dict[int, int] = field(default_factory=dict)
    data: dict[int, int] = field(default_factory=dict)
    symbols: dict[str, int] = field(default_factory=dict)
    max_program: int = 0
    max_data: int = 0


LABEL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def strip_comment(line: str) -> str:
    out = []
    i = 0
    while i < len(line):
        if line[i] == ";":
            break
        if line[i : i + 2] == "//":
            break
        if line[i] == "#":
            break
        out.append(line[i])
        i += 1
    return "".join(out).strip()


def split_operands(text: str) -> list[str]:
    if not text.strip():
        return []
    return [p.strip() for p in text.split(",")]


def parse_lines(text: str) -> list[Line]:
    lines: list[Line] = []
    for n, raw in enumerate(text.splitlines(), 1):
        body = strip_comment(raw)
        if not body:
            lines.append(Line(n, raw.rstrip(), None, None, []))
            continue
        label = None
        m = LABEL_RE.match(body)
        if m:
            label = m.group(1)
            body = m.group(2).strip()
        if not body:
            lines.append(Line(n, raw.rstrip(), label, None, []))
            continue
        # Split the opcode from the operand text on the first whitespace.
        parts = body.split(None, 1)
        op = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        lines.append(Line(n, raw.rstrip(), label, op, split_operands(rest)))
    return lines


def eval_expr(text: str, symbols: dict[str, int], lineno: int) -> int:
    """Safe integer expression evaluator with symbol lookup."""
    text = text.strip()
    if not text:
        raise AsmError(lineno, "empty expression")
    try:
        node = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise AsmError(lineno, f"bad expression {text!r}: {exc.msg}") from None

    def walk(n: ast.AST) -> int:
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in symbols:
                raise AsmError(lineno, f"undefined symbol {n.id!r}")
            return symbols[n.id]
        if isinstance(n, ast.UnaryOp):
            v = walk(n.operand)
            if isinstance(n.op, ast.USub):
                return -v
            if isinstance(n.op, ast.UAdd):
                return v
            if isinstance(n.op, ast.Invert):
                return ~v
            raise AsmError(lineno, "unsupported unary operator")
        if isinstance(n, ast.BinOp):
            a = walk(n.left)
            b = walk(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, ast.FloorDiv):
                return a // b
            if isinstance(n.op, ast.Div):
                return a // b
            if isinstance(n.op, ast.Mod):
                return a % b
            if isinstance(n.op, ast.LShift):
                return a << b
            if isinstance(n.op, ast.RShift):
                return a >> b
            if isinstance(n.op, ast.BitAnd):
                return a & b
            if isinstance(n.op, ast.BitOr):
                return a | b
            if isinstance(n.op, ast.BitXor):
                return a ^ b
            raise AsmError(lineno, "unsupported binary operator")
        raise AsmError(lineno, "unsupported expression")

    return int(walk(node))


def check_range(value: int, lo: int, hi: int, what: str, lineno: int) -> int:
    if not lo <= value <= hi:
        raise AsmError(lineno, f"{what} {value} outside {lo}..{hi}")
    return value


def parse_port(token: str, lineno: int) -> str:
    p = token.strip().upper()
    if p not in {"UO", "UIO", "UIO_OE", "UIO_OD", "UI"}:
        raise AsmError(lineno, f"unknown port {token!r}")
    return p


def parse_reg(token: str, lineno: int) -> str:
    r = token.strip().upper()
    if r not in {"A", "X", "Y"}:
        raise AsmError(lineno, f"unknown register {token!r}")
    return r


def encode_instruction(op: str, args: list[str], symbols: dict[str, int], lineno: int) -> int:
    """Encode one assembly instruction into a 16-bit word."""
    m = op.upper()

    def expr(i: int) -> int:
        if i >= len(args):
            raise AsmError(lineno, f"{m} is missing operand {i + 1}")
        return check_range(eval_expr(args[i], symbols, lineno), 0, 255, "immediate", lineno)

    def want(n: int) -> None:
        if len(args) != n:
            raise AsmError(lineno, f"{m} expects {n} operand(s), got {len(args)}")

    # Arithmetic/logic, register or immediate second operand.
    if m in ALU_NAMES:
        want(2)
        if parse_reg(args[0], lineno) != "A":
            raise AsmError(lineno, f"{m} destination must be A")
        sub = ALU_NAMES.index(m)
        rhs = args[1].strip().upper()
        if rhs == "X":
            return encode(OP_ALUX, sub, 0)
        if rhs == "Y":
            return encode(OP_ALUY, sub, 0)
        return encode(OP_ALU, sub, expr(1))

    if m in {"SHL", "SHR", "ROL", "ROR", "ASR", "SWAP"}:
        want(1)
        if parse_reg(args[0], lineno) != "A":
            raise AsmError(lineno, f"{m} operand must be A")
        return encode(OP_SHIFT, ["SHL", "SHR", "ROL", "ROR", "ASR", "SWAP"].index(m), 0)

    if m in {"INC", "DEC"}:
        want(1)
        r = parse_reg(args[0], lineno)
        if r == "A":
            return encode(OP_SHIFT, 6 if m == "INC" else 7, 0)
        if r == "X":
            return encode(OP_MISC, 1 if m == "INC" else 2, 0)
        return encode(OP_MISC, 3 if m == "INC" else 4, 0)

    if m == "LDI":
        want(2)
        r = parse_reg(args[0], lineno)
        sub = {"A": 0, "X": 1, "Y": 2}[r]
        return encode(OP_LOAD, sub, expr(1))

    if m == "LD":
        want(2)
        if parse_reg(args[0], lineno) != "A":
            raise AsmError(lineno, "LD supports A only")
        src = args[1].strip()
        if src.upper() == "(X)":
            return encode(OP_LOAD, 3, 0)
        if src.startswith("(") and src.endswith(")"):
            return encode(OP_LOAD, 5, check_range(eval_expr(src[1:-1], symbols, lineno), 0, 63, "data address", lineno))
        raise AsmError(lineno, "LD source must be (X) or (address)")

    if m == "ST":
        want(2)
        dst = args[0].strip()
        if parse_reg(args[1], lineno) != "A":
            raise AsmError(lineno, "ST source must be A")
        if dst.upper() == "(X)":
            return encode(OP_LOAD, 4, 0)
        if dst.startswith("(") and dst.endswith(")"):
            return encode(OP_LOAD, 6, check_range(eval_expr(dst[1:-1], symbols, lineno), 0, 63, "data address", lineno))
        raise AsmError(lineno, "ST destination must be (X) or (address)")

    if m in {"TFR", "MOV"}:
        if len(args) == 1:
            return encode(OP_LOAD, 7, check_range(eval_expr(args[0], symbols, lineno), 0, 7, "TFR code", lineno))
        want(2)
        pair = (parse_reg(args[0], lineno), parse_reg(args[1], lineno))
        if pair not in TFR_CODES:
            raise AsmError(lineno, f"unsupported transfer {pair[0]},{pair[1]}")
        return encode(OP_LOAD, 7, TFR_CODES[pair])

    if m == "OUT":
        want(2)
        port = parse_port(args[0], lineno)
        rhs = args[1].strip()
        if rhs.upper() == "A":
            if port == "UO":
                return encode(OP_IO, 0, 0)
            if port == "UIO":
                return encode(OP_IO, 1, 0)
            if port == "UIO_OE":
                return encode(OP_IO, 2, 0)
            if port == "UIO_OD":
                return encode(OP_IO, 3, 0)
            raise AsmError(lineno, f"OUT {port} does not accept A")
        if port == "UO":
            return encode(OP_IO, 6, expr(1))
        if port == "UIO":
            return encode(OP_IO, 7, expr(1))
        raise AsmError(lineno, f"OUT {port} requires A")

    if m == "IN":
        want(1)
        port = parse_port(args[0], lineno)
        if port == "UI":
            return encode(OP_IO, 4, 0)
        if port == "UIO":
            return encode(OP_IO, 5, 0)
        raise AsmError(lineno, "IN supports UI and UIO only")

    if m in {"JMP", "JZ", "JNZ", "JC", "JNC", "CALL"}:
        want(1)
        return encode(OP_BRANCH, ["JMP", "JZ", "JNZ", "JC", "JNC", "CALL"].index(m), expr(0))

    if m == "RET":
        want(0)
        return encode(OP_BRANCH, 6, 0)

    if m == "DJNZ":
        want(2)
        if parse_reg(args[0], lineno) != "Y":
            raise AsmError(lineno, "DJNZ counts Y")
        return encode(OP_BRANCH, 7, expr(1))

    if m == "WAIT":
        want(1)
        return encode(OP_TIME, 0, expr(0))

    if m in {"WAIT_PIN0", "WAIT_PIN1"}:
        want(2)
        port = parse_port(args[0], lineno)
        sub = {"UI": 1, "UIO": 3}[port] + (1 if m == "WAIT_PIN1" else 0)
        return encode(OP_TIME, sub, expr(1))

    if m == "WAIT_EDGE":
        want(2)
        port = parse_port(args[0], lineno)
        if port not in {"UI", "UIO"}:
            raise AsmError(lineno, "WAIT_EDGE supports UI and UIO")
        return encode(OP_TIME, 5 if port == "UI" else 6, expr(1))

    if m == "HALT":
        want(0)
        return encode(OP_TIME, 7, 0)

    if m in {"SETB", "CLRB", "TGLB"}:
        want(2)
        port = parse_port(args[0], lineno)
        if port == "UO":
            sub = {"SETB": 0, "CLRB": 1, "TGLB": 2}[m]
        elif port == "UIO":
            sub = {"SETB": 3, "CLRB": 4, "TGLB": 5}[m]
        elif port == "UIO_OE" and m in {"SETB", "CLRB"}:
            sub = 6 if m == "SETB" else 7
        else:
            raise AsmError(lineno, f"{m} {port} is not supported")
        return encode(OP_BIT, sub, expr(1))

    if m == "NOP":
        want(0)
        return encode(OP_MISC, 0, 0)

    if m == "TMR_LO":
        want(0)
        return encode(OP_TIMER, 0, 0)
    if m == "TMR_HI":
        want(0)
        return encode(OP_TIMER, 1, 0)
    if m == "TMR_CLR":
        want(0)
        return encode(OP_TIMER, 2, 0)
    if m == "ID":
        want(0)
        return encode(OP_TIMER, 7, 0)

    cap_subs = {
        "CAP_EN": 0,
        "CAP_POP": 1,
        "CAP_UI": 2,
        "CAP_UIO": 3,
        "CAP_TS": 4,
        "CAP_STATUS": 5,
        "CAP_CLR": 6,
    }
    if m in cap_subs:
        if m == "CAP_EN":
            want(1)
            return encode(OP_CAP, 0, expr(0))
        want(0)
        return encode(OP_CAP, cap_subs[m], 0)

    raise AsmError(lineno, f"unknown mnemonic {op!r}")


def assemble(text: str, source_name: str = "<input>") -> Image:
    lines = parse_lines(text)
    image = Image()

    # ---------------- pass 1: addresses and symbols ----------------
    addr = 0
    daddr = 0
    section = "text"
    for line in lines:
        if line.label:
            if line.label in image.symbols:
                raise AsmError(line.lineno, f"duplicate symbol {line.label!r}")
            image.symbols[line.label] = daddr if section == "data" else addr
        if not line.op:
            continue
        op = line.op.lower()
        if op == ".equ":
            if len(line.operands) != 2 or not IDENT_RE.match(line.operands[0]):
                raise AsmError(line.lineno, ".equ NAME, value")
            name = line.operands[0]
            if name in image.symbols:
                raise AsmError(line.lineno, f"duplicate symbol {name!r}")
            image.symbols[name] = eval_expr(line.operands[1], image.symbols, line.lineno)
        elif op == ".org":
            if len(line.operands) != 1:
                raise AsmError(line.lineno, ".org address")
            v = eval_expr(line.operands[0], image.symbols, line.lineno)
            if section == "text":
                addr = check_range(v, 0, PROG_WORDS, ".org", line.lineno)
            else:
                daddr = check_range(v, 0, DATA_BYTES, ".org", line.lineno)
        elif op == ".data":
            if line.operands:
                raise AsmError(line.lineno, ".data takes no operands")
            section = "data"
        elif op == ".text":
            if line.operands:
                raise AsmError(line.lineno, ".text takes no operands")
            section = "text"
        elif op in {".byte", ".word", "db", "dw"}:
            if not line.operands:
                raise AsmError(line.lineno, f"{op} needs at least one value")
            if section == "text":
                addr += len(line.operands)
            else:
                daddr += len(line.operands) if op in {".byte", "db"} else 2 * len(line.operands)
        elif op == ".fill":
            if not (1 <= len(line.operands) <= 2):
                raise AsmError(line.lineno, ".fill count[, value]")
            count = eval_expr(line.operands[0], image.symbols, line.lineno)
            if count < 0:
                raise AsmError(line.lineno, ".fill count must be non-negative")
            if section == "text":
                addr += count
            else:
                daddr += count
        elif op == ".align":
            if len(line.operands) != 1:
                raise AsmError(line.lineno, ".align n")
            n = eval_expr(line.operands[0], image.symbols, line.lineno)
            if n <= 0:
                raise AsmError(line.lineno, ".align needs a positive power of two")
            if section == "text":
                addr = ((addr + n - 1) // n) * n
            else:
                daddr = ((daddr + n - 1) // n) * n
        elif op.startswith("."):
            raise AsmError(line.lineno, f"unknown directive {line.op!r}")
        else:
            if section != "text":
                raise AsmError(line.lineno, "instructions are not allowed in .data")
            addr += 1
        image.max_program = max(image.max_program, addr)
        image.max_data = max(image.max_data, daddr)

    if image.max_program > PROG_WORDS:
        raise AsmError(0, f"program needs {image.max_program} words, limit is {PROG_WORDS}")
    if image.max_data > DATA_BYTES:
        raise AsmError(0, f"data needs {image.max_data} bytes, limit is {DATA_BYTES}")

    # ---------------- pass 2: emit ----------------
    addr = 0
    daddr = 0
    section = "text"
    listing: list[str] = []
    for line in lines:
        if not line.op:
            if line.label:
                listing.append(f"        {line.label}:")
            elif line.source:
                listing.append("")
            continue
        op = line.op.lower()
        if op == ".equ":
            continue
        if op == ".org":
            v = eval_expr(line.operands[0], image.symbols, line.lineno)
            if section == "text":
                addr = v
            else:
                daddr = v
            listing.append(f"        ; .org {v}")
            continue
        if op == ".data":
            section = "data"
            listing.append("        ; .data")
            continue
        if op == ".text":
            section = "text"
            listing.append("        ; .text")
            continue
        if op in {".byte", ".word", "db", "dw"}:
            for value_text in line.operands:
                v = eval_expr(value_text, image.symbols, line.lineno)
                if section == "text":
                    word = check_range(v, -128, 0xFFFF, "word", line.lineno) & 0xFFFF
                    image.program[addr] = word
                    listing.append(f"{addr:02X}: {word:04X}    {line.source}")
                    addr += 1
                elif op in {".byte", "db"}:
                    b = check_range(v, -128, 0xFF, "byte", line.lineno) & 0xFF
                    image.data[daddr] = b
                    listing.append(f"D{daddr:02X}: {b:02X}      {line.source}")
                    daddr += 1
                else:
                    word = check_range(v, -32768, 0xFFFF, "word", line.lineno) & 0xFFFF
                    for shift in (0, 8):
                        image.data[daddr] = (word >> shift) & 0xFF
                        listing.append(f"D{daddr:02X}: {(word >> shift) & 0xFF:02X}      {line.source}")
                        daddr += 1
            continue
        if op == ".fill":
            count = eval_expr(line.operands[0], image.symbols, line.lineno)
            val = eval_expr(line.operands[1], image.symbols, line.lineno) if len(line.operands) > 1 else 0
            for _ in range(count):
                if section == "text":
                    image.program[addr] = val & 0xFFFF
                    listing.append(f"{addr:02X}: {val & 0xFFFF:04X}    {line.source}")
                    addr += 1
                else:
                    image.data[daddr] = val & 0xFF
                    listing.append(f"D{daddr:02X}: {val & 0xFF:02X}      {line.source}")
                    daddr += 1
            continue
        if op == ".align":
            n = eval_expr(line.operands[0], image.symbols, line.lineno)
            if section == "text":
                while addr % n:
                    image.program[addr] = 0
                    listing.append(f"{addr:02X}: 0000    ; align")
                    addr += 1
            else:
                while daddr % n:
                    image.data[daddr] = 0
                    listing.append(f"D{daddr:02X}: 00      ; align")
                    daddr += 1
            continue
        if op.startswith("."):
            raise AsmError(line.lineno, f"unknown directive {line.op!r}")
        if section != "text":
            raise AsmError(line.lineno, "instructions are not allowed in .data")
        if line.label:
            listing.append(f"        {line.label}:")
        word = encode_instruction(line.op, line.operands, image.symbols, line.lineno)
        image.program[addr] = word
        listing.append(f"{addr:02X}: {word:04X}    {line.source}")
        addr += 1

    image.listing = listing  # type: ignore[attr-defined]
    image.source_name = source_name  # type: ignore[attr-defined]
    return image


def to_intel_hex(image: Image) -> str:
    out: list[str] = []

    def record(addr: int, data: list[int]) -> None:
        ll = len(data)
        body = [ll, (addr >> 8) & 0xFF, addr & 0xFF, 0x00] + data
        checksum = (-sum(body)) & 0xFF
        out.append(":" + "".join(f"{b:02X}" for b in body) + f"{checksum:02X}")

    # Program words, big-endian, at byte address word*2.
    items = sorted(image.program.items())
    for start in range(0, len(items), 8):
        chunk = items[start : start + 8]
        addr = chunk[0][0] * 2
        data: list[int] = []
        for _, word in chunk:
            data.extend([(word >> 8) & 0xFF, word & 0xFF])
        record(addr, data)
    # Data bytes at 0x8000.
    items = sorted(image.data.items())
    for start in range(0, len(items), 16):
        chunk = items[start : start + 16]
        addr = 0x8000 + chunk[0][0]
        record(addr, [v for _, v in chunk])
    out.append(":00000001FF")
    return "\n".join(out) + "\n"


def to_json(image: Image) -> str:
    doc = {
        "format": "proteus-image",
        "version": 1,
        "program_words": PROG_WORDS,
        "data_bytes": DATA_BYTES,
        "program": [[a, w] for a, w in sorted(image.program.items())],
        "data": [[a, b] for a, b in sorted(image.data.items())],
        "symbols": {k: v for k, v in sorted(image.symbols.items())},
        "max_program": image.max_program,
        "max_data": image.max_data,
    }
    return json.dumps(doc, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Proteus-1 assembler")
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="output base name (default: source stem)")
    ap.add_argument("--hex", dest="hexfile", type=Path, help="Intel HEX output")
    ap.add_argument("--json", dest="jsonfile", type=Path, help="image JSON output")
    ap.add_argument("--lst", dest="lstfile", type=Path, help="listing output")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    try:
        text = args.source.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        image = assemble(text, str(args.source))
    except AsmError as exc:
        print(f"{args.source}: {exc}", file=sys.stderr)
        return 1

    base = args.output or args.source.with_suffix("")
    hexfile = args.hexfile or base.with_suffix(".hex")
    jsonfile = args.jsonfile or base.with_suffix(".json")
    lstfile = args.lstfile or base.with_suffix(".lst")

    hexfile.write_text(to_intel_hex(image), encoding="utf-8")
    jsonfile.write_text(to_json(image), encoding="utf-8")
    lstfile.write_text("\n".join(getattr(image, "listing", [])) + "\n", encoding="utf-8")

    if not args.quiet:
        print(f"{args.source}: {image.max_program} program words, {image.max_data} data bytes")
        print(f"  {hexfile}")
        print(f"  {jsonfile}")
        print(f"  {lstfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
