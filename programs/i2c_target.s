; Proteus-1 I2C target example.
;
; Listens for the 7-bit address 0x28 (write byte 0x50), receives one data
; byte, ACKs both bytes, drives the received byte on uo_out[6:0], and sets
; uo_out[7] as a done flag after STOP. Open-drain SCL/SDA on uio[2]/uio[3].
;
; The receiver loop uses the carry-insertion trick:
;   IN UIO; AND A,SDA; SWAP A; ADD A,0x80
; produces C=1 for SDA high and C=0 for SDA low, without a branch. LD does not
; affect flags, so ROL A then shifts that bit into the accumulator.

.equ SCL, 0x04
.equ SDA, 0x08

        .org 0x00
start:
        SETB UIO, SCL | SDA
        LDI A, SCL | SDA
        OUT UIO_OE, A
        LDI A, SCL | SDA
        OUT UIO_OD, A
        OUT UO, 0x00

wait_start:
        WAIT_PIN0 UIO, SDA       ; START pulls SDA low while SCL is high
        WAIT_PIN0 UIO, SCL       ; controller pulls SCL low
        CALL recv_byte           ; address + R/W
        CMP A, 0x50
        JNZ not_me

        ; ACK the address.
        CLRB UIO, SDA
        WAIT_PIN1 UIO, SCL
        WAIT_PIN0 UIO, SCL
        SETB UIO, SDA

        CALL recv_byte           ; data byte
        OUT UO, A
        ST (0x00), A             ; keep it for the done marker

        ; ACK the data.
        CLRB UIO, SDA
        WAIT_PIN1 UIO, SCL
        WAIT_PIN0 UIO, SCL
        SETB UIO, SDA

        ; STOP: SDA goes low, then rises while SCL is high.
        WAIT_PIN0 UIO, SDA
        WAIT_PIN1 UIO, SDA
        LD A, (0x00)
        SETB UO, 0x80
        HALT

not_me:
        ; Not our address. Wait for STOP and try again.
        WAIT_PIN0 UIO, SDA
        WAIT_PIN1 UIO, SDA
        JMP wait_start

; ---------------------------------------------------------------- recv_byte
; Returns the received byte in A. MSB first, sampled on SCL rising.
; Clobbers A, Y. Uses data[0] as the accumulator.
recv_byte:
        LDI Y, 8
        LDI A, 0
        ST (0x00), A
rb_loop:
        WAIT_PIN1 UIO, SCL
        IN UIO
        AND A, SDA
        SWAP A                   ; 0x08 -> 0x80, 0x00 -> 0x00
        ADD A, 0x80              ; C = the SDA bit
        LD A, (0x00)             ; LD preserves flags
        ROL A                    ; shift the bit in at bit 0
        ST (0x00), A
        WAIT_PIN0 UIO, SCL
        DEC Y
        JNZ rb_loop
        LD A, (0x00)
        RET
