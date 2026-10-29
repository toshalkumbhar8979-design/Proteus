// Proteus-1 Tiny Tapeout top level.
//
// Pin roles:
//   ui_in[7]   CFG_CS_N    host loader chip select, active low
//   ui_in[6]   CFG_SCK     host loader clock
//   ui_in[5]   CFG_MOSI    host loader data
//   ui_in[4:0] general inputs (firmware-defined)
//   uo_out[7]  CFG_MISO    loader readback (only while CS_N is low)
//   uo_out[6:0] general outputs (firmware-defined)
//   uio[7:0]   bidirectional GPIO, per-bit output enable and open-drain
//
// While CS_N is low the CPU is halted and the bidir pins are inputs. While
// CS_N is high and run=1 the CPU owns all protocol pins. The configuration pins
// are still readable as GPIO in run mode; the host must leave them static.

`default_nettype none

module tt_um_proteus (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

  wire cfg_cs_n = ui_in[7];
  wire cfg_sck  = ui_in[6];
  wire cfg_mosi = ui_in[5];
  wire cfg_miso;

  wire        run;
  wire        cfg_busy;
  wire        prog_we;
  wire [7:0]  prog_waddr;
  wire [15:0] prog_wdata;
  wire [7:0]  cfg_raddr;
  wire [6:0]  pc;
  wire [15:0] instr;

  wire        loader_data_we;
  wire [5:0]  loader_data_waddr;
  wire [7:0]  loader_data_wdata;
  wire        core_data_we;
  wire [5:0]  core_data_waddr;
  wire [7:0]  core_data_wdata;
  wire [5:0]  data_raddr;
  wire [7:0]  data_rdata;

  // The loader and the core never write in the same cycle (the CPU is held
  // while CS_N is low), but they are separate ports; mux them so there is one
  // driver on the RAM.
  wire        ram_data_we    = loader_data_we | core_data_we;
  wire [5:0]  ram_data_waddr = loader_data_we ? loader_data_waddr : core_data_waddr;
  wire [7:0]  ram_data_wdata = loader_data_we ? loader_data_wdata : core_data_wdata;

  wire [7:0]  cpu_uo;
  wire [7:0]  cpu_uio;
  wire [7:0]  cpu_uio_oe;
  wire [7:0]  cpu_uio_od;

  // While the host owns the configuration port, the program RAM read port is
  // routed to the loader for readback. The CPU is halted, so its fetch address
  // is irrelevant.
  wire [6:0] prog_raddr = cfg_busy ? cfg_raddr[6:0] : pc;

  proteus_loader u_loader (
      .clk        (clk),
      .rst_n      (rst_n),
      .cs_n       (cfg_cs_n),
      .sck        (cfg_sck),
      .mosi       (cfg_mosi),
      .miso       (cfg_miso),
      .run        (run),
      .prog_we    (prog_we),
      .prog_waddr (prog_waddr),
      .prog_wdata (prog_wdata),
      .cfg_raddr  (cfg_raddr),
      .cfg_rdata  (instr),
      .data_we    (loader_data_we),
      .data_waddr (loader_data_waddr),
      .data_wdata (loader_data_wdata),
      .busy       (cfg_busy)
  );

  proteus_prog_ram #(
      .AW(7),
      .DW(16)
  ) u_prog_ram (
      .clk   (clk),
      .we    (prog_we),
      .waddr (prog_waddr[6:0]),
      .wdata (prog_wdata),
      .raddr (prog_raddr),
      .rdata (instr)
  );

  proteus_data_ram #(
      .AW(6),
      .DW(8)
  ) u_data_ram (
      .clk   (clk),
      .we    (ram_data_we),
      .waddr (ram_data_waddr),
      .wdata (ram_data_wdata),
      .raddr (data_raddr),
      .rdata (data_rdata)
  );

  proteus_core #(
      .PROG_AW(7),
      .DATA_AW(6)
  ) u_core (
      .clk       (clk),
      .rst_n     (rst_n && run),
      .en        (run && !cfg_busy),
      .ui_in     (ui_in),
      .uio_in    (uio_in),
      .uo_out    (cpu_uo),
      .uio_out   (cpu_uio),
      .uio_oe    (cpu_uio_oe),
      .uio_od    (cpu_uio_od),
      .pc_out    (pc),
      .instr     (instr),
      .data_waddr(core_data_waddr),
      .data_wdata(core_data_wdata),
      .data_we   (core_data_we),
      .data_raddr(data_raddr),
      .data_rdata(data_rdata)
  );

  // Loader owns uo_out[7] while CS_N is low. In run mode the CPU owns it.
  assign uo_out = cfg_busy ? {cfg_miso, 7'b0} :
                  (run      ? cpu_uo : 8'b0);

  // Bidir pins are inputs unless the CPU is running. Open-drain mode disables
  // the high-side driver whenever the output bit is 1.
  assign uio_out = (run && !cfg_busy) ? cpu_uio : 8'b0;
  assign uio_oe  = (run && !cfg_busy) ?
                   (cpu_uio_oe & ~(cpu_uio & cpu_uio_od)) : 8'b0;

  // The loader address is 8 bits on the wire; the 128-word memory uses 7.
  // Consume the unused MSBs so lint does not report them as dangling.
  wire _unused = &{ena, prog_waddr[7], cfg_raddr[7], 1'b0};

`ifdef FORMAL
  // Formal-only: with the CPU stopped and no frame in progress, every output
  // and every output enable is driven low. A board must never see a floating or
  // undriven pin between loader frames.
  reg f_past_valid;
  initial f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;

`ifndef F_NO_OUT
  always @(posedge clk) begin
    if (!run && !cfg_busy) begin
      assert (uo_out  == 8'b0);
      assert (uio_out == 8'b0);
      assert (uio_oe  == 8'b0);
    end
  end
`endif
`endif

endmodule

`default_nettype wire
