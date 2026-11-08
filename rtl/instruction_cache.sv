`timescale 1ns / 1ps

// 1KiB direct-mapped instruction cache for the 64KiB program window.
// Accelerator DMA cannot write this window. CPU stores invalidate their line,
// including partial stores, so executable RAM never retains stale instructions.
module instruction_cache (
	input wire clk, rst,
	input wire cpu_valid, cpu_instr,
	input wire [31:0] cpu_addr,
	input wire [3:0] cpu_wstrb,
	output wire cpu_ready,
	output wire [31:0] cpu_rdata,
	output wire bus_valid,
	input wire bus_ready,
	input wire [31:0] bus_rdata
);
	reg [31:0] words[0:255];
	reg [5:0] tags[0:255];
	reg [255:0] valid;
	wire program_window = cpu_addr[31:16] == 0;
	wire [7:0] index = cpu_addr[9:2];
	wire hit = cpu_valid && cpu_instr && program_window && cpu_wstrb == 0 && cpu_addr[1:0] == 0 &&
		valid[index] && tags[index] == cpu_addr[15:10];

	assign bus_valid = cpu_valid && !hit && !rst;
	assign cpu_ready = !rst && (hit || bus_ready);
	assign cpu_rdata = hit ? words[index] : bus_rdata;

	always @(posedge clk) begin
		if (rst)
			valid <= 0;
		else if (cpu_valid && bus_ready && program_window) begin
			if (cpu_wstrb != 0)
				valid[index] <= 0;
			else if (cpu_instr) begin
				words[index] <= bus_rdata;
				tags[index] <= cpu_addr[15:10];
				valid[index] <= 1;
			end
		end
	end
endmodule
