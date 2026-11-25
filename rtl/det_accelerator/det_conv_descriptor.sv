`timescale 1ns / 1ps
module det_conv_descriptor (
	input wire [1023:0] descriptor,
	input wire [511:0] fusion,
	input wire [31:0] desc_addr,
	output wire desc_addr_ok, fuse_addr_ok,
	output reg config_bad, addr_bad
);
	/* verilator lint_off UNUSEDPARAM */
`include "spec.vh"
	/* verilator lint_on UNUSEDPARAM */
	localparam [31:0] DATA_BASE = 32'h01000000, DATA_END = 32'h05000000;

	wire [31:0] d[0:31];
	for (genvar i = 0; i < 32; i = i + 1) begin : unpack_d
		assign d[i] = descriptor[32 * i +: 32];
	end
	wire [31:0] f[0:15];
	for (genvar i = 0; i < 16; i = i + 1) begin : unpack_f
		assign f[i] = fusion[32 * i +: 32];
	end
	wire fused = d[D_FLAGS][2];
	reg [63:0] xbytes, wbytes, pbytes;
	assign desc_addr_ok = desc_addr[3:0] == 0 && in_range(desc_addr, 128);
	assign fuse_addr_ok = d[D_FUSE_ADDR][3:0] == 0 && in_range(d[D_FUSE_ADDR], 64);

	function automatic bit in_range (
		input [31:0] a,
		input [63:0] n
	);

		in_range =
			(n != 0 && a >= DATA_BASE && {32'b0, a} + n <= {32'b0, DATA_END} && a[1:0] == 0);
	endfunction

	function automatic bit overlap (
		input [31:0] a,
		input [63:0] an,
		input [31:0] b,
		input [63:0] bn
	);

		overlap = ({32'b0, a} < {32'b0, b} + bn && {32'b0, b} < {32'b0, a} + an);
	endfunction

	wire [63:0] insize = {32'b0, d[D_H]} * {32'b0, d[D_W]} * {32'b0, d[D_CIN]};
	wire [63:0] weight_size = {32'b0, d[D_COUT]} * {32'b0, d[D_KH]} * {32'b0, d[D_KW]} *
						{32'b0, d[D_CIN]};
	wire [63:0] output_size = {32'b0, d[D_HOUT]} * {32'b0, d[D_WOUT]} * {32'b0, d[D_COUT]};
	wire [63:0] param_size = 64'd20 * {32'b0, d[D_COUT]};
	wire [63:0] src0_size = {32'b0, f[F_H0]} * {32'b0, f[F_W0]} * {32'b0, f[F_C0]};
	wire [63:0] src1_size = {32'b0, f[F_H1]} * {32'b0, f[F_W1]} * {32'b0, f[F_C1]};

	always @* begin
		xbytes = ((64'(d[D_TH]) - 1) * 64'(d[D_SH]) + 64'(d[D_KH])) *
			((64'(d[D_TW]) - 1) * 64'(d[D_SW]) + 64'(d[D_KW])) * 64'(d[D_TIC]);
		wbytes = 64'(d[D_KH]) * 64'(d[D_KW]) * 64'(d[D_TIC]) * 64'(d[D_TOC]);
		pbytes = 64'(d[D_TH]) * 64'(d[D_TW]) * 64'(d[D_TOC]) * 4;

		config_bad = d[D_H] < 1 || d[D_H] > 160 || d[D_W] < 1 || d[D_W] > 160 || d[D_CIN] < 1 ||
			d[D_CIN] > 1024 || d[D_COUT] < 1 || d[D_COUT] > 1024 ||
			!(d[D_KH] == 1 || d[D_KH] == 3) || d[D_KW] != d[D_KH] ||
			!(d[D_SH] == 1 || d[D_SH] == 2) || d[D_SW] != d[D_SH] || d[D_PT] > 1 || d[D_PB] > 1 ||
			d[D_PL] > 1 || d[D_PR] > 1 || d[D_HOUT] < 1 || d[D_WOUT] < 1 ||
			(int'(d[D_H]) + int'(d[D_PT]) + int'(d[D_PB]) - int'(d[D_KH])) < 0 ||
			(int'(d[D_W]) + int'(d[D_PL]) + int'(d[D_PR]) - int'(d[D_KW])) < 0 ||
			int'(d[D_HOUT]) !=
				(int'(d[D_H]) + int'(d[D_PT]) + int'(d[D_PB]) - int'(d[D_KH])) /
						int'(d[D_SH] | 1 * (d[D_SH] == 0)) +
					1 ||
			int'(d[D_WOUT]) !=
				(int'(d[D_W]) + int'(d[D_PL]) + int'(d[D_PR]) - int'(d[D_KW])) /
						int'(d[D_SW] | 1 * (d[D_SW] == 0)) +
					1 ||
			d[D_TH] < 1 || d[D_TH] > 16 || d[D_TW] < 1 || d[D_TW] > 16 ||
			!(d[D_TIC] == 4 || d[D_TIC] == 8 || d[D_TIC] == 16) ||
			!(d[D_TOC] == 4 || d[D_TOC] == 8 || d[D_TOC] == 16) || xbytes > 8192 || wbytes > 8192 ||
			pbytes > 4096 || d[D_ACT] > 2 || (d[D_FLAGS] & 32'hfffffffa) != 0 || !d[D_FLAGS][0] ||
			(!fused && d[D_FUSE_ADDR] != 0);
		for (integer i = 25; i < 32; i = i + 1)
			if (d[i] != 0)
				config_bad = 1;
		if (fused) begin
			if (d[D_SRC] != 0 || {32'b0, f[F_H0]} * 2 != {32'b0, d[D_H]} || f[F_H1] != d[D_H] ||
				{32'b0, f[F_W0]} * 2 != {32'b0, d[D_W]} || f[F_W1] != d[D_W] ||
				{32'b0, f[F_C0]} + {32'b0, f[F_C1]} != {32'b0, d[D_CIN]} || f[F_C0] == 0 ||
				f[F_C1] == 0 || f[F_R0] != 2 || f[F_R1] != 1 || f[F_ORDER] > 1 ||
				f[F_RESERVED] != 0 || f[F_M0][31] || f[F_M1][31] || f[F_S0] > 62 || f[F_S1] > 62)
				config_bad = 1;
		end

		addr_bad = !in_range(d[D_WEIGHT], weight_size) || !in_range(d[D_DST], output_size) ||
			!in_range(d[D_QPARAM], param_size) ||
			overlap(d[D_DST], output_size, d[D_WEIGHT], weight_size) ||
			overlap(d[D_DST], output_size, d[D_QPARAM], param_size) ||
			overlap(d[D_DST], output_size, desc_addr, 128);
		if (fused)
			addr_bad = addr_bad || !in_range(f[F_SRC0], src0_size) ||
				!in_range(f[F_SRC1], src1_size) ||
				overlap(d[D_DST], output_size, f[F_SRC0], src0_size) ||
				overlap(d[D_DST], output_size, f[F_SRC1], src1_size) ||
				overlap(d[D_DST], output_size, d[D_FUSE_ADDR], 64);
		else
			addr_bad = addr_bad || !in_range(d[D_SRC], insize) ||
				overlap(d[D_DST], output_size, d[D_SRC], insize);
	end
endmodule
