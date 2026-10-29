; Proteus-1 I2C controller example, 400 kHz.
;
; Standard Tiny Tapeout Pmod pinout:
;   uio[2] = SCL
;   uio[3] = SDA
;
; Both pins are open-drain: uio_out=1 releases the line, uio_out=0 pulls it
; low, and uio_od=1 disables the high-side driver. External 4.7k pull-ups are
; required, as with any I2C bus. The firmware writes 0x42 to the 7-bit address
; 0x28 (write direction, so the address byte is 0x50).
;
; SCL timing: the bit loop is about 83 clocks from one rising edge to the
; next (WAIT 38 + WAIT 38 + seven instruction cycles), which is 386 kHz at
; 32 MHz. That is inside the 400 kHz fast-mode limit with margin for the
; instruction path. The ACK wait is a pin-level wait, so the target can stretch
; by holding SDA low. There is no timeout; a missing target will stall the CPU,
; which is intentional for a bring-up demo.

.equ SCL, 0x04
.equ SDA, 0x08

        .org 0x00
start:
        SETB UIO, SCL | SDA      ; release both lines
        LDI A, SCL | SDA
        OUT UIO_OE, A            ; SCL and SDA are outputs
        LDI A, SCL | SDA
        OUT UIO_OD, A            ; open-drain
        OUT UO, 0x00
        WAIT 20

        ; START: SDA falls while SCL is high.
        SETB UIO, SDA
        SETB UIO, SCL
        WAIT 20
        CLRB UIO, SDA
        WAIT 20
        CLRB UIO, SCL
        WAIT 20

        LDI A, 0x50              ; address 0x28, write
        CALL i2c_send
        LDI A, 0x42              ; data byte
        CALL i2c_send

        ; STOP: SDA rises while SCL is high.
        CLRB UIO, SDA
        WAIT 20
        SETB UIO, SCL
        WAIT 20
        SETB UIO, SDA
        WAIT 20

        OUT UO, 0x5A             ; done marker
        HALT

; ----------------------------------------------------------------- i2c_send
; A = byte to send. Clobbers A, Y. Returns after the target ACKs.
i2c_send:
        LDI Y, 8
i2c_bit:
        SHL A                    ; C = MSB
        JC sda_one
        CLRB UIO, SDA
        JMP sda_ready
sda_one:
        SETB UIO, SDA
sda_ready:
        SETB UIO, SCL            ; release SCL; target samples SDA
        WAIT 38
        CLRB UIO, SCL            ; pull SCL low
        WAIT 38
        DEC Y
        JNZ i2c_bit

        ; ACK cycle: release SDA, release SCL, wait until the target pulls
        ; SDA low. Then take SCL low again for the next byte.
        SETB UIO, SDA
        SETB UIO, SCL
        WAIT 20
        WAIT_PIN0 UIO, SDA
        CLRB UIO, SCL
        WAIT 20
        RET
