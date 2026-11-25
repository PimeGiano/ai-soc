`timescale 1ns / 1ps
module det_conv_datapath (
	input wire clk, rst, clear, restore, step,
	input wire [3:0] ri,
	input wire signed [31:0] restore_data,
	input wire [31:0] avec, bvec,
	input wire [639:0] quant_params,
	input wire p_save, result_save,
	input wire [9:0] p_read_index, p_write_index, result_index, output_index,
	input wire [1:0] result_lane,
	output wire signed [31:0] p_read_data,
	output wire [31:0] output_word,
	output wire bias_overflow
);

	wire [31:0] qp[0:19];
	for (genvar i = 0; i < 20; i = i + 1) begin : unpack_qp
		assign qp[i] = quant_params[32 * i +: 32];
	end

	reg [31:0] obuf[0:1023];
	reg signed [31:0] psum[0:1023];
	wire signed [31:0] core_result;
	conv_core core (
		.clk(clk),
		.rst(rst),
		.clear(clear),
		.restore(restore),
		.index(ri),
		.restore_data(restore_data),
		.step(step),
		.a_vector(avec),
		.b_vector(bvec),
		.result(core_result)
	);
	wire signed [63:0] biased = $signed({{32{core_result[31]}}, core_result}) +
								$signed({{32{qp[int'(ri[1:0]) * 5][31]}}, qp[int'(ri[1:0]) * 5]});
	wire [30:0] qmult = biased < 0 ? qp[int'(ri[1:0]) * 5 + 3][30:0] : qp[int'(ri[1:0]) * 5 + 1][30:0];
	wire [5:0] qshift = biased < 0 ? qp[int'(ri[1:0]) * 5 + 4][5:0] : qp[int'(ri[1:0]) * 5 + 2][5:0];
	wire signed [7:0] qresult;
	requant output_q (
		.value(biased[31:0]),
		.multiplier(qmult),
		.shift(qshift),
		.result(qresult)
	);

	assign bias_overflow = biased > 64'sh7fffffff || biased < -64'sh80000000;
	assign p_read_data = psum[p_read_index];
	assign output_word = obuf[output_index];

	always @(posedge clk) begin
		if (!rst && p_save)
			psum[p_write_index] <= core_result;
		if (!rst && result_save && !bias_overflow)
			for (integer byte_lane = 0; byte_lane < 4; byte_lane = byte_lane + 1)
				if (result_lane == 2'(byte_lane))
					obuf[result_index][8 * byte_lane +: 8] <= qresult;
	end
endmodule
