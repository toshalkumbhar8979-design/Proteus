// SPDX-FileCopyrightText: 2026 Toshal Kumbhar
// SPDX-License-Identifier: Apache-2.0
// Proteus-1 core.
//
// A single-cycle 8-bit accumulator CPU built for pin timing. Every ordinary
// instruction retires in one enabled clock. WAIT, WAIT_PIN*, WAIT_EDGE, and
// HALT are the only instructions that hold the program counter.
//
// The core is held in reset while run=0 (rst_n low). The loader releases run
// only after the program has been written, so the first fetch is always a word
// the host loaded.
//
// Data-memory writes and capture-FIFO pops are combinational from the decoded
// instruction, not registered. That makes ST followed by LD observe the new
// byte on the very next instruction, and makes CAP_POP followed by CAP_UI
// observe the popped entry without a pipeline bubble.

`default_nettype none

module proteus_core #(
    parameter integer PROG_AW = 7,
    parameter integer DATA_AW = 6
) (
    input  wire                  clk,
    input  wire                  rst_n,       // core reset, active low
    input  wire                  en,          // run && !cfg_busy

    input  wire [7:0]            ui_in,
    input  wire [7:0]            uio_in,

    output wire [7:0]            uo_out,
    output wire [7:0]            uio_out,
    output wire [7:0]            uio_oe,
    output wire [7:0]            uio_od,

    output wire [PROG_AW-1:0]    pc_out,
    input  wire [15:0]           instr,

    output wire [DATA_AW-1:0]    data_waddr,
    output wire [7:0]            data_wdata,
    output wire                  data_we,
    output wire [DATA_AW-1:0]    data_raddr,
    input  wire [7:0]            data_rdata
);

  // ---------------------------------------------------------------------------
  // Opcode map (ISA v1.0)
  // ---------------------------------------------------------------------------
  localparam [4:0] OP_ALU    = 5'd0;
  localparam [4:0] OP_SHIFT  = 5'd1;
  localparam [4:0] OP_LOAD   = 5'd2;
  localparam [4:0] OP_IO     = 5'd3;
  localparam [4:0] OP_BRANCH = 5'd4;
  localparam [4:0] OP_TIME   = 5'd5;
  localparam [4:0] OP_BIT    = 5'd6;
  localparam [4:0] OP_MISC   = 5'd7;
  localparam [4:0] OP_ALUX   = 5'd8;
  localparam [4:0] OP_ALUY   = 5'd9;
  localparam [4:0] OP_TIMER  = 5'd10;
  localparam [4:0] OP_CAP    = 5'd11;

  // ---------------------------------------------------------------------------
  // Architectural state
  // ---------------------------------------------------------------------------
  reg [7:0]          a;
  reg [7:0]          x;
  reg [7:0]          y;
  reg [PROG_AW-1:0]  pc;
  reg [2:0]          sp;
  reg [7:0]          stack [0:7];
  reg                z;
  reg                c;
  reg                n;

  reg [7:0]          uo_r;
  reg [7:0]          uio_r;
  reg [7:0]          uio_oe_r;
  reg [7:0]          uio_od_r;

  reg [15:0]         timer;
  reg [7:0]          timer_hi;

  reg                halt;
  reg                wait_active;
  reg [8:0]          wait_cnt;
  reg [2:0]          wait_kind;
  reg [7:0]          wait_mask;
  reg [15:0]         wait_ref;

  reg [23:0]         cap_rd;

  // ---------------------------------------------------------------------------
  // Decode
  // ---------------------------------------------------------------------------
  wire [4:0] op  = instr[15:11];
  wire [2:0] sub = instr[10:8];
  wire [7:0] imm = instr[7:0];

  wire [15:0] pins = {uio_in, ui_in};
  wire        cpu_active = en && !halt && !wait_active;

  // ---------------------------------------------------------------------------
  // Combinational ALU / shifts
  // ---------------------------------------------------------------------------
  reg [7:0]  alu_rhs;
  reg        alu_cin;
  reg [8:0]  alu_res;
  reg [8:0]  shift_res;

  always @* begin
    alu_rhs = imm;
    case (op)
      OP_ALUX: alu_rhs = x;
      OP_ALUY: alu_rhs = y;
      default: alu_rhs = imm;
    endcase

    alu_cin = 1'b0;
    if ((op == OP_ALU) || (op == OP_ALUX) || (op == OP_ALUY)) begin
      if ((sub == 3'd1) || (sub == 3'd3)) begin
        alu_cin = c;
      end
    end

    case (sub)
      3'd0: alu_res = {1'b0, a} + {1'b0, alu_rhs} + {8'b0, alu_cin};
      3'd1: alu_res = {1'b0, a} + {1'b0, alu_rhs} + {8'b0, alu_cin};
      3'd2: alu_res = {1'b0, a} - {1'b0, alu_rhs} - {8'b0, alu_cin};
      3'd3: alu_res = {1'b0, a} - {1'b0, alu_rhs} - {8'b0, alu_cin};
      3'd4: alu_res = {1'b0, (a & alu_rhs)};
      3'd5: alu_res = {1'b0, (a | alu_rhs)};
      3'd6: alu_res = {1'b0, (a ^ alu_rhs)};
      3'd7: alu_res = {1'b0, a} - {1'b0, alu_rhs};
      default: alu_res = {1'b0, a};
    endcase
  end

  always @* begin
    case (sub)
      3'd0: shift_res = {a[7], a[6:0], 1'b0};       // SHL
      3'd1: shift_res = {a[0], 1'b0, a[7:1]};       // SHR
      3'd2: shift_res = {a[7], a[6:0], c};          // ROL
      3'd3: shift_res = {a[0], c, a[7:1]};          // ROR
      3'd4: shift_res = {a[0], a[7], a[7:1]};       // ASR
      3'd5: shift_res = {c, a[3:0], a[7:4]};        // SWAP
      3'd6: shift_res = {c, (a + 8'd1)};            // INC A
      3'd7: shift_res = {c, (a - 8'd1)};            // DEC A
      default: shift_res = {c, a};
    endcase
  end

  wire [7:0] x_inc = x + 8'd1;
  wire [7:0] x_dec = x - 8'd1;
  wire [7:0] y_inc = y + 8'd1;
  wire [7:0] y_dec = y - 8'd1;

  wire [8:0] wait_n = (imm == 8'd0) ? 9'd256 : {1'b0, imm};

  // ---------------------------------------------------------------------------
  // Data-memory port: write is combinational so ST is visible to the next LD.
  // ---------------------------------------------------------------------------
  wire load_st_x   = (op == OP_LOAD) && (sub == 3'd4);
  wire load_st_dir = (op == OP_LOAD) && (sub == 3'd6);
  wire load_ld_x   = (op == OP_LOAD) && (sub == 3'd3);

  assign data_we    = cpu_active && (load_st_x || load_st_dir);
  assign data_waddr = load_st_x ? x[DATA_AW-1:0] : imm[DATA_AW-1:0];
  assign data_wdata = a;
  assign data_raddr = load_ld_x ? x[DATA_AW-1:0] : imm[DATA_AW-1:0];

  // ---------------------------------------------------------------------------
  // Capture FIFO. Control signals are combinational from the CAP instruction so
  // the FIFO advances on the same edge that the core consumes the head.
  // ---------------------------------------------------------------------------
  wire cap_insn    = cpu_active && (op == OP_CAP);
  wire cap_set_en  = cap_insn && (sub == 3'd0);
  wire cap_pop     = cap_insn && (sub == 3'd1);
  wire cap_clear   = cap_insn && (sub == 3'd6);
  wire cap_en_val  = imm[0];

  wire [23:0] cap_head;
  wire [7:0]  cap_status;

  proteus_capture #(
      .CAP_AW(3)
  ) u_capture (
      .clk       (clk),
      .rst_n     (rst_n),
      .en        (en),
      .pins      (pins),
      .timestamp (timer[7:0]),
      .set_en    (cap_set_en),
      .en_val    (cap_en_val),
      .pop       (cap_pop),
      .clear     (cap_clear),
      .head_data (cap_head),
      .status    (cap_status)
  );

  // ---------------------------------------------------------------------------
  // Outputs
  // ---------------------------------------------------------------------------
  assign uo_out   = uo_r;
  assign uio_out  = uio_r;
  assign uio_oe   = uio_oe_r;
  assign uio_od   = uio_od_r;
  assign pc_out   = pc;

  // ---------------------------------------------------------------------------
  // Sequential core
  // ---------------------------------------------------------------------------
  integer i;

  always @(posedge clk) begin
    if (!rst_n) begin
      a          <= 8'b0;
      x          <= 8'b0;
      y          <= 8'b0;
      pc         <= {PROG_AW{1'b0}};
      sp         <= 3'b0;
      z          <= 1'b0;
      c          <= 1'b0;
      n          <= 1'b0;
      uo_r       <= 8'b0;
      uio_r      <= 8'b0;
      uio_oe_r   <= 8'b0;
      uio_od_r   <= 8'b0;
      timer      <= 16'b0;
      timer_hi   <= 8'b0;
      halt       <= 1'b0;
      wait_active <= 1'b0;
      wait_cnt   <= 9'b0;
      wait_kind  <= 3'b0;
      wait_mask  <= 8'b0;
      wait_ref   <= 16'b0;
      cap_rd     <= 24'b0;
      for (i = 0; i < 8; i = i + 1) begin
        stack[i] <= 8'b0;
      end
    end else if (en) begin
      // The cycle timer free-runs whenever the core is enabled, including while
      // the CPU is waiting or halted. A TMR_CLR instruction below overrides the
      // increment on that edge.
      timer <= timer + 16'd1;

      if (!halt) begin
        if (wait_active) begin
          // -----------------------------------------------------------------
          // Multi-cycle wait state
          // -----------------------------------------------------------------
          case (wait_kind)
            3'd0: begin
              if (wait_cnt == 9'd1) begin
                wait_active <= 1'b0;
                pc          <= pc + 1'b1;
              end else begin
                wait_cnt <= wait_cnt - 9'd1;
              end
            end
            3'd1: begin  // UI level 0
              if ((ui_in & wait_mask) == 8'b0) begin
                wait_active <= 1'b0;
                pc          <= pc + 1'b1;
              end
            end
            3'd2: begin  // UI level 1
              if ((ui_in & wait_mask) == wait_mask) begin
                wait_active <= 1'b0;
                pc          <= pc + 1'b1;
              end
            end
            3'd3: begin  // UIO level 0
              if ((uio_in & wait_mask) == 8'b0) begin
                wait_active <= 1'b0;
                pc          <= pc + 1'b1;
              end
            end
            3'd4: begin  // UIO level 1
              if ((uio_in & wait_mask) == wait_mask) begin
                wait_active <= 1'b0;
                pc          <= pc + 1'b1;
              end
            end
            3'd5: begin  // edge on UI
              if (((pins ^ wait_ref) & {8'h00, wait_mask}) != 16'b0) begin
                wait_active <= 1'b0;
                pc          <= pc + 1'b1;
              end
            end
            3'd6: begin  // edge on UIO
              if (((pins ^ wait_ref) & {wait_mask, 8'h00}) != 16'b0) begin
                wait_active <= 1'b0;
                pc          <= pc + 1'b1;
              end
            end
            default: begin
              wait_active <= 1'b0;
              pc          <= pc + 1'b1;
            end
          endcase
        end else begin
          // -----------------------------------------------------------------
          // Normal single-cycle instruction
          // -----------------------------------------------------------------
          pc <= pc + 1'b1;

          case (op)
            // ---------------------------------------------------------------
            OP_ALU, OP_ALUX, OP_ALUY: begin
              if (sub != 3'd7) begin
                a <= alu_res[7:0];
              end
              z <= (alu_res[7:0] == 8'b0);
              c <= alu_res[8];
              n <= alu_res[7];
            end

            // ---------------------------------------------------------------
            OP_SHIFT: begin
              a <= shift_res[7:0];
              z <= (shift_res[7:0] == 8'b0);
              n <= shift_res[7];
              if (sub <= 3'd4) begin
                c <= shift_res[8];
              end
            end

            // ---------------------------------------------------------------
            OP_LOAD: begin
              case (sub)
                3'd0: a <= imm;
                3'd1: x <= imm;
                3'd2: y <= imm;
                3'd3: a <= data_rdata;
                3'd4: ; // ST (X),A
                3'd5: a <= data_rdata;
                3'd6: ; // ST imm,A
                3'd7: begin
                  case (imm[2:0])
                    3'd0: a <= x;
                    3'd1: x <= a;
                    3'd2: a <= y;
                    3'd3: y <= a;
                    3'd4: x <= y;
                    3'd5: y <= x;
                    default: ; // reserved, no effect
                  endcase
                end
                default: ;
              endcase
            end

            // ---------------------------------------------------------------
            OP_IO: begin
              case (sub)
                3'd0: uo_r      <= a;
                3'd1: uio_r     <= a;
                3'd2: uio_oe_r  <= a;
                3'd3: uio_od_r  <= a;
                3'd4: a         <= ui_in;
                3'd5: a         <= uio_in;
                3'd6: uo_r      <= imm;
                3'd7: uio_r     <= imm;
                default: ;
              endcase
            end

            // ---------------------------------------------------------------
            OP_BRANCH: begin
              case (sub)
                3'd0: pc <= imm[PROG_AW-1:0];
                3'd1: if (z)  pc <= imm[PROG_AW-1:0];
                3'd2: if (!z) pc <= imm[PROG_AW-1:0];
                3'd3: if (c)  pc <= imm[PROG_AW-1:0];
                3'd4: if (!c) pc <= imm[PROG_AW-1:0];
                3'd5: begin
                  stack[sp] <= {1'b0, pc} + 8'd1;
                  sp        <= sp + 3'd1;
                  pc        <= imm[PROG_AW-1:0];
                end
                3'd6: begin
                  pc <= stack[sp - 3'd1][PROG_AW-1:0];
                  sp <= sp - 3'd1;
                end
                3'd7: begin
                  y <= y_dec;
                  z <= (y_dec == 8'b0);
                  n <= y_dec[7];
                  if (y != 8'd1) begin
                    pc <= imm[PROG_AW-1:0];
                  end
                end
                default: ;
              endcase
            end

            // ---------------------------------------------------------------
            OP_TIME: begin
              case (sub)
                3'd0: begin // WAIT imm (0 = 256)
                  if (wait_n != 9'd1) begin
                    wait_cnt    <= wait_n - 9'd1;
                    wait_kind   <= 3'd0;
                    wait_active <= 1'b1;
                    pc          <= pc;
                  end
                end
                3'd1: begin // wait UI low
                  wait_kind <= 3'd1;
                  wait_mask <= imm;
                  if ((ui_in & imm) != 8'b0) begin
                    wait_active <= 1'b1;
                    pc          <= pc;
                  end
                end
                3'd2: begin // wait UI high
                  wait_kind <= 3'd2;
                  wait_mask <= imm;
                  if ((ui_in & imm) != imm) begin
                    wait_active <= 1'b1;
                    pc          <= pc;
                  end
                end
                3'd3: begin // wait UIO low
                  wait_kind <= 3'd3;
                  wait_mask <= imm;
                  if ((uio_in & imm) != 8'b0) begin
                    wait_active <= 1'b1;
                    pc          <= pc;
                  end
                end
                3'd4: begin // wait UIO high
                  wait_kind <= 3'd4;
                  wait_mask <= imm;
                  if ((uio_in & imm) != imm) begin
                    wait_active <= 1'b1;
                    pc          <= pc;
                  end
                end
                3'd5: begin // wait for UI edge
                  wait_ref    <= pins;
                  wait_kind   <= 3'd5;
                  wait_mask   <= imm;
                  wait_active <= 1'b1;
                  pc          <= pc;
                end
                3'd6: begin // wait for UIO edge
                  wait_ref    <= pins;
                  wait_kind   <= 3'd6;
                  wait_mask   <= imm;
                  wait_active <= 1'b1;
                  pc          <= pc;
                end
                3'd7: begin // HALT
                  halt <= 1'b1;
                  pc   <= pc;
                end
                default: ;
              endcase
            end

            // ---------------------------------------------------------------
            OP_BIT: begin
              case (sub)
                3'd0: uo_r     <= uo_r | imm;
                3'd1: uo_r     <= uo_r & ~imm;
                3'd2: uo_r     <= uo_r ^ imm;
                3'd3: uio_r    <= uio_r | imm;
                3'd4: uio_r    <= uio_r & ~imm;
                3'd5: uio_r    <= uio_r ^ imm;
                3'd6: uio_oe_r <= uio_oe_r | imm;
                3'd7: uio_oe_r <= uio_oe_r & ~imm;
                default: ;
              endcase
            end

            // ---------------------------------------------------------------
            OP_MISC: begin
              case (sub)
                3'd0: ; // NOP
                3'd1: begin x <= x_inc; z <= (x_inc == 8'b0); n <= x_inc[7]; end
                3'd2: begin x <= x_dec; z <= (x_dec == 8'b0); n <= x_dec[7]; end
                3'd3: begin y <= y_inc; z <= (y_inc == 8'b0); n <= y_inc[7]; end
                3'd4: begin y <= y_dec; z <= (y_dec == 8'b0); n <= y_dec[7]; end
                3'd5: a <= x;
                3'd6: x <= a;
                3'd7: y <= a;
                default: ;
              endcase
            end

            // ---------------------------------------------------------------
            OP_TIMER: begin
              case (sub)
                3'd0: begin
                  a        <= timer[7:0];
                  timer_hi <= timer[15:8];
                end
                3'd1: a <= timer_hi;
                3'd2: begin
                  timer    <= 16'b0;
                  timer_hi <= 8'b0;
                end
                3'd7: a <= 8'hA1; // Proteus-1 signature
                default: ;
              endcase
            end

            // ---------------------------------------------------------------
            OP_CAP: begin
              case (sub)
                3'd0: ; // CAP_EN, combinational control
                3'd1: cap_rd <= cap_head;
                3'd2: a <= cap_rd[7:0];
                3'd3: a <= cap_rd[15:8];
                3'd4: a <= cap_rd[23:16];
                3'd5: a <= cap_status;
                3'd6: cap_rd <= 24'b0;
                default: ;
              endcase
            end

            default: ;
          endcase
        end
      end
    end
  end

`ifdef FORMAL
  // ---------------------------------------------------------------------------
  // Formal-only properties. Not synthesized; proven by scripts/formal.sh.
  // ---------------------------------------------------------------------------
  reg f_past_valid;
  initial f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;

  always @(posedge clk) begin
    if (f_past_valid && rst_n) begin
      // Each property can be excluded with a define so scripts/formal.sh can
      // report them one at a time instead of letting the first failure mask the
      // rest.
