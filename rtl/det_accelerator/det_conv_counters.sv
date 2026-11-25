`timescale 1ns / 1ps

module det_conv_counters (
	input wire clk, rst, start_job,
	input wire [7:0] reg_addr,
	input wire [31:0] desc_addr, error_code,
	input wire busy, done_flag, error_flag, reject_flag,
	input wire [2:0] phase,
	input wire gather, gather_parallel, core_step,
	input wire prefetch_busy, waiting_prefetch,
	input wire dma_wait, read_word, write_word,
	input wire [2:0] write_count,
	output reg [31:0] reg_rdata
);
	/* verilator lint_off UNUSEDPARAM */
`include "spec.vh"
	/* verilator lint_on UNUSEDPARAM */

	reg [63:0] job_cycles, compute_cycles, read_words, write_bytes, wait_cycles;
	reg [63:0] phase_cycles[0:5];
	reg [63:0] fast_gather, serial_gather, prefetch_active, prefetch_mac, prefetch_wait;

	always @* begin
		reg_rdata = 0;
		case (reg_addr)
			REG_STATUS:
				reg_rdata = {28'b0, reject_flag, error_flag, done_flag, busy};
			REG_DESC_ADDR:
				reg_rdata = desc_addr;
			REG_ERROR_CODE:
				reg_rdata = error_code;
			REG_JOB_CYCLES_LO:
				reg_rdata = job_cycles[31:0];
			REG_JOB_CYCLES_HI:
				reg_rdata = job_cycles[63:32];
			REG_COMPUTE_CYCLES_LO:
				reg_rdata = compute_cycles[31:0];
			REG_COMPUTE_CYCLES_HI:
				reg_rdata = compute_cycles[63:32];
			REG_READ_WORDS_LO:
				reg_rdata = read_words[31:0];
			REG_READ_WORDS_HI:
				reg_rdata = read_words[63:32];
			REG_WRITE_BYTES_LO:
				reg_rdata = write_bytes[31:0];
			REG_WRITE_BYTES_HI:
				reg_rdata = write_bytes[63:32];
			REG_DMA_WAIT_LO:
				reg_rdata = wait_cycles[31:0];
			REG_DMA_WAIT_HI:
				reg_rdata = wait_cycles[63:32];
			REG_VERSION:
				reg_rdata = DET_INTERFACE_VERSION;
			REG_LOAD_CYCLES_LO: reg_rdata = phase_cycles[0][31:0];
			REG_LOAD_CYCLES_HI: reg_rdata = phase_cycles[0][63:32];
			REG_GATHER_CYCLES_LO: reg_rdata = phase_cycles[1][31:0];
			REG_GATHER_CYCLES_HI: reg_rdata = phase_cycles[1][63:32];
			REG_PARTIAL_CYCLES_LO: reg_rdata = phase_cycles[2][31:0];
			REG_PARTIAL_CYCLES_HI: reg_rdata = phase_cycles[2][63:32];
			REG_PARAM_CYCLES_LO: reg_rdata = phase_cycles[3][31:0];
			REG_PARAM_CYCLES_HI: reg_rdata = phase_cycles[3][63:32];
			REG_OUTPUT_CYCLES_LO: reg_rdata = phase_cycles[4][31:0];
			REG_OUTPUT_CYCLES_HI: reg_rdata = phase_cycles[4][63:32];
			REG_CONTROL_CYCLES_LO: reg_rdata = phase_cycles[5][31:0];
			REG_CONTROL_CYCLES_HI: reg_rdata = phase_cycles[5][63:32];
			REG_FAST_GATHER_LO: reg_rdata = fast_gather[31:0];
			REG_FAST_GATHER_HI: reg_rdata = fast_gather[63:32];
			REG_SERIAL_GATHER_LO: reg_rdata = serial_gather[31:0];
			REG_SERIAL_GATHER_HI: reg_rdata = serial_gather[63:32];
			REG_PREFETCH_ACTIVE_LO: reg_rdata = prefetch_active[31:0];
			REG_PREFETCH_ACTIVE_HI: reg_rdata = prefetch_active[63:32];
			REG_PREFETCH_MAC_LO: reg_rdata = prefetch_mac[31:0];
			REG_PREFETCH_MAC_HI: reg_rdata = prefetch_mac[63:32];
			REG_PREFETCH_WAIT_LO: reg_rdata = prefetch_wait[31:0];
			REG_PREFETCH_WAIT_HI: reg_rdata = prefetch_wait[63:32];
			default:
				reg_rdata = 0;
		endcase
	end

	always @(posedge clk) begin
		if (rst || start_job) begin
			job_cycles <= 0;
			compute_cycles <= 0;
			read_words <= 0;
			write_bytes <= 0;
			wait_cycles <= 0;
			fast_gather <= 0;
			serial_gather <= 0;
			prefetch_active <= 0;
			prefetch_mac <= 0;
			prefetch_wait <= 0;
			for (integer i = 0; i < 6; i = i + 1)
				phase_cycles[i] <= 0;
		end else begin
			if (busy) begin
				job_cycles <= job_cycles + 1;
				phase_cycles[phase] <= phase_cycles[phase] + 1;
			end
			if (busy && gather) begin
				if (gather_parallel)
					fast_gather <= fast_gather + 1;
				else
					serial_gather <= serial_gather + 1;
			end
			if (busy && prefetch_busy)
				prefetch_active <= prefetch_active + 1;
			if (busy && prefetch_busy && core_step)
				prefetch_mac <= prefetch_mac + 1;
			if (busy && waiting_prefetch)
				prefetch_wait <= prefetch_wait + 1;

			if (core_step)
				compute_cycles <= compute_cycles + 1;
			if (dma_wait)
				wait_cycles <= wait_cycles + 1;
			if (read_word)
				read_words <= read_words + 1;
			if (write_word)
				write_bytes <= write_bytes + {61'b0, write_count};

		end
	end
endmodule
