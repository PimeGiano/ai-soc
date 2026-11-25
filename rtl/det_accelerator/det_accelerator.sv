`timescale 1ns / 1ps

module det_accelerator #(
	parameter ENABLE_PREFETCH = 1,
	parameter ENABLE_BANKED_GATHER = 1
) (
	input wire clk, rst,
	input wire reg_valid,
	input wire [7:0] reg_addr,
	input wire [31:0] reg_wdata,
	input wire [3:0] reg_wstrb,
	output wire reg_ready,
	output wire [31:0] reg_rdata,
	output wire dma_valid,
	output wire [31:0] dma_addr, dma_wdata,
	output wire [3:0] dma_wstrb,
	input wire dma_ready,
	input wire [31:0] dma_rdata,

	// Pool owns a separate register window and DMA request channel.
	input wire pool_reg_valid,
	output wire pool_reg_ready,
	output wire [31:0] pool_reg_rdata,
	output wire pool_dma_valid,
	output wire [31:0] pool_dma_addr, pool_dma_wdata,
	output wire [3:0] pool_dma_wstrb,
	input wire pool_dma_ready,
	input wire [31:0] pool_dma_rdata
);

	det_conv_scheduler #(
		.ENABLE_PREFETCH(ENABLE_PREFETCH),
		.ENABLE_BANKED_GATHER(ENABLE_BANKED_GATHER)
	) conv_engine (
		.clk(clk),
		.rst(rst),
		.reg_valid(reg_valid),
		.reg_addr(reg_addr),
		.reg_wdata(reg_wdata),
		.reg_wstrb(reg_wstrb),
		.reg_ready(reg_ready),
		.reg_rdata(reg_rdata),
		.dma_valid(dma_valid),
		.dma_addr(dma_addr),
		.dma_wdata(dma_wdata),
		.dma_wstrb(dma_wstrb),
		.dma_ready(dma_ready),
		.dma_rdata(dma_rdata)
	);

	pool_accelerator pool_engine (
		.clk(clk),
		.rst(rst),
		.reg_valid(pool_reg_valid),
		.reg_addr(reg_addr),
		.reg_wdata(reg_wdata),
		.reg_wstrb(reg_wstrb),
		.reg_ready(pool_reg_ready),
		.reg_rdata(pool_reg_rdata),
		.dma_valid(pool_dma_valid),
		.dma_addr(pool_dma_addr),
		.dma_wdata(pool_dma_wdata),
		.dma_wstrb(pool_dma_wstrb),
		.dma_ready(pool_dma_ready),
		.dma_rdata(pool_dma_rdata)
	);
endmodule
