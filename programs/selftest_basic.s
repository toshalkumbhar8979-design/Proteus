; Proteus-1 basic self-test.
;
; Writes a walking pattern to uo_out, exercises the ALU and data memory, then
; halts. The expected final values are checked by test/test.py.

        .org 0x00
start:
        LDI A, 0x55
        OUT UO, A
        WAIT 10
        LDI A, 0xAA
        OUT UO, A
        WAIT 10

        ; ALU: 3 + 4 = 7
        LDI A, 3
        ADD A, 4
        OUT UO, A

        ; Data memory: store 0xC3 at 0x10 and read it back.
        LDI A, 0xC3
        ST (0x10), A
        LDI A, 0x00
        LD A, (0x10)
        OUT UO, A

        ; Loop: X = 3 down to 0, A increments each time.
        LDI X, 3
        LDI A, 0
loop:
        ADD A, 1
        DEC X
        JNZ loop
        OUT UO, A

        ; Indexed memory: X = 0x20, store A, read back, then make the
        ; result distinguishable from the previous output.
        LDI X, 0x20
        ST (X), A
        LDI A, 0
        LD A, (X)
        ADD A, 1
        OUT UO, A

        ; Bit operations produce a unique 0x11 -> 0x91 -> 0x90 -> 0x10 run.
        OUT UO, 0x11
        SETB UO, 0x80
        TGLB UO, 0x01
        CLRB UO, 0x80

        ; Timer signature check: A should become 0xA1.
        ID
        OUT UO, A

        HALT
