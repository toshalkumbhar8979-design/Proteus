; Proteus-1 capture timestamp span self-test.
;
; Records two edges on ui[2] roughly 300 clocks apart, then reports both 16-bit
; timestamps. A 300-clock interval cannot be expressed in eight bits, so this
; image is the proof that the capture engine stores the whole cycle counter
; rather than its low byte: with an 8-bit timestamp the reported span would wrap
; to about 44.
;
;   ui[2]      edge source, driven by the testbench
;   uo_out     four bytes, low then high for each edge, then 0xAA
;
; The gap is padded by the testbench; the firmware only has to see two edges and
; report what the capture engine recorded for them.

.equ EDGE,   0x04

        .org 0x00
        CAP_CLR
        CAP_EN 1                 ; FIFO mode, edge detector seeded
        WAIT_EDGE UI, EDGE       ; first edge
        WAIT_EDGE UI, EDGE       ; second edge, after the injected gap

        CAP_POP
        CAP_TS                   ; low byte of the first timestamp
        OUT UO, A
        CAP_TSH                  ; high byte of the first timestamp
        OUT UO, A

        CAP_POP
        CAP_TS
        OUT UO, A
        CAP_TSH
        OUT UO, A

        OUT UO, 0xAA
        HALT
