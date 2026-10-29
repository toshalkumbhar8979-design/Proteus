; Proteus-1 SPI master, mode 0, MSB first.
;
; Standard Tiny Tapeout Pmod pinout:
;   uio[0] = CS_N
;   uio[1] = MOSI
;   uio[2] = MISO (input, not driven by this example)
;   uio[3] = SCK
;
; Sends 0xA5. SCK idles low; MOSI is set before the rising edge; the slave
; samples on the rising edge. The bit loop is deliberately branchy: SPI does
; not need a constant instruction count per bit, and the extra cycles make the
; waveform easy to probe on the demo board.

.equ PIN_CS,   0x01
.equ PIN_MOSI, 0x02
.equ PIN_MISO, 0x04
.equ PIN_SCK,  0x08

        .org 0x00
start:
        OUT UIO, PIN_CS          ; CS high, SCK low, MOSI low
        LDI A, PIN_CS | PIN_MOSI | PIN_SCK
        OUT UIO_OE, A            ; CS, MOSI, SCK are outputs
        LDI A, 0x00
        OUT UIO_OD, A            ; push-pull
        OUT UO, 0xA5             ; visible marker

        CLRB UIO, PIN_CS         ; select
        LDI A, 0xA5
        LDI Y, 8

spi_bit:
        SHL A                    ; C = MSB, A <<= 1
        JC mosi_one
        CLRB UIO, PIN_MOSI
        JMP mosi_ready
mosi_one:
        SETB UIO, PIN_MOSI
mosi_ready:
        SETB UIO, PIN_SCK        ; rising edge: slave samples MOSI
        WAIT 2
        CLRB UIO, PIN_SCK        ; falling edge
        WAIT 2
        DEC Y
        JNZ spi_bit

        SETB UIO, PIN_CS         ; deselect
        OUT UO, 0x5A             ; done marker
        HALT
