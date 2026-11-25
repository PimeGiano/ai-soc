`timescale 1ns / 1ps
module det_conv_tile_buffer #(
	parameter ENABLE_BANKED_GATHER = 1
) (
	input wire clk, rst, active_slot,
	input wire [31:0] tic, kh, kw, stride_w, stride_h,
	input wire signed [31:0] th, tw, xh, xw, co_count,
	input wire signed [31:0] m0, n0, kpos, kc, kx, ky, lane,
	input wire x_write_valid, w_write_valid,
	input wire signed [31:0] x_write_index, w_write_index,
	input wire [31:0] x_write_data, w_write_data,
	input wire [3:0] x_write_strobe, w_write_strobe,
	input wire prefetch_x_write, prefetch_w_write,
	input wire [12:0] prefetch_write_index,
	input wire [31:0] prefetch_write_data,
	input wire [3:0] prefetch_write_strobe,
	output wire [2:0] channel_shift,
	output wire [31:0] tile_k,
	output reg gather_parallel,
	output reg [31:0] next_a, next_b
);
	function automatic integer imax (
		input integer a, b
	);

		imax = a > b ? a : b;
	endfunction
	assign channel_shift = tic == 16 ? 3'd4 : (tic == 8 ? 3'd3 : 3'd2);
	wire stride_shift = stride_w == 2;
	wire [31:0] bank_row_pixels = 32'(((xw + (4 << stride_shift) - 1) >> (2 + stride_shift)) << stride_shift);
	wire swizzled_x = 64'(bank_row_pixels) * 64'(xh) * {32'b0, tic} <= 2048;

	// A row-dependent bank rotation makes consecutive output positions
	// conflict-free even when a microtile crosses a short or odd row.
	// Padding is used only if every bank still fits 2KiB; otherwise the
	// compact linear layout and the conflict detector remain available.
	function automatic [1:0] x_bank (
		input integer byte_index
	);
		integer pixel, xx, yy;
		begin
			pixel = byte_index >> channel_shift;
			xx = pixel % imax(xw, 1);
			yy = pixel / imax(xw, 1);
			if (swizzled_x)
				x_bank = 2'((xx >> stride_shift) + (yy >> stride_shift) * tw);
			else
				x_bank = 2'(pixel >> stride_shift);
		end
	endfunction

	function automatic [8:0] x_address (
		input integer byte_index
	);
		integer pixel, packed_pixel, xx, yy;
		begin
			pixel = byte_index >> channel_shift;
			xx = pixel % imax(xw, 1);
			yy = pixel / imax(xw, 1);
			if (swizzled_x)
				packed_pixel = yy * int'(bank_row_pixels) +
					((xx >> (2 + stride_shift)) << stride_shift) + (xx & int'(stride_shift));
			else
				packed_pixel = ((pixel >> (2 + stride_shift)) << stride_shift) +
					(pixel & int'(stride_shift));
			x_address = 9'((packed_pixel << (channel_shift - 2)) +
				((byte_index & (int'(tic) - 1)) >> 2));
		end
	endfunction

	assign tile_k = kh * kw * tic;
	function automatic [1:0] w_bank (
		input integer byte_index
	);
		w_bank = 2'((byte_index / imax(int'(tile_k), 1)) % 4);
	endfunction

	function automatic [8:0] w_address (
		input integer byte_index
	);
		w_address = 9'((byte_index / imax(int'(tile_k), 1) / 4) * (int'(tile_k) / 4) +
			(byte_index % imax(int'(tile_k), 1)) / 4);
	endfunction

	reg [35:0] x_read_addr, w_read_addr;
	wire [127:0] x_read_data, w_read_data;
	wire [127:0] x_read_slot0, x_read_slot1, w_read_slot0, w_read_slot1;
	assign x_read_data = active_slot ? x_read_slot1 : x_read_slot0;
	assign w_read_data = active_slot ? w_read_slot1 : w_read_slot0;
	integer a_index[0:3];
	reg [1:0] a_bank[0:3];
	integer gather_x, gather_y;

	always @* begin
		gather_parallel = ENABLE_BANKED_GATHER != 0;
		for (integer r = 0; r < 4; r = r + 1) begin
			gather_x = ((m0 + r) % imax(tw, 1)) * int'(stride_w) + kx;
			gather_y = ((m0 + r) / imax(tw, 1)) * int'(stride_h) + ky;
			a_index[r] = (gather_y * xw + gather_x) * int'(tic) + kc;
			a_bank[r] = x_bank(a_index[r]);
		end
		for (integer r = 0; r < 4; r = r + 1)
			for (integer q = 0; q < r; q = q + 1)
				if (m0 + r < th * tw && m0 + q < th * tw && a_bank[r] == a_bank[q])
					gather_parallel = 0;

		x_read_addr = 0;
		w_read_addr = 0;
		for (integer r = 0; r < 4; r = r + 1) begin
			if (m0 + r < th * tw && (gather_parallel || lane == r))
				x_read_addr[a_bank[r] * 9 +: 9] = x_address(a_index[r]);
			w_read_addr[r * 9 +: 9] = 9'((n0 / 4) * (int'(tile_k) / 4) + kpos / 4);
		end
	end

	always @* begin
		next_a = 0;
		next_b = 0;
		for (integer r = 0; r < 4; r = r + 1) begin
			if (m0 + r < th * tw)
				next_a[r * 8 +: 8] = x_read_data[a_bank[r] * 32 + (kc % 4) * 8 +: 8];
			next_b[r * 8 +: 8] = n0 + r < co_count
				? w_read_data[r * 32 + (kpos % 4) * 8 +: 8] : 8'b0;
		end
	end

	for (genvar slot = 0; slot < 2; slot = slot + 1) begin : slots
		wire inactive = active_slot != slot;
		wire [127:0] xr, wr;
		banked_scratch input_store (
			.clk(clk),
			.write_valid(!rst && (inactive ? prefetch_x_write : x_write_valid)),
			.write_bank(inactive ? x_bank(int'({19'b0, prefetch_write_index})) : x_bank(x_write_index)),
			.write_addr(inactive ? x_address(int'({19'b0, prefetch_write_index})) : x_address(x_write_index)),
			.write_data(inactive ? prefetch_write_data : x_write_data),
			.write_strobe(inactive ? prefetch_write_strobe : x_write_strobe),
			.read_addr(x_read_addr),
			.read_data(xr)
		);
		banked_scratch weight_store (
			.clk(clk),
			.write_valid(!rst && (inactive ? prefetch_w_write : w_write_valid)),
			.write_bank(inactive ? w_bank(int'({19'b0, prefetch_write_index})) : w_bank(w_write_index)),
			.write_addr(inactive ? w_address(int'({19'b0, prefetch_write_index})) : w_address(w_write_index)),
			.write_data(inactive ? prefetch_write_data : w_write_data),
			.write_strobe(inactive ? prefetch_write_strobe : w_write_strobe),
			.read_addr(w_read_addr),
			.read_data(wr)
		);
		if (slot == 0) begin : first_slot
			assign x_read_slot0 = xr;
			assign w_read_slot0 = wr;
		end else begin : second_slot
			assign x_read_slot1 = xr;
			assign w_read_slot1 = wr;
		end
	end
endmodule
