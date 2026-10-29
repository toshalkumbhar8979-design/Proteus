// Proteus-1 program memory.
//
// One asynchronous read port (the CPU fetches one instruction per cycle) and
// one synchronous write port (the host loader). This is inferred as a
// distributed RAM: flops plus a read mux. There is deliberately no reset on the
// array; the host must load every word it intends to execute before setting
// run=1. The CPU is held in reset until then, so no uninitialised word is ever
// fetched.
//
// `ifdef SIM initialisation is for RTL simulation only. Synthesis never sees
// it because SIM is not defined by the GDS flow.

`default_nettype none

module proteus_prog_ram #(
    parameter integer AW = 8,
    parameter integer DW = 16
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
