`default_nettype none
`timescale 1ns / 1ps

/* Cocotb testbench for Proteus-1. */
module tb ();

  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  wire [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  // Open-drain I2C bus model. uio[2] = SCL, uio[3] = SDA. The testbench
  // target can pull SDA low with sda_pull; the chip's own open-drain driver
  // pulls low when uio_oe is set and uio_out is 0. Otherwise the pull-up wins.
  reg  sda_pull;        // testbench target pulls SDA (chip is controller)
  reg  scl_drive_low;   // testbench controller drives SCL (chip is target)
  reg  sda_drive_low;   // testbench controller drives SDA (chip is target)
  wire scl_bus = (scl_drive_low || (uio_oe[2] && !uio_out[2])) ? 1'b0 : 1'b1;
  wire sda_bus = (sda_pull || sda_drive_low || (uio_oe[3] && !uio_out[3])) ? 1'b0 : 1'b1;
  assign uio_in = {4'b0000, sda_bus, scl_bus, 2'b00};

  tt_um_proteus user_project (
      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (ena),
      .clk    (clk),
      .rst_n  (rst_n)
  );

endmodule
