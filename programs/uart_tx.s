; Proteus-1 UART transmitter, 8N1, 76.8 kbaud at 32 MHz.
;
; 32 MHz / 76800 = 416.67 clocks per bit. BIT_CYCLES is rounded to 417
; (0.08% error, well inside the 2-3% a real UART tolerates). The bit period is
; kept exact by accounting for the two instructions around each WAIT:
;
;   start bit: OUT (1) + WAIT(255) + WAIT(160) = 417
;   data bit : ROR(1) + OUT(1) + WAIT(255+158) + DEC(1) + JNZ(1) = 417
;   stop bit : last data OUT + WAIT(413) + DEC + JNZ + NOP = 417
;
; Data is emitted on uo_out[7] by rotating the byte through carry. Only bit 7
; is the UART line; the other output bits carry the rotated byte and are
; unused. This avoids a conditional branch per data bit, which would make the
; bit period depend on the data value.

.equ TX_BIT, 7

        .org 0x00
start:
        OUT UO, 0xFF          ; idle high
        LDI A, 0x50           ; 'P'
        CALL uart_tx
        LDI A, 0x31           ; '1'
        CALL uart_tx
        LDI A, 0x0A           ; newline
        CALL uart_tx
        OUT UO, 0xFF
        HALT

; ------------------------------------------------------------------ uart_tx
; A = byte to send. Clobbers A, Y. Preserves X.
uart_tx:
        SHR A                 ; C = bit 0, A = {0, b7..b1}
        LDI Y, 8              ; 8 data bits
        OUT UO, 0x00          ; start bit, low
        WAIT 255
        WAIT 160              ; 415 = 417 - 2
tx_loop:
        ROR A                 ; LSB moves to bit 7
        OUT UO, A
        WAIT 255
        WAIT 158              ; 413 = 417 - 4
        DEC Y
        JNZ tx_loop
        NOP                   ; align the stop edge to 417
        OUT UO, 0xFF          ; stop bit, high
        WAIT 255
        WAIT 161              ; hold the stop bit for 416 cycles
        RET
