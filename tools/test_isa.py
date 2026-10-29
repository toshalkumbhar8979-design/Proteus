"""Unit tests for the Proteus-1 ISA, assembler, disassembler, and ISS."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import proteus_isa as isa
from proteus_asm import AsmError, assemble
from proteus_iss import ProteusISS


def test_encode_decode_roundtrip():
    for op in range(12):
        for sub in range(8):
            word = isa.encode(op, sub, 0xA5)
            assert isa.decode(word) == (op, sub, 0xA5)
            d = isa.disassemble(word, 0x12)
            assert d.text
            assert d.text.startswith("12: ")


def test_assembler_all_mnemonics():
    src = """
        .equ K, 0x12
start:
        NOP
        LDI A, K
        LDI X, 1
        LDI Y, 2
        ADD A, 3
        ADC A, 4
        SUB A, 5
        SBC A, 6
        AND A, 0x0F
        OR A, 0xF0
        XOR A, 0xAA
        CMP A, 1
        ADD A, X
        SUB A, Y
        AND A, X
        OR A, Y
        XOR A, X
        CMP A, Y
        SHL A
        SHR A
        ROL A
        ROR A
        ASR A
        SWAP A
        INC A
        DEC A
        INC X
        DEC X
        INC Y
        DEC Y
        TFR A, X
        TFR X, A
        TFR A, Y
        TFR Y, A
        TFR X, Y
        TFR Y, X
        LD A, (X)
        ST (X), A
        LD A, (0x10)
        ST (0x10), A
        OUT UO, A
        OUT UIO, A
        OUT UIO_OE, A
        OUT UIO_OD, A
        IN UI
        IN UIO
        OUT UO, 0x5A
        OUT UIO, 0x5A
        SETB UO, 1
        CLRB UO, 1
        TGLB UO, 1
        SETB UIO, 1
        CLRB UIO, 1
        TGLB UIO, 1
        SETB UIO_OE, 1
        CLRB UIO_OE, 1
        JMP next
next:
        JZ next
        JNZ next
        JC next
        JNC next
        CALL sub
        RET
        LDI Y, 3
        DJNZ Y, next
        WAIT 1
        WAIT_PIN0 UI, 1
        WAIT_PIN1 UI, 1
        WAIT_PIN0 UIO, 1
        WAIT_PIN1 UIO, 1
        WAIT_EDGE UI, 1
        WAIT_EDGE UIO, 1
        TMR_LO
        TMR_HI
        TMR_CLR
        ID
        CAP_EN 1
        CAP_POP
        CAP_UI
        CAP_UIO
        CAP_TS
        CAP_STATUS
        CAP_CLR
        HALT
sub:
        RET
    """
    image = assemble(src)
    assert image.max_program > 0
    assert image.max_program <= 128
    for word in image.program.values():
        assert isa.disassemble(word).text


def test_assembler_directives_and_data():
    src = """
        .org 0x04
        .word 0xBEEF
        .byte 0x12, 0x34
        .fill 3, 0xAA
        .align 8
        .data
        .org 0x02
        .byte 0x11, 0x22
        .word 0x3344
        .text
        .org 0
        JMP 0
    """
    image = assemble(src)
    assert image.program[4] == 0xBEEF
    assert image.program[5] == 0x12
    assert image.program[6] == 0x34
    assert image.program[7] == 0x00AA
    assert image.program[8] == 0x00AA
    assert image.program[9] == 0x00AA
    assert image.data[2] == 0x11
    assert image.data[3] == 0x22
    assert image.data[4] == 0x44
    assert image.data[5] == 0x33


def test_assembler_errors():
    with pytest.raises(AsmError):
        assemble("JMP missing_label")
    with pytest.raises(AsmError):
        assemble("LDI A, 256")
    with pytest.raises(AsmError):
        assemble("OUT UIO_OE, 1")
    with pytest.raises(AsmError):
        assemble(".fill 129")
    with pytest.raises(AsmError):
        assemble("bogus A, 1")


def test_iss_arithmetic_and_memory():
    src = """
        LDI A, 3
        ADD A, 4
        ST (0x10), A
        LDI A, 0
        LD A, (0x10)
        OUT UO, A
        HALT
    """
    image = assemble(src)
    iss = ProteusISS(image.program, image.data)
    for _ in range(10):
        iss.step()
        if iss.halt:
            break
    assert iss.a == 7
    assert iss.uo == 7
    assert iss.data[0x10] == 7
    assert iss.halt


def test_iss_wait_is_exact():
    image = assemble("WAIT 10\nOUT UO, 0xAA\nHALT")
    iss = ProteusISS(image.program)
    pc0 = iss.pc
    iss.step()
    assert iss.pc == pc0
    for _ in range(9):
        iss.step()
    assert iss.pc == pc0 + 1
    assert iss.cycles == 10
    iss.step()
    assert iss.uo == 0xAA


def test_iss_djnz_and_stack():
    src = """
        LDI Y, 3
        LDI A, 0
loop:
        ADD A, 1
        DJNZ Y, loop
        CALL sub
        OUT UO, A
        HALT
sub:
        ADD A, 10
        RET
    """
    image = assemble(src)
    iss = ProteusISS(image.program)
    for _ in range(40):
        iss.step()
        if iss.halt:
            break
    assert iss.a == 13
    assert iss.uo == 13
    assert iss.sp == 0
