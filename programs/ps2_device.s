; Proteus-1 PS/2 device transmitter.
;
; Demonstrates a protocol outside the UART/SPI/I2C set using only firmware and
; the existing open-drain pins:
;   uio[0] = DATA  (device to host)
;   uio[1] = CLK   (device generates the clock)
;
; Both lines are open-drain with external pull-ups. The device sends one 11-bit
; frame: start 0, eight data bits LSB first, odd parity, stop 1. Data changes
; while CLK is high and is sampled by the host on the falling edge. The bit
; period is about 95 us at 48 MHz (WAIT 250 x 9 plus loop overhead), inside the
; 10-16.7 kHz PS/2 clock range.

.equ DATA, 0x01
.equ CLK,  0x02

        .org 0x00
start:
        SETB UIO, DATA | CLK     ; release both lines
        LDI A, DATA | CLK
        OUT UIO_OE, A            ; both are outputs
        LDI A, DATA | CLK
        OUT UIO_OD, A            ; open-drain
        OUT UO, 0x00
        WAIT 100

        ; Keep the byte in data[0] and count its one bits in X.
        LDI A, 0x5A
        ST (0x00), A
        LDI X, 0
        LDI Y, 8
par_loop:
        SHR A                    ; C = next bit
        JNC par_skip
        INC X
par_skip:
        DEC Y
        JNZ par_loop

        ; Odd parity: send 1 when the number of one bits is even.
        TFR X, A
        AND A, 1
        JZ parity_one
        LDI A, 0
        JMP parity_ready
parity_one:
        LDI A, 1
parity_ready:
        ST (0x01), A             ; save parity bit

        ; Start bit.
        LDI A, 0
        CALL send_bit

        ; Eight data bits, LSB first.
        LDI Y, 8
data_loop:
        LD A, (0x00)
        AND A, 1
        CALL send_bit
        LD A, (0x00)
        SHR A
        ST (0x00), A
        DEC Y
        JNZ data_loop

        ; Parity and stop.
        LD A, (0x01)
        CALL send_bit
        LDI A, 1
        CALL send_bit

        SETB UIO, DATA | CLK
        OUT UO, 0x5A             ; done marker
        HALT

; ------------------------------------------------------------------ send_bit
; A[0] = bit. Drives DATA while CLK is high, then emits one clock pulse.
; Clobbers A and X; preserves Y.
send_bit:
        AND A, 1
        JZ sb_zero
        SETB UIO, DATA
        JMP sb_ready
sb_zero:
        CLRB UIO, DATA
sb_ready:
        CLRB UIO, CLK            ; falling edge: host samples DATA
        CALL delay
        SETB UIO, CLK            ; rising edge: next DATA bit may change
        CALL delay
        RET

; -------------------------------------------------------------------- delay
; About 47 us at 48 MHz: 9 x (WAIT 250 + DEC + JNZ) plus call overhead.
delay:
        LDI X, 9
delay_loop:
        WAIT 250
        DEC X
        JNZ delay_loop
        RET
