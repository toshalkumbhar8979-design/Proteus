// Proteus-1 host loader.
//
// A small SPI-mode-0 target used to load program words and data bytes, and to
// start/stop the CPU. It is deliberately independent of the CPU: the CPU is
// held in reset while run=0, and held (not reset) while CFG_CS_N is low.
//
// Frame: 32 bits, MSB first: {command[7:0], address[7:0], data[15:0]}.
//  0x01  write program word
//  0x02  write data byte
//  0x03  control (bit 0 = run)
//  0x04  read program word into the MISO holding register
//  0x00  no operation
//
// Readback is pipelined: 0x04 latches the word, and the NEXT 32-bit frame
// shifts it out on MISO during its first 16 SCK rising edges.
//
// The SCK/CS/MOSI pins are asynchronous. Each is passed through two flops; the
// host must keep SCK at or below clk/4 and hold CS for at least two clocks
// around a frame.

`default_nettype none

module proteus_loader (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        cs_n,
    input  wire        sck,
    input  wire        mosi,
    output wire        miso,

    output reg         run,
    output reg         prog_we,
    output reg  [7:0]  prog_waddr,
    output reg  [15:0] prog_wdata,
    output reg  [7:0]  cfg_raddr,
    input  wire [15:0] cfg_rdata,

    output reg         data_we,
    output reg  [5:0]  data_waddr,
    output reg  [7:0]  data_wdata,

    output wire        busy
);

  // Two-flop synchronisers. cs_s[0] is the newest sample.
  reg [1:0] cs_s;
  reg [1:0] sck_s;
  reg [1:0] mosi_s;

  always @(posedge clk) begin
    if (!rst_n) begin
      cs_s   <= 2'b11;
      sck_s  <= 2'b00;
      mosi_s <= 2'b00;
    end else begin
      cs_s   <= {cs_s[0], cs_n};
      sck_s  <= {sck_s[0], sck};
      mosi_s <= {mosi_s[0], mosi};
    end
  end

  wire cs_low  = ~cs_s[1];      // conservative level for frame logic
  wire sck_rise = sck_s[0] & ~sck_s[1];
  assign busy = ~cs_s[0];       // halt the CPU quickly

  reg [30:0] sr;                // first 31 frame bits; the 32nd is mosi
  reg [5:0]  bit_cnt;           // 0..32
  reg [15:0] miso_shift;
  reg        miso_pending;
  reg        read_pending;

  assign miso = (cs_low && miso_pending) ? miso_shift[15] : 1'b0;

  wire [31:0] frame = {sr, mosi_s[1]};
  wire [7:0]  cmd   = frame[31:24];
  wire [7:0]  addr  = frame[23:16];
  wire [15:0] dat   = frame[15:0];

  always @(posedge clk) begin
    if (!rst_n) begin
      sr           <= 31'b0;
      bit_cnt      <= 6'd0;
      miso_shift   <= 16'b0;
      miso_pending <= 1'b0;
      read_pending <= 1'b0;
      run          <= 1'b0;
      prog_we      <= 1'b0;
      prog_waddr   <= 8'b0;
      prog_wdata   <= 16'b0;
      cfg_raddr    <= 8'b0;
      data_we      <= 1'b0;
      data_waddr   <= 6'b0;
      data_wdata   <= 8'b0;
    end else begin
      // One-cycle write pulses.
      prog_we <= 1'b0;
      data_we <= 1'b0;

      // Pipelined readback: the address was set on the previous clock, and the
      // program RAM has had a full cycle to drive cfg_rdata.
      if (read_pending) begin
        miso_shift   <= cfg_rdata;
        miso_pending <= 1'b1;
        read_pending <= 1'b0;
      end

      if (!cs_low) begin
        // Idle: clear the receive path, but keep a pending readback response so
        // the host can raise CS between the read command and the reply frame.
        bit_cnt <= 6'd0;
        sr      <= 31'b0;
      end else if (sck_rise) begin
        // Shift the readback word out during the first 16 bits of a frame.
        if (miso_pending && (bit_cnt < 6'd16)) begin
          miso_shift <= {miso_shift[14:0], 1'b0};
          if (bit_cnt == 6'd15) begin
            miso_pending <= 1'b0;
          end
        end

        if (bit_cnt < 6'd32) begin
          sr      <= {sr[29:0], mosi_s[1]};
          bit_cnt <= bit_cnt + 6'd1;

          if (bit_cnt == 6'd31) begin
            // Full frame is now visible as `frame`. Commit it.
            sr      <= 31'b0;
            bit_cnt <= 6'd0;

            case (cmd)
              8'h01: begin
                prog_we    <= 1'b1;
                prog_waddr <= addr;
                prog_wdata <= dat;
              end
              8'h02: begin
                data_we    <= 1'b1;
                data_waddr <= addr[5:0];
                data_wdata <= dat[7:0];
              end
              8'h03: begin
                run <= dat[0];
              end
              8'h04: begin
                cfg_raddr    <= addr;
                read_pending <= 1'b1;
              end
              default: begin
                // 0x00 and unknown commands do nothing.
              end
            endcase
          end
        end
      end
    end
  end

`ifdef FORMAL
  // Formal-only: after one idle clock, the frame shifter and bit counter are
  // empty. That is what makes back-to-back frames independent: a short CS pulse
  // cannot leave stale bits that shift into the next command.
  reg f_past_valid;
  initial f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;

`ifndef F_NO_LOADER
  always @(posedge clk) begin
    if (f_past_valid && rst_n) begin
      if (!cs_low && !$past(cs_low)) begin
        assert (sr == 31'b0);
        assert (bit_cnt == 6'd0);
      end
    end
  end
`endif
`endif

endmodule

`default_nettype wire
