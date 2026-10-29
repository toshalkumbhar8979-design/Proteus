; Proteus-1 SPI master, CPOL=1 (modes 2 and 3), MSB first.
;
; Standard Tiny Tapeout Pmod pinout:
;   uio[0] = CS_N
;   uio[1] = MOSI
;   uio[2] = MISO (input, not driven by this example)
;   uio[3] = SCK
;
; SCK idles high. The first edge is falling, the second is rising. MOSI is
; stable across both edges, so the same waveform is valid for:
;   mode 2 (CPHA=0): the receiver samples on the falling (first) edge
;   mode 3 (CPHA=1): the receiver samples on the rising (second) edge
; The companion spi_master.s uses CPOL=0 and covers modes 0 and 1 the same way.
; CPHA is a receiver sampling convention; a master that holds data stable
; across the whole bit satisfies both phases.

.equ PIN_CS,   0x01
.equ PIN_MOSI, 0x02
.equ PIN_MISO, 0x04
.equ PIN_SCK,  0x08

        .org 0x00
start:
        LDI A, PIN_CS | PIN_SCK  ; CS high, SCK high, MOSI low
        OUT UIO, A
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
        CLRB UIO, PIN_SCK        ; falling edge
        WAIT 2
        SETB UIO, PIN_SCK        ; rising edge
        WAIT 2
        DEC Y
        JNZ spi_bit

        SETB UIO, PIN_CS         ; deselect, SCK idles high
        OUT UO, 0x5A             ; done marker
        HALT