`ifndef F_NO_PC
      // While the core is disabled (the loader owns the pins, or run=0), the
      // program counter must not move. Otherwise a host writing a new image
      // would race a fetch it thinks is stopped. `$past` is the value before the
      // edge just taken, so the guard is the previous cycle's enable: that is
      // the signal that decided whether this edge updated the register.
      if ($past(rst_n) && !$past(en)) assert (pc == $past(pc));
`endif
`ifndef F_NO_TIMER
      // The cycle timer either advances by exactly one or is cleared by TMR_CLR.
      // No instruction may make it jump or run backwards. Again the guard is the
      // previous cycle's enable, which is what gated the update being observed.
      if ($past(rst_n) && $past(en))
        assert ((timer == ($past(timer) + 16'd1)) || (timer == 16'd0));
`endif
`ifndef F_NO_STACK
      // CALL pushes PC+1 into stack[sp] and bumps sp; RET reads stack[sp-1] into
      // PC and drops sp. These two assertions tie the pointer arithmetic to the
      // data so neither half can drift: right after a CALL the slot below the
      // new sp must hold the return address, and right after a RET the PC must
      // be exactly the slot the popped pointer addresses. sp is three bits, so
      // an overflow wraps to entry 0 on purpose; the modulo-8 index below is the
      // same arithmetic the RTL performs, including that wrap.
      if ($past(rst_n) && $past(cpu_active)) begin
        if (($past(op) == OP_BRANCH) && ($past(sub) == 3'd5)) begin
          assert (sp == ($past(sp) + 3'd1));
          assert (stack[sp - 3'd1] == ({1'b0, $past(pc)} + 8'd1));
        end
        if (($past(op) == OP_BRANCH) && ($past(sub) == 3'd6)) begin
          assert (sp == ($past(sp) - 3'd1));
          // RET loads only PROG_AW bits, so a return address of 0x80 (PC was
          // 0x7F) comes back as 0. Compare through the same truncation.
          //
          // The index is the *current* sp: $past samples the whole expression
          // one edge back, and in that cycle sp was one higher than it is now,
          // so stack[sp - 1] here is exactly the slot RET read. Writing
          // $past(stack[$past(sp) - 1]) instead would sample with sp from two
          // cycles back and be off by one frame.
          assert ({1'b0, pc} == ($past(stack[sp - 3'd1]) & 8'h7F));
        end
      end
`endif
    end
  end
`endif

endmodule

`default_nettype wire
