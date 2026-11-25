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

	typedef enum logic [1:0] {IDLE, SAMPLE, SCALE, WRITE} state_t;
	state_t state;
	reg [31:0] src, dst, height, width, channels, stride;
	reg [31:0] dst_pitch, q_mult, q_shift;
	reg strided_output, apply_scale;
	reg done, error_flag;
	reg [31:0] oy, ox, channel;
	reg [1:0] sample_index;
	reg [1:0] scale_lane;
	localparam [31:0] PAD = 32'h81818181;
	localparam [31:0] INT8_MIN = 32'h80808080;
	reg [31:0] maximum, right_maximum;
	reg [63:0] cycles;
	wire busy = state != IDLE;
	wire [31:0] ho = stride == 2 ? ((height - 1) >> 1) + 1 : height;
	wire [31:0] wo = stride == 2 ? ((width - 1) >> 1) + 1 : width;
	// Visit each column top to bottom. For stride 1 the next window can
	// start from this window's right-column maximum.
	wire [31:0] iy = oy * stride + {31'b0, sample_index[0]};
	wire [31:0] ix = ox * stride + {31'b0, sample_index[1]};
	wire sample_inside = iy < height && ix < width;
	wire [31:0] source_address = src + (iy * width + ix) * channels + channel;
	wire [31:0] output_pitch = strided_output ? dst_pitch : channels;
	wire [31:0] output_address = dst + (oy * wo + ox) * output_pitch + channel;
	wire packed_word = channels[1:0] == 0 && output_pitch[1:0] == 0 && channel + 4 <= channels;
	wire [31:0] advance = packed_word ? 4 : 1;
	wire last_channel = channel + advance >= channels;
	wire last_x = ox + 1 >= wo;
	wire last_y = oy + 1 >= ho;
	wire reuse_column = stride == 1 && !last_x;
	wire [31:0] sample_data = packed_word ? dma_rdata : (dma_rdata >> (8 * source_address[1:0]));
	wire [31:0] minimum = apply_scale ? INT8_MIN : PAD;
	wire start_strided = reg_wdata == 2;
	wire start_scaled = start_strided && !(q_shift < 31 && q_mult == (32'd1 << q_shift));
	wire [31:0] start_pitch = start_strided ? dst_pitch : channels;
	wire [63:0] output_pixels = {32'b0, ho} * {32'b0, wo};
	wire [63:0] input_bytes = {32'b0, height} * {32'b0, width} * {32'b0, channels};
	wire [63:0] output_bytes = (output_pixels - 64'd1) * {32'b0, start_pitch} + {32'b0, channels};
	wire bad = src[1:0] != 0 || dst[1:0] != 0 || height == 0 || height > 160 ||
		width == 0 || width > 160 || channels == 0 || channels > 1024 ||
		(start_strided && (dst_pitch < channels || dst_pitch > 1024 || q_mult[31] || q_shift > 62)) ||
		(stride != 1 && stride != 2) || src < 32'h01000000 || dst < 32'h01000000 ||
		{32'b0, src} + input_bytes > 64'h05000000 ||
		{32'b0, dst} + output_bytes > 64'h05000000 ||
		({32'b0, src} < {32'b0, dst} + output_bytes &&
		 {32'b0, dst} < {32'b0, src} + input_bytes);

	wire signed [7:0] raw_max = maximum[8 * scale_lane +: 8];
	wire signed [7:0] scaled_max;
	requant output_scale (
		.value({{24{raw_max[7]}}, raw_max}),
		.multiplier(q_mult[30:0]),
		.shift(q_shift[5:0]),
		.result(scaled_max)
	);

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
			POOL_REG_DST_PITCH: reg_rdata = dst_pitch;
			POOL_REG_Q_MULT: reg_rdata = q_mult;
			POOL_REG_Q_SHIFT: reg_rdata = q_shift;
			POOL_REG_CAPABILITIES: reg_rdata = 1;
			default: reg_rdata = 0;
		endcase
	end

	assign dma_valid = !rst && ((state == SAMPLE && sample_inside) || state == WRITE);
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
			dst_pitch <= 0;
			q_mult <= 0;
			q_shift <= 0;
			strided_output <= 0;
			apply_scale <= 0;
			done <= 0;
			error_flag <= 0;
			oy <= 0;
			ox <= 0;
			channel <= 0;
			sample_index <= 0;
			scale_lane <= 0;
			maximum <= PAD;
			right_maximum <= PAD;
			cycles <= 0;
		end else begin
			if (busy)
				cycles <= cycles + 1;
			case (state)
				IDLE: begin
				end
				SAMPLE:
					if (!sample_inside || dma_ready) begin
						if (sample_inside)
							for (integer lane = 0; lane < 4; lane = lane + 1)
								if (packed_word || lane == 0) begin
									if ($signed(sample_data[lane * 8 +: 8]) >
										$signed(maximum[lane * 8 +: 8]))
										maximum[lane * 8 +: 8] <= sample_data[lane * 8 +: 8];
									if (sample_index[1] && reuse_column &&
										$signed(sample_data[lane * 8 +: 8]) >
										$signed(right_maximum[lane * 8 +: 8]))
										right_maximum[lane * 8 +: 8] <= sample_data[lane * 8 +: 8];
								end
						if (sample_index == 3) begin
							scale_lane <= 0;
							state <= apply_scale ? SCALE : WRITE;
						end else
							sample_index <= sample_index + 1;
					end
				SCALE: begin
					maximum[8 * scale_lane +: 8] <= scaled_max;
					if (!packed_word || scale_lane == 3)
						state <= WRITE;
					else
						scale_lane <= scale_lane + 1;
				end
				WRITE:
					if (dma_ready) begin
						if (stride == 2 || last_x)
							channel <= last_channel ? 0 : channel + advance;
						if (stride == 1 || last_channel)
							ox <= last_x ? 0 : ox + 1;
						if (last_channel && last_x)
							oy <= oy + 1;
						if (last_channel && last_x && last_y) begin
							done <= 1;
							state <= IDLE;
						end else begin
							maximum <= reuse_column ? right_maximum : minimum;
							right_maximum <= minimum;
							sample_index <= reuse_column ? 2'd2 : 2'd0;
							state <= SAMPLE;
						end
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
					POOL_REG_DST_PITCH: dst_pitch <= reg_wdata;
					POOL_REG_Q_MULT: q_mult <= reg_wdata;
					POOL_REG_Q_SHIFT: q_shift <= reg_wdata;
					POOL_REG_START:
						if (reg_wdata == 1 || start_strided) begin
							done <= 0;
							error_flag <= bad;
							cycles <= 0;
							if (!bad) begin
								oy <= 0;
								ox <= 0;
								channel <= 0;
								strided_output <= start_strided;
								apply_scale <= start_scaled;
								maximum <= start_scaled ? INT8_MIN : PAD;
								right_maximum <= start_scaled ? INT8_MIN : PAD;
									sample_index <= 0;
									state <= SAMPLE;
							end
						end
					default: begin
					end
				endcase
			end
		end
	end
endmodule
