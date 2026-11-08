`timescale 1ns / 1ps

// One tile ahead, only across input-channel blocks of the same spatial/OC tile.
// Both X and W are prefetched. Fused X uses virtual dual-source addressing
// and the same integer requant primitive; no full intermediate tensor is stored.
module tile_prefetch (
	input wire clk, rst, start, consume,
	input wire fused,
	input wire [31:0] src, weight,
	input wire [31:0] src0, src1, width0, width1, channels0, channels1, order,
	input wire [30:0] multiplier0, multiplier1,
	input wire [5:0] shift0, shift1,
	input wire [31:0] height, width, cin, cout,
	input wire [31:0] kh, kw, tic, toc,
	input wire [31:0] next_ic, oc, xh, xw,
	input wire signed [31:0] ytop, xtop,
	output wire busy,
	output reg done,
	output wire read_valid,
	output wire [31:0] read_addr,
	input wire read_ready,
	input wire [31:0] read_data,
	output wire x_write, w_write,
	output wire [12:0] write_index,
	output wire [31:0] write_data,
	output wire [3:0] write_strobe
);
	typedef enum logic [2:0] {IDLE, W_SCAN, X_SCAN, REQUEST, STORE} state_t;
	state_t state;
	reg target_x;
	reg [31:0] index, request_addr, sample_word;
	reg [2:0] advance;
	// Four cached words retain one channel-block pixel while virtual 2x
	// upsampling revisits it. The cache is flushed at each prefetch start.
	reg [27:0] cache_tag[0:3];
	reg [31:0] cache_data[0:3];
	reg [3:0] cache_valid;
	integer ksize, total, ci, co, local_c, pixel, iy, ix, global_c, source_c;
	reg low_source;
	reg invalid_sample, full_word;
	reg [31:0] sample_addr;

	function automatic integer positive (
		input [31:0] value
	);
		positive = value == 0 ? 1 : int'(value);
	endfunction

	always @* begin
		ksize = int'(kh * kw * tic);
		ci = int'(cin) - int'(next_ic);
		co = int'(cout) - int'(oc);
		local_c = int'(index) % positive(tic);
		pixel = int'(index) / positive(tic);
		iy = ytop + pixel / positive(xw);
		ix = xtop + pixel % positive(xw);
		global_c = int'(next_ic) + local_c;
		low_source = order == 0 ? global_c < int'(channels0) : global_c >= int'(channels1);
		source_c = global_c - (low_source ? (order == 0 ? 0 : int'(channels1)) :
			(order == 0 ? int'(channels0) : 0));
		if (target_x) begin
			total = int'(xh * xw * tic);
			invalid_sample = iy < 0 || iy >= int'(height) || ix < 0 || ix >= int'(width) || local_c >= ci;
			sample_addr = src + 32'((iy * int'(width) + ix) * int'(cin) + int'(next_ic) + local_c);
			if (fused)
				sample_addr = low_source
					? src0 + 32'(((iy / 2) * int'(width0) + ix / 2) * int'(channels0) + source_c)
					: src1 + 32'((iy * int'(width1) + ix) * int'(channels1) + source_c);
		end else begin
			total = ksize * int'(toc);
			invalid_sample = int'(index) / positive(32'(ksize)) >= co || local_c >= ci;
			sample_addr = weight + 32'(((int'(oc) + int'(index) / positive(32'(ksize))) * int'(kh * kw) +
				(int'(index) / positive(tic)) % positive(kh * kw)) * int'(cin) + int'(next_ic) + local_c);
		end
		// Never cross a channel-block boundary or read beyond valid channels.
		full_word = !(target_x && fused) && index[1:0] == 0 && (invalid_sample ||
			(sample_addr[1:0] == 0 && local_c + 4 <= ci));
	end

	assign busy = state != IDLE;
	assign read_valid = state == REQUEST && !rst;
	assign read_addr = {request_addr[31:2], 2'b00};
	assign x_write = state == STORE && target_x && !rst;
	assign w_write = state == STORE && !target_x && !rst;
	assign write_index = index[12:0];
	wire signed [7:0] raw_sample = sample_word[8 * request_addr[1:0] +: 8];
	wire signed [7:0] converted;
	requant input_quant (
		.value({{24{raw_sample[7]}}, raw_sample}),
		.multiplier(low_source ? multiplier0 : multiplier1),
		.shift(low_source ? shift0 : shift1),
		.result(converted)
	);
	assign write_data = target_x && fused ? {4{converted}} :
		(advance == 4 ? sample_word : {4{raw_sample}});
	assign write_strobe = advance == 4 ? 4'b1111 : (4'b0001 << index[1:0]);

	always @(posedge clk) begin
		if (rst) begin
			state <= IDLE;
			done <= 0;
			target_x <= 0;
			index <= 0;
			request_addr <= 0;
			sample_word <= 0;
			advance <= 1;
			cache_valid <= 0;
		end else begin
			if (consume)
				done <= 0;
			case (state)
				IDLE:
					if (start && !done) begin
						target_x <= 0;
						index <= 0;
						cache_valid <= 0;
						state <= W_SCAN;
					end

				W_SCAN, X_SCAN: begin
					advance <= full_word ? 3'd4 : 3'd1;
					request_addr <= sample_addr;
					if (invalid_sample) begin
						sample_word <= 0;
						state <= STORE;
					end else if (cache_valid[sample_addr[3:2]] && cache_tag[sample_addr[3:2]] == sample_addr[31:4]) begin
						sample_word <= cache_data[sample_addr[3:2]];
						state <= STORE;
					end else
						state <= REQUEST;
				end

				REQUEST:
					if (read_ready) begin
						sample_word <= read_data;
						cache_data[request_addr[3:2]] <= read_data;
						cache_tag[request_addr[3:2]] <= request_addr[31:4];
						cache_valid[request_addr[3:2]] <= 1;
						state <= STORE;
					end

				STORE:
					if (index + {29'b0, advance} == 32'(total)) begin
						if (!target_x) begin
							target_x <= 1;
							index <= 0;
							state <= X_SCAN;
						end else begin
							done <= 1;
							state <= IDLE;
						end
					end else begin
						index <= index + {29'b0, advance};
						state <= target_x ? X_SCAN : W_SCAN;
					end

				default: state <= IDLE;
			endcase
		end
	end

endmodule
