; Proteus-1 capture FIFO demo.
;
; Enables the 8-entry pin-change capture, waits while the testbench toggles
; ui_in[1:0], then reports:
;   status (count) -> oldest ui byte -> oldest uio byte -> timestamp -> 0xAA
;
; uio_in is driven high on uio[3:2] by the open-drain bus model, so the uio
; byte is 0x0C in simulation. On a real board it is whatever the pads see.

        .org 0x00
        CAP_CLR
        CAP_EN 1
        WAIT 40

        CAP_STATUS
        OUT UO, A
        CAP_POP
        CAP_UI
        OUT UO, A
        CAP_UIO
        OUT UO, A
        CAP_TS
        OUT UO, A
        OUT UO, 0xAA
        HALT
