; Proteus-1 JTAG master.
;
; Demonstrates a fourth protocol family with nothing but firmware and the
; existing bidirectional pins:
;   uio[0] = TCK  (output)
;   uio[1] = TMS  (output)
;   uio[2] = TDI  (output)
;   ui[4]  = TDO  (input; uio_in is owned by the I2C bus model)
;
; The firmware walks a standard 1149.1 TAP into Shift-DR and clocks out the
; 32-bit IDCODE, then checks it byte by byte. It relies on the IEEE rule that a
; TAP with an IDCODE register loads instruction 0x01 out of Test-Logic-Reset, so
; no IR scan is needed. If the captured value matches, it writes 0xC3 to
; uo_out; a mismatch writes 0xE7. The testbench models the TAP and asserts both
; the state path and the captured value.
;
; TCK is high for one clock and low for two. That is far below a real JTAG
; clock, which is the point: the timing comes from WAIT instructions, and the
; same firmware can be retimed by changing two constants.

.equ TCK,  0x01
.equ TMS,  0x02
.equ TDI,  0x04
.equ TDO,  0x10

.equ B_ACC,  0x05            ; byte being assembled
.equ B_BIT,  0x06            ; last TDO sample
.equ B_LEFT, 0x07            ; bits still to clock, minus one

        .org 0x00
        LDI A, TCK | TMS | TDI
        OUT UIO_OE, A            ; TDO stays an input
        CLRB UIO, TCK
        CLRB UIO, TDI
        SETB UIO, TMS

        ; Test-Logic-Reset: five TCK with TMS high.
        LDI Y, 5
rst_loop:
        LDI A, 0
        CALL cycle
        DEC Y
        JNZ rst_loop

        ; Run-Test/Idle -> Select-DR -> Capture-DR -> Shift-DR.
        CLRB UIO, TMS
        LDI A, 0
        CALL cycle               ; Run-Test/Idle
        SETB UIO, TMS
        LDI A, 0
        CALL cycle               ; Select-DR
        CLRB UIO, TMS
        LDI A, 0
        CALL cycle               ; Capture-DR. The next cycle is both the
                                 ; entry into Shift-DR and the first data bit,
                                 ; because TDO is valid after its falling edge.

        ; Clock 32 bits out of the DR. The last one raises TMS to enter
        ; Exit1-DR, which is how a scan is terminated.
        LDI A, 31
        ST (B_LEFT), A
        LDI A, 0
        ST (B_ACC), A
        LDI X, 1                 ; destination byte 1..4
next_byte:
        LDI Y, 8
bit_loop:
        LD A, (B_LEFT)
        CMP A, 0                 ; LOAD does not touch flags
        JNZ no_tms
        SETB UIO, TMS            ; thirty-second bit: Exit1-DR
no_tms:
        LDI A, 0                 ; TDI is don't-care during IDCODE
        CALL cycle
        ST (B_BIT), A
        LD A, (B_ACC)
        SHR A
        ST (B_ACC), A
        LD A, (B_BIT)
        CMP A, 0                 ; TDO was masked to its pin bit, so 0 means 0
        JZ no_set
        LD A, (B_ACC)
        OR A, 0x80
        ST (B_ACC), A
no_set:
        LD A, (B_LEFT)
        DEC A
        ST (B_LEFT), A
        DEC Y
        JNZ bit_loop
        LD A, (B_ACC)
        ST (X), A                ; store MSB-first byte
        LDI A, 0
        ST (B_ACC), A
        INC X
        TFR 0                    ; A <- X
        CMP A, 5
        JNZ next_byte

        ; Update-DR -> Run-Test/Idle.
        SETB UIO, TMS
        LDI A, 0
        CALL cycle
        CLRB UIO, TMS
        LDI A, 0
        CALL cycle

        ; Check the captured IDCODE 0x1A5A5A5D, MSB first.
        LD A, (1)
        CMP A, 0x5D
        JNZ fail
        LD A, (2)
        CMP A, 0x5A
        JNZ fail
        LD A, (3)
        CMP A, 0x5A
        JNZ fail
        LD A, (4)
        CMP A, 0x1A
        JNZ fail
        LDI A, 0xC3
        OUT UO, A
        HALT

fail:
        LDI A, 0xE7
        OUT UO, A
        HALT

; -------------------------------------------------------------------- cycle
; One TCK pulse with TDI = A[0]. Returns the TDO level in A[0].
; TMS must already be driven. Clobbers A only.
cycle:
        AND A, 1
        JZ cy_tdi0
        SETB UIO, TDI
        JMP cy_clock
cy_tdi0:
        CLRB UIO, TDI
cy_clock:
        SETB UIO, TCK            ; rising edge: TAP samples TMS and TDI
        WAIT 1
        CLRB UIO, TCK            ; falling edge: TAP updates TDO
        WAIT 1
        IN UI
        AND A, TDO
        RET
