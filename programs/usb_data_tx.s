; Proteus-1 low-speed USB data packet transmitter, differential.
;
; Emits a complete device data packet on uio[0] = D- and uio[1] = D+:
;
;   SYNC      0x80   (LSB first, so the pair shows KJKJKJKK)
;   PID       0xC3   DATA0
;   payload   0x11 0x22
;   CRC-16    complemented, low byte then high byte
;   EOP       SE0 (both lines low) for two bit times, then idle J
;
; Firmware only chooses what to send. Bit order, NRZI, bit stuffing and the
; differential J/K mapping come from the SER helper, and the CRC from
; CRC16_ADD / CRC16_LO / CRC16_HI.
;
;   uio[0]     D-  (bit 0 of the pair)
;   uio[1]     D+  (bit 1 of the pair)
;   uo_out[0]  one-clock strobe on every bit time, for a scope or testbench
;
; Both lines are driven push-pull here. That is a demonstration choice: a board
; adds the 1.5 k pull-up on D- and series resistors, which firmware does not need
; to know about.
;
; Timing. A bit time is 21 or 22 clocks and the eight slots below alternate so the
; packet averages 21.25 clocks, which is 1.506 Mbit/s at 32 MHz: inside the +-1.5%
; low-speed tolerance, where a fixed 21-clock bit (1.524 Mbit/s, +1.6%) is outside
; it. That is the dither.
;
; Why the bit loop is unrolled instead of rotating three bodies: reloading the
; next byte costs seven clocks (DJNZ, LD/INC/SER_LD, the jump back, and the entry
; preamble), and that cost lands in the gap *before* the first bit of the new
; byte. With a rotating loop the slot that pays it is not known until runtime, so
; the gap after it is the one that grows: the measured pattern was 29, 14, 21, 21
; instead of 21, 21, 21, 21. Naming the slots s1..s8 makes the price known at
; assembly time, so s8 can shorten its own WAIT to absorb the reload and every bit
; time on the wire is 21 or 22 clocks. The test rejects anything else.
;
; This packet needs no stuffed bit (48 ones-runs are all shorter than six), so
; every byte occupies exactly eight slots. A packet that does need stuffing would
; shift the slots by one; the SER helper still inserts the bit, and a stuffing
; case wants a timer-paced loop rather than positional slots, which is noted in
; docs/verification.md as future work rather than pretended here.

.equ DM,     0x01         ; uio[0], D-
.equ DP,     0x02         ; uio[1], D+
.equ BOTH,   0x03

; Data-memory bytes 0x00..0x05 hold the packet. Building it first keeps the
; transmit loop free of CRC work, which is what makes the bit time constant.
.equ BUF,    0x00

        .org 0x00
        LDI A, BOTH
        OUT UIO_OE, A            ; both lines driven
        LDI A, 0x00
        OUT UIO_OD, A            ; push-pull
        SER_SET 1                ; idle: J
        SER_JK
        OUT UIO, A
        OUT UO, 0x00

        CRC16_RST                ; CRC covers the payload only
        LDI A, 0x11
        CRC16_ADD
        LDI A, 0x22
        CRC16_ADD
        CRC16_LO                 ; already complemented for the wire
        ST (0x04), A
        CRC16_HI
        ST (0x05), A

        LDI A, 0x80              ; SYNC
        ST (0x00), A
        LDI A, 0xC3              ; PID DATA0
        ST (0x01), A
        LDI A, 0x11
        ST (0x02), A
        LDI A, 0x22
        ST (0x03), A

        LDI X, BUF
        LDI Y, 6                 ; six bytes
byte_loop:
        LD A, (X)
        INC X
        SER_LD
        JMP s1

; --------------------------------------------------------------- bit slots
; A bit slot is nine words: SER_BUSY sets Z when nothing is left to send, so JZ
; leaves the slot for the next byte. The WAIT closes the slot and JMP names the
; successor, which is how each slot's own bit time is fixed.

s1:                              ; 22 clocks
        SER_BUSY
        JZ byte_done
        SER_NEXT
        SER_JK
        OUT UIO, A
        OUT UO, 0x01
        OUT UO, 0x00
        WAIT 14
        JMP s2

s2:                              ; 21 clocks
        SER_BUSY
        JZ byte_done
        SER_NEXT
        SER_JK
        OUT UIO, A
        OUT UO, 0x01
        OUT UO, 0x00
        WAIT 13
        JMP s3

s3:                              ; 21 clocks
        SER_BUSY
        JZ byte_done
        SER_NEXT
        SER_JK
        OUT UIO, A
        OUT UO, 0x01
        OUT UO, 0x00
        WAIT 13
        JMP s4

s4:                              ; 22 clocks
        SER_BUSY
        JZ byte_done
        SER_NEXT
        SER_JK
        OUT UIO, A
        OUT UO, 0x01
        OUT UO, 0x00
        WAIT 14
        JMP s5

s5:                              ; 21 clocks
        SER_BUSY
        JZ byte_done
        SER_NEXT
        SER_JK
        OUT UIO, A
        OUT UO, 0x01
        OUT UO, 0x00
        WAIT 13
        JMP s6

s6:                              ; 21 clocks
        SER_BUSY
        JZ byte_done
        SER_NEXT
        SER_JK
        OUT UIO, A
        OUT UO, 0x01
        OUT UO, 0x00
        WAIT 13
        JMP s7

s7:                              ; 21 clocks
        SER_BUSY
        JZ byte_done
        SER_NEXT
        SER_JK
        OUT UIO, A
        OUT UO, 0x01
        OUT UO, 0x00
        WAIT 13
        JMP s8

; s8 also carries the byte reload, so its WAIT is shorter by exactly the reload
; cost; the gap it leaves is still one bit time.
s8:                              ; 21 clocks
        SER_BUSY
        JZ byte_done
        SER_NEXT
        SER_JK
        OUT UIO, A
        OUT UO, 0x01
        OUT UO, 0x00
        WAIT 8
        JMP reload

reload:
        DJNZ Y, more_bytes
        JMP eop
more_bytes:
        LD A, (X)
        INC X
        SER_LD
        JMP s1

; ------------------------------------------------------------------ end of packet
byte_done:
eop:
        ; SE0 is both lines low, then the bus returns to J.
        OUT UIO, 0x00
        WAIT 40                  ; two bit times
        SER_SET 1
        SER_JK
        OUT UIO, A
        OUT UO, 0xAA
        HALT
