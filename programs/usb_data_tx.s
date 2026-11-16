; Proteus-1 low-speed USB data packet transmitter.
;
; Emits a complete device data packet on uio[0] with the hardware helpers:
;
;   SYNC      0x80   (LSB first, so the line shows KJKJKJKK)
;   PID       0xC3   DATA0
;   payload   0x11 0x22
;   CRC-16    complemented, low byte then high byte
;   idle      line held at level 1
;
; Firmware only chooses what to send. Byte order, NRZI and bit stuffing come from
; the SER helper, and the CRC comes from CRC16_ADD / CRC16_LO / CRC16_HI, so a
; packet is six CALLs and two memory writes rather than a bit-banging loop.
;
;   uio[0]     line (output, NRZI coded, stuffed)
;   uo_out[0]  one-clock strobe on every bit time, for a scope or testbench
;
; Timing: the loop is eight one-cycle instructions plus WAIT 13, so a bit time is
; 21 clocks. At 32 MHz that is 1.524 Mbit/s, 1.6% above the 1.5 Mbit/s low-speed
; rate: this demonstrates the line code and the packet structure, not the PHY
; tolerance. A compliant rate needs a 21/22-clock pattern averaged over time,
; which is a change to one constant and one counter, not to the packet.
;
; The end-of-packet SE0 is not expressible on a single line pin, so the line is
; left at idle after the CRC. A real transceiver has both D+ and D-.

.equ LINE,   0x01
.equ STROBE, 0x01

        .org 0x00
        LDI A, LINE
        OUT UIO_OE, A            ; uio[0] is the line, driven by firmware
        SER_SET 1                ; idle level, stuffing state cleared
        OUT UIO, LINE
        OUT UO, 0x00

        CRC16_RST                ; CRC covers the payload only
        LDI A, 0x80              ; SYNC
        CALL send
        LDI A, 0xC3              ; PID DATA0
        CALL send
        LDI A, 0x11
        CRC16_ADD
        CALL send
        LDI A, 0x22
        CRC16_ADD
        CALL send
        CRC16_LO                 ; already complemented for the wire
        CALL send
        CRC16_HI
        CALL send

        OUT UO, 0xAA             ; packet finished
        HALT

; --------------------------------------------------------------------- send
; A = byte to transmit, LSB first. Clobbers A, preserves the CRC and line state.
send:
        SER_LD
send_loop:
        SER_BUSY                 ; sets Z when the byte and any stuff bit are gone
        CMP A, 0x01
        JNZ send_done
        SER_NEXT                 ; A = next line level, already NRZI coded
        OUT UIO, A
        OUT UO, STROBE
        OUT UO, 0x00
        WAIT 13                  ; 8 + 13 = 21 clocks per bit
        JMP send_loop
send_done:
        RET
