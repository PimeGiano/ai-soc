`timescale 1ns / 1ps
module det_soc_top #(
	parameter ENABLE_ICACHE = 1,
	parameter ENABLE_PREFETCH = 1,
	parameter ENABLE_BANKED_GATHER = 1
) (
	input wire clk, rst,
	output wire trap,
	output wire mem_valid,
	output wire [31:0] mem_addr, mem_wdata,
	output wire [3:0] mem_wstrb,
	input wire mem_ready,
	input wire [31:0] mem_rdata,
	output wire mem_dma, mem_instr
);

	wire cv, cr, dv, dr, sv, sr, ci, cbv, cbr;
	wire [31:0] cbd;
	wire [31:0] ca, cw, cd, da, dw, dd, sa, sw, sd;
	wire [3:0] cs, ds, ss;
	wire reg_select = sa[31:8] == 24'h100001;
	wire pool_select = sa[31:8] == 24'h100002;
	wire pool_rr, pool_dv, pool_dr, external_ready;
	wire [31:0] pool_rd, pool_da, pool_dw;
	wire [31:0] unused_pool_crdata, unused_pool_drdata;
	wire [3:0] pool_ds;
	wire rr;
	wire [31:0] rd;
	/* verilator lint_off PINCONNECTEMPTY */
	picorv32 #(
		.ENABLE_FAST_MUL(1),
		.ENABLE_DIV(1),
		.ENABLE_COUNTERS(1),
		.ENABLE_IRQ(0),
		.COMPRESSED_ISA(0),
		.PROGADDR_RESET(0),
		.STACKADDR(32'h05000000)
	) cpu (
		.clk(clk),
		.resetn(!rst),
		.trap(trap),
		.mem_valid(cv),
		.mem_instr(ci),
		.mem_ready(cr),
		.mem_addr(ca),
		.mem_wdata(cw),
		.mem_wstrb(cs),
		.mem_rdata(cd),
		.mem_la_read(),
		.mem_la_write(),
		.mem_la_addr(),
		.mem_la_wdata(),
		.mem_la_wstrb(),
		.pcpi_valid(),
		.pcpi_insn(),
		.pcpi_rs1(),
		.pcpi_rs2(),
		.pcpi_wr(1'b0),
		.pcpi_rd(32'b0),
		.pcpi_wait(1'b0),
		.pcpi_ready(1'b0),
		.irq(32'b0),
		.eoi(),
		.trace_valid(),
		.trace_data()
	);
	/* verilator lint_on PINCONNECTEMPTY */
	generate
		if (ENABLE_ICACHE != 0) begin : cached_cpu

			instruction_cache icache (
				.clk(clk),
				.rst(rst),
				.cpu_valid(cv),
				.cpu_instr(ci),
				.cpu_addr(ca),
				.cpu_wstrb(cs),
				.cpu_ready(cr),
				.cpu_rdata(cd),
				.bus_valid(cbv),
				.bus_ready(cbr),
				.bus_rdata(cbd)
			);
		end else begin : uncached_cpu
			assign cbv = cv;
			assign cr = cbr;
			assign cd = cbd;
		end
	endgenerate

	native_arbiter arb (
		.clk(clk),
		.rst(rst),
		.c_valid(cbv),
		.c_addr(ca),
		.c_wdata(cw),
		.c_wstrb(cs),
		.c_ready(cbr),
		.c_rdata(cbd),
		.d_valid(dv),
		.d_addr(da),
		.d_wdata(dw),
		.d_wstrb(ds),
		.d_ready(dr),
		.d_rdata(dd),
		.s_valid(sv),
		.s_addr(sa),
		.s_wdata(sw),
		.s_wstrb(ss),
		.s_ready(sr),
		.s_rdata(sd)
	);
	det_accelerator #(
		.ENABLE_PREFETCH(ENABLE_PREFETCH),
		.ENABLE_BANKED_GATHER(ENABLE_BANKED_GATHER)
	) accel (
		.clk(clk),
		.rst(rst),
		.reg_valid(sv && reg_select),
		.reg_addr(sa[7:0]),
		.reg_wdata(sw),
		.reg_wstrb(ss),
		.reg_ready(rr),
		.reg_rdata(rd),
		.dma_valid(dv),
		.dma_addr(da),
		.dma_wdata(dw),
		.dma_wstrb(ds),
		.dma_ready(dr),
		.dma_rdata(dd)
	);

	pool_accelerator pool_engine (
		.clk(clk),
		.rst(rst),
		.reg_valid(sv && pool_select),
		.reg_addr(sa[7:0]),
		.reg_wdata(sw),
		.reg_wstrb(ss),
		.reg_ready(pool_rr),
		.reg_rdata(pool_rd),
		.dma_valid(pool_dv),
		.dma_addr(pool_da),
		.dma_wdata(pool_dw),
		.dma_wstrb(pool_ds),
		.dma_ready(pool_dr),
		.dma_rdata(mem_rdata)
	);

	// Pool and convolution execute sequential graph operators. This outer
	// arbiter nevertheless locks stalled requests and supports contention.
	native_arbiter pool_arbiter (
		.clk(clk),
		.rst(rst),
		.c_valid(sv && !reg_select && !pool_select),
		.c_addr(sa),
		.c_wdata(sw),
		.c_wstrb(ss),
		.c_ready(external_ready),
		.c_rdata(unused_pool_crdata),
		.d_valid(pool_dv),
		.d_addr(pool_da),
		.d_wdata(pool_dw),
		.d_wstrb(pool_ds),
		.d_ready(pool_dr),
		.d_rdata(unused_pool_drdata),
		.s_valid(mem_valid),
		.s_addr(mem_addr),
		.s_wdata(mem_wdata),
		.s_wstrb(mem_wstrb),
		.s_ready(mem_ready),
		.s_rdata(mem_rdata)
	);

	assign sr = reg_select ? rr : (pool_select ? pool_rr : external_ready);
	assign sd = reg_select ? rd : (pool_select ? pool_rd : mem_rdata);
	assign mem_dma = pool_dr || (dr && !reg_select && !pool_select);
	assign mem_instr = ci && !mem_dma;
endmodule
