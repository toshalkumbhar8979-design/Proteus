// Proteus-1 capture FIFO.
//
// Samples the 16 external pin bits every enabled clock while cap_en=1. When the
// sampled vector differs from the previous sample it pushes
// {timestamp[7:0], uio_in[7:0], ui_in[7:0]}. The oldest entry is exposed
// combinationally as head_data, so a CAP_POP instruction can both read the head
// and advance the read pointer on the same clock edge.
//
// The FIFO is intentionally small (8 entries, 24 bits each). It is a protocol
// analyzer, not a frame buffer. New events are dropped when full; the status
// byte tells firmware that this happened.

`default_nettype none

module proteus_capture #(
    parameter integer CAP_AW = 3
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              en,          // run && !cfg_busy
    input  wire [15:0]       pins,        // {uio_in, ui_in}
    input  wire [7:0]        timestamp,
    input  wire              set_en,      // CAP_EN instruction
    input  wire              en_val,      // imm[0]
    input  wire              pop,         // CAP_POP instruction
    input  wire              clear,       // CAP_CLR instruction
    output wire [23:0]       head_data,
    output wire [7:0]        status
);

  localparam integer DEPTH = (1 << CAP_AW);
  localparam [CAP_AW:0] DEPTH_COUNT = (1 << CAP_AW);

  reg [23:0] mem [0:DEPTH-1];
  reg [CAP_AW-1:0] wr_ptr;
  reg [CAP_AW-1:0] rd_ptr;
  reg [CAP_AW:0]   count;       // 0..8 needs four bits
  reg [15:0]       last_pins;
  reg              cap_en;

  wire full  = (count == DEPTH_COUNT);
  wire empty = (count == 0);

  // When CAP_EN turns capture on, seed the edge detector with the current pins
  // so the first sample does not look like an event. The same edge must not
  // also push.
  wire enabling = set_en && en_val && !cap_en;
  wire pushing  = en && cap_en && !enabling && (pins != last_pins);
  wire pushing_ok = pushing && !full;
  wire popping_ok = pop && !empty;

  assign head_data = empty ? 24'b0 : mem[rd_ptr];
  assign status    = {full, empty, 2'b00, count[3:0]};

  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin
      wr_ptr   <= {CAP_AW{1'b0}};
      rd_ptr   <= {CAP_AW{1'b0}};
      count    <= {(CAP_AW+1){1'b0}};
      last_pins <= 16'b0;
      cap_en   <= 1'b0;
      for (i = 0; i < DEPTH; i = i + 1) begin
        mem[i] <= 24'b0;
      end
    end else begin
      // Capture enable register.
      if (set_en) begin
        cap_en <= en_val;
      end

      if (enabling) begin
        last_pins <= pins;
      end else if (en && cap_en && (pins != last_pins)) begin
        // Track the newest observed state even when the FIFO is full, otherwise
        // a full FIFO would retry the same event forever and miss later ones.
        last_pins <= pins;
      end

      if (clear) begin
        wr_ptr <= {CAP_AW{1'b0}};
        rd_ptr <= {CAP_AW{1'b0}};
        count  <= {(CAP_AW+1){1'b0}};
      end else begin
        if (pushing_ok) begin
          mem[wr_ptr] <= {timestamp, pins};
          wr_ptr <= wr_ptr + 1'b1;
        end
        if (popping_ok) begin
          rd_ptr <= rd_ptr + 1'b1;
        end

        if (pushing_ok && !popping_ok) begin
          count <= count + 1'b1;
        end else if (!pushing_ok && popping_ok) begin
          count <= count - 1'b1;
        end
        // Push and pop together leave count unchanged.
      end
    end
  end

`ifdef FORMAL
  // Formal-only: the FIFO fill level can never exceed its depth, so CAP_STATUS
  // cannot report a count the firmware would use to index past the array.
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
