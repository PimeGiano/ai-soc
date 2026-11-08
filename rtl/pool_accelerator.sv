`timescale 1ns / 1ps

// NHWC 2x2 maxpool, stride 1/2, Darknet right/bottom padding = -127.
// Four INT8 channels per word when aligned; byte fallback for arbitrary C.
module pool_accelerator (
	input wire clk, rst,
	input wire reg_valid,
	input wire [7:0] reg_addr,
	input wire [31:0] reg_wdata,
	input wire [3:0] reg_wstrb,
	output wire reg_ready,
	output reg [31:0] reg_rdata,
	output wire dma_valid,
	output wire [31:0] dma_addr, dma_wdata,
	output wire [3:0] dma_wstrb,
	input wire dma_ready,
	input wire [31:0] dma_rdata
);
	`include "pool_spec.vh"

	typedef enum logic [2:0] {IDLE, BEGIN_PIXEL, SAMPLE, READ, NEXT_SAMPLE, WRITE} state_t;
	state_t state;
	reg [31:0] src, dst, height, width, channels, stride;
	reg done, error_flag;
	reg [31:0] oy, ox, channel;
	reg [1:0] sample_index;
	reg [31:0] maximum;
	reg [63:0] cycles;
	wire busy = state != IDLE;
	wire [31:0] ho = stride == 2 ? ((height - 1) >> 1) + 1 : height;
	wire [31:0] wo = stride == 2 ? ((width - 1) >> 1) + 1 : width;
	wire [31:0] iy = oy * stride + {31'b0, sample_index[1]};
	wire [31:0] ix = ox * stride + {31'b0, sample_index[0]};
	wire [31:0] source_address = src + (iy * width + ix) * channels + channel;
	wire [31:0] output_address = dst + (oy * wo + ox) * channels + channel;
	wire packed_word = channels[1:0] == 0 && channel + 4 <= channels;
	wire [31:0] advance = packed_word ? 4 : 1;
	wire [31:0] sample_data = packed_word ? dma_rdata : (dma_rdata >> (8 * source_address[1:0]));
	wire [63:0] input_bytes = {32'b0, height} * {32'b0, width} * {32'b0, channels};
	wire [63:0] output_bytes = {32'b0, ho} * {32'b0, wo} * {32'b0, channels};
	wire bad = src[1:0] != 0 || dst[1:0] != 0 || height == 0 || height > 160 ||
		width == 0 || width > 160 || channels == 0 || channels > 1024 ||
		(stride != 1 && stride != 2) || src < 32'h01000000 || dst < 32'h01000000 ||
		{32'b0, src} + input_bytes > 64'h05000000 ||
		{32'b0, dst} + output_bytes > 64'h05000000 ||
		({32'b0, src} < {32'b0, dst} + output_bytes &&
		 {32'b0, dst} < {32'b0, src} + input_bytes);

	assign reg_ready = reg_valid && !rst;
	always @* begin
		reg_rdata = 0;
		case (reg_addr)
			POOL_REG_SRC: reg_rdata = src;
			POOL_REG_DST: reg_rdata = dst;
			POOL_REG_H: reg_rdata = height;
			POOL_REG_W: reg_rdata = width;
			POOL_REG_C: reg_rdata = channels;
			POOL_REG_STRIDE: reg_rdata = stride;
			POOL_REG_STATUS: reg_rdata = {29'b0, error_flag, done, busy};
			POOL_REG_CYCLES_LO: reg_rdata = cycles[31:0];
			POOL_REG_CYCLES_HI: reg_rdata = cycles[63:32];
			default: reg_rdata = 0;
		endcase
	end

	assign dma_valid = !rst && (state == READ || state == WRITE);
	assign dma_addr = state == WRITE ? {output_address[31:2], 2'b00} : {source_address[31:2], 2'b00};
	assign dma_wstrb = state != WRITE ? 4'b0000 :
		(packed_word ? 4'b1111 : (4'b0001 << output_address[1:0]));
	assign dma_wdata = packed_word ? maximum : ({24'b0, maximum[7:0]} << (8 * output_address[1:0]));

	always @(posedge clk) begin
		if (rst) begin
			state <= IDLE;
			src <= 0;
			dst <= 0;
			height <= 0;
			width <= 0;
			channels <= 0;
			stride <= 1;
			done <= 0;
			error_flag <= 0;
			oy <= 0;
			ox <= 0;
			channel <= 0;
			sample_index <= 0;
			maximum <= 32'h81818181;
			cycles <= 0;
		end else begin
			if (busy)
				cycles <= cycles + 1;
			case (state)
				IDLE: begin
				end
				BEGIN_PIXEL: begin
					maximum <= 32'h81818181;
					sample_index <= 0;
					state <= SAMPLE;
				end
				SAMPLE:
					state <= iy < height && ix < width ? READ : NEXT_SAMPLE;
				READ:
					if (dma_ready) begin
						for (integer lane = 0; lane < 4; lane = lane + 1)
							if ((packed_word || lane == 0) &&
								$signed(sample_data[lane * 8 +: 8]) > $signed(maximum[lane * 8 +: 8]))
								maximum[lane * 8 +: 8] <= sample_data[lane * 8 +: 8];
						state <= NEXT_SAMPLE;
					end
				NEXT_SAMPLE:
					if (sample_index == 3)
						state <= WRITE;
					else begin
						sample_index <= sample_index + 1;
						state <= SAMPLE;
					end
				WRITE:
					if (dma_ready) begin
						if (channel + advance < channels)
							channel <= channel + advance;
						else begin
							channel <= 0;
							if (ox + 1 < wo)
								ox <= ox + 1;
							else begin
								ox <= 0;
								oy <= oy + 1;
							end
						end
						if (channel + advance >= channels && ox + 1 >= wo && oy + 1 >= ho) begin
							done <= 1;
							state <= IDLE;
						end else
							state <= BEGIN_PIXEL;
					end
				default: state <= IDLE;
			endcase
			if (reg_valid && reg_wstrb != 0) begin
				if (reg_wstrb != 15 || reg_addr[1:0] != 0 || busy)
					error_flag <= 1;
				else case (reg_addr)
					POOL_REG_SRC: src <= reg_wdata;
					POOL_REG_DST: dst <= reg_wdata;
					POOL_REG_H: height <= reg_wdata;
					POOL_REG_W: width <= reg_wdata;
					POOL_REG_C: channels <= reg_wdata;
					POOL_REG_STRIDE: stride <= reg_wdata;
					POOL_REG_START:
						if (reg_wdata == 1) begin
							done <= 0;
							error_flag <= bad;
							cycles <= 0;
							if (!bad) begin
								oy <= 0;
								ox <= 0;
								channel <= 0;
								state <= BEGIN_PIXEL;
							end
						end
					default: begin
					end
				endcase
			end
		end
	end
endmodule
