; Proteus-1 UART receiver, 8N1, 115200 baud at 48 MHz.
;
; RX is ui_in[3] (the Tiny Tapeout Pmod UART RX pin). The receiver waits for a
; low start bit, delays to the centre of data bit 0, then samples every 417
; cycles. Each sample is shifted in LSB-first with the carry-insertion trick:
;
;   IN UI; AND A,0x08; SWAP A; ADD A,0x80   -> C = RX bit, A = 0
;   LD A,(0); ROR A; ST (0),A               -> insert at bit 7, shift right
;
; The loop body is 9 cycles (IN, AND, SWAP, ADD, LD, ROR, ST, DEC, JNZ), so the
; two WAITs total 408 cycles and the sample-to-sample period is 417. WAIT 217
; after the start edge puts the first sample at the centre of data bit 0.

.equ RX_MASK, 0x08

        .org 0x00
start:
        OUT UO, 0x00
        WAIT_PIN0 UI, RX_MASK     ; start bit
        WAIT 217                  ; start centre + 217 -> data bit 0 centre
        LDI Y, 8
        LDI A, 0
        ST (0x00), A

rx_loop:
        WAIT 255
        WAIT 153                  ; 408 + 9 loop cycles = 417
        IN UI
        AND A, RX_MASK
        SWAP A                    ; 0x08 -> 0x80
        ADD A, 0x80               ; C = RX bit
        LD A, (0x00)              ; LD preserves flags
        ROR A                     ; insert at bit 7, shift right
        ST (0x00), A
        DEC Y
        JNZ rx_loop

        LD A, (0x00)
        OUT UO, A
        HALT
