// SPDX-FileCopyrightText: 2026 Toshal Kumbhar
// SPDX-License-Identifier: Apache-2.0
// Proteus-1 capture engine.
//
// Samples the 16 external pin bits every enabled clock while cap_en=1. When the
// sampled vector differs from the previous sample it stores
// {timestamp[15:0], uio_in[7:0], ui_in[7:0]}. The oldest entry is exposed
// combinationally as head_data, so a CAP_POP instruction can both read the head
// and advance the read pointer on the same clock edge.
//
// The timestamp is the whole 16-bit cycle counter, not its low byte. An 8-bit
// timestamp aliases every 256 clocks, which is shorter than one bit time of the
// slow protocols this engine exists to demonstrate: a 76.8 kbaud UART bit is 417
// clocks and a 100 kHz I2C half-period is 160, so a low-byte-only scope could
// not time the traffic it had just captured. The cost is 32 entries x 8 extra
// bits, 256 flops, which the 8x4 allocation has.
//
// CAP_TS still returns the low byte at head_data[23:16] and CAP_TSH returns the
// high byte at [31:24], so firmware that only read the low byte keeps exactly
// the meaning it had before.
//
// Two modes, chosen by CAP_EN imm[1]:
//
//   FIFO mode (imm[1]=0, the default). New events are dropped once the buffer is
//   full and the status byte says so, so firmware can tell that it lost data.
//
//   Roll mode (imm[1]=1). The buffer keeps recording when full, overwriting the
//   oldest entry. That is a scope in roll mode: enable it, let the protocol run,
//   stop the program, and drain the last 32 edges before the stop without having
//   armed the capture in advance or known where the interesting edge would be.
//
// 32 entries is the deepest this can go and still describe itself in one status
// byte: full, empty, and a six-bit count. CAP_AW must stay <= 5 for that to
// hold; the status expression below zero-extends the count so a smaller build
// keeps the same bit layout.

`default_nettype none

module proteus_capture #(
    parameter integer CAP_AW = 5
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              en,          // run && !cfg_busy
    input  wire [15:0]       pins,        // {uio_in, ui_in}
    input  wire [15:0]       timestamp,
    input  wire              set_en,      // CAP_EN instruction
    input  wire              en_val,      // imm[0]
    input  wire              roll_val,    // imm[1]
    input  wire              pop,         // CAP_POP instruction
    input  wire              clear,       // CAP_CLR instruction
    output wire [31:0]       head_data,
    output wire [7:0]        status
);

  localparam integer DEPTH = (1 << CAP_AW);
  localparam [CAP_AW:0] DEPTH_COUNT = (1 << CAP_AW);

  reg [31:0] mem [0:DEPTH-1];
  reg [CAP_AW-1:0] wr_ptr;
  reg [CAP_AW-1:0] rd_ptr;
  reg [CAP_AW:0]   count;       // 0..DEPTH
  reg [15:0]       last_pins;
  reg              cap_en;
  reg              cap_mode;

  wire full  = (count == DEPTH_COUNT);
  wire empty = (count == 0);

  // When CAP_EN turns capture on, seed the edge detector with the current pins
  // so the first sample does not look like an event. The same edge must not
  // also push.
  wire enabling = set_en && en_val && !cap_en;
  wire pushing  = en && cap_en && !enabling && (pins != last_pins);

  // A push is kept in FIFO mode only while there is room. In roll mode it is
  // always kept, and when the buffer is full the write lands on the oldest entry.
  wire push = pushing && (!full || cap_mode);
  wire drop = push && full;
  wire popping = pop && !empty;

  wire [5:0] count6 = count;

  assign head_data = empty ? 32'b0 : mem[rd_ptr];
  assign status    = {full, empty, count6};

  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin
      wr_ptr   <= {CAP_AW{1'b0}};
      rd_ptr   <= {CAP_AW{1'b0}};
      count    <= {(CAP_AW+1){1'b0}};
      last_pins <= 16'b0;
      cap_en   <= 1'b0;
      cap_mode <= 1'b0;
      for (i = 0; i < DEPTH; i = i + 1) begin
        mem[i] <= 32'b0;
      end
    end else begin
      // Capture enable and mode register.
      if (set_en) begin
        cap_en   <= en_val;
        cap_mode <= roll_val;
      end

      if (enabling) begin
        last_pins <= pins;
      end else if (pushing) begin
        // Track the newest observed state even when the FIFO is full, otherwise
        // a full FIFO would retry the same event forever and miss later ones.
        last_pins <= pins;
      end

      if (clear) begin
        wr_ptr <= {CAP_AW{1'b0}};
        rd_ptr <= {CAP_AW{1'b0}};
        count  <= {(CAP_AW+1){1'b0}};
      end else begin
        if (push) begin
          mem[wr_ptr] <= {timestamp, pins};
          wr_ptr <= wr_ptr + 1'b1;
        end

        // The read pointer moves when an entry is consumed by CAP_POP, or when a
        // push into a full rolling buffer overwrites the oldest entry. A push and
        // a pop in the same cycle touch different slots, so one increment covers
        // both: while full, wr_ptr == rd_ptr and the store lands exactly in the
        // slot the pop just freed.
        if (popping) begin
          rd_ptr <= rd_ptr + 1'b1;
        end else if (drop) begin
          rd_ptr <= rd_ptr + 1'b1;
        end

        if (push && !popping && !drop) begin
          count <= count + 1'b1;
        end else if (!push && popping) begin
          count <= count - 1'b1;
        end
        // Push together with pop, or a push that overwrites the oldest entry,
        // leaves the fill level unchanged.
      end
    end
  end

`ifdef FORMAL
  // Formal-only: the buffer fill level can never exceed its depth, so CAP_STATUS
  // cannot report a count the firmware would use to index past the array. The
  // bound holds in roll mode too, where the count stays at DEPTH and the read
  // pointer moves instead.
`ifndef F_NO_CAP
  // The bound is a post-reset guarantee, not a power-up one: an ASIC flop can
  // come up in any state, which is exactly why the RTL has a reset. Track that
  // reset has been seen and prove the invariant from there on.
  reg f_reset_seen;
  initial f_reset_seen = 1'b0;
  always @(posedge clk) begin
    if (!rst_n) f_reset_seen <= 1'b1;
  end

  always @(posedge clk) begin
    if (f_reset_seen) assert (count <= DEPTH_COUNT);
  end
`endif
`endif

endmodule

`default_nettype wire
