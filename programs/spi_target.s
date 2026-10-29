; Proteus-1 SPI target (receive-only), mode 0, MSB first.
;
; This example deliberately uses the dedicated input pins rather than uio, so
; it can coexist with the I2C bus model in simulation and with a second
; connector on a board:
;   ui[0] = CS_N
;   ui[1] = MOSI
;   ui[2] = SCK
;   uo[0..7] = received byte
;
; (The SPI master example uses the standard uio Pmod pinout. Pin assignment is
; firmware, not silicon.)

.equ CS,  0x01
.equ MOSI, 0x02
.equ SCK,  0x04

        .org 0x00
start:
        OUT UO, 0x00
wait_cs:
        WAIT_PIN0 UI, CS
        LDI Y, 8
        LDI A, 0
        ST (0x00), A
spi_bit:
        WAIT_PIN1 UI, SCK
        IN UI
        AND A, MOSI
        SHR A                    ; 0x02 -> 0x01
        ADD A, 0xFF              ; C = the MOSI bit
        LD A, (0x00)
        ROL A
        ST (0x00), A
        WAIT_PIN0 UI, SCK
        DEC Y
        JNZ spi_bit
        LD A, (0x00)
        OUT UO, A
        WAIT_PIN1 UI, CS
        HALT
