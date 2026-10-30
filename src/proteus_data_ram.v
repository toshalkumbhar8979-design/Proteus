// SPDX-FileCopyrightText: 2026 Toshal Kumbhar
// SPDX-License-Identifier: Apache-2.0
// Proteus-1 data memory: 64 bytes, asynchronous read, synchronous write.
//
// The core supplies one read address (direct or indexed) and one write address.
// Firmware must initialise any byte it reads; there is no hardware reset for the
// array. Simulation initialises it to zero for reproducible tests.

`default_nettype none

module proteus_data_ram #(
    parameter integer AW = 6,
    parameter integer DW = 8
) (
    input  wire              clk,
    input  wire              we,
    input  wire [AW-1:0]     waddr,
    input  wire [DW-1:0]     wdata,
    input  wire [AW-1:0]     raddr,
    output wire [DW-1:0]     rdata
);

  reg [DW-1:0] mem [0:(1<<AW)-1];

  always @(posedge clk) begin
    if (we) begin
      mem[waddr] <= wdata;
    end
  end

  assign rdata = mem[raddr];

`ifdef SIM
  integer i;
  initial begin
    for (i = 0; i < (1<<AW); i = i + 1) begin
      mem[i] = {DW{1'b0}};
    end
  end
`endif

endmodule

`default_nettype wire
