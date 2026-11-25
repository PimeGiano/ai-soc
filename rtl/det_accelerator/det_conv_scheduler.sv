`timescale 1ns / 1ps
// Ping-pong X/W, each slot four-way banked: X 16KiB, W 16KiB, P/O 4KiB each.
// The scheduler prefetches the next input-channel block while computing.
module det_conv_scheduler #(
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
	input wire [31:0] dma_rdata
);

	/* verilator lint_off UNUSEDPARAM */
`include "spec.vh"
	/* verilator lint_on UNUSEDPARAM */

	typedef enum logic [5:0] {
		IDLE,
		DESC_REQ,
		DESC_GOT,
		FUSE_REQ,
		FUSE_GOT,
		CHECK_DESC,
		PARAM_REQ,
		PARAM_GOT,
		TILE_BEGIN,
		X_ZERO,
		SOURCE_BEGIN,
		SAMPLE_REQ,
		SAMPLE_GOT,
		CONVERT_IN,
		CONVERT_OUT,
		SCATTER,
		SAMPLE_NEXT,
		SOURCE_NEXT,
		W_REQ,
		W_GOT,
		MICRO_BEGIN,
		P_READ,
		P_RESTORE,
		GATHER_A,
		MAC_STEP,
		MICRO_PARAM_REQ,
		MICRO_PARAM_GOT,
		RESULT,
		P_SAVE,
		MICRO_NEXT,
		IC_NEXT,
		WRITE_OUT,
		TILE_NEXT,
		READ_DISPATCH,
		READ_BUS
	} state_t;

	state_t state, read_return;
	reg busy, done_flag, error_flag, reject_flag;
	reg [31:0] error_code, desc_addr;
	reg [2:0] phase;
	state_t phase_state;
	reg [31:0] d[0:31], f[0:15];
	reg [31:0] req_addr, rdword, cache_addr, cache_data;
	reg cache_valid;
	reg active_slot, weights_ready, prefetch_locked;
	integer di, fi, pi;
	integer oy, ox, oc0, ic0, th, tw, xh, xw, xsize, wsize, ci_count, co_count;
	integer xi, wi, branch_id, branch_offset, branch_c, branch_w, ratio;
	integer sy, sx, sc, sy1, sx0, sx1, sc0, sc1, dy, dx, ytop, xtop;
	integer m0, n0, kpos, lane, ri, qi;
	reg signed [7:0] sample_value;
	reg [31:0] avec, bvec;
	reg signed [31:0] psum_rd;
	reg [31:0] qp[0:19];
	reg [31:0] check_mpos, check_spos;

	reg [2:0] sample_advance;
	wire fused = d[D_FLAGS][2];
	wire final_ci = (ic0 + int'(d[D_TIC]) >= int'(d[D_CIN]));
	integer kc, kxy, ky, kx, spatial, outc, pindex;
	integer scatter_x, scatter_y, scatter_index;
	integer src_c, src_w, src_ratio, src_offset;
	reg [31:0] src_base;
	reg param_bad;

	function automatic integer imin (
		input integer a, b
	);

		imin = a < b ? a : b;
	endfunction

	function automatic integer imax (
		input integer a, b
	);

		imax = a > b ? a : b;
	endfunction

	wire signed [31:0] tile_h = imin(int'(d[D_TH]), int'(d[D_HOUT]) - oy);
	wire signed [31:0] tile_w = imin(int'(d[D_TW]), int'(d[D_WOUT]) - ox);
	wire signed [31:0] input_h = (tile_h - 1) * int'(d[D_SH]) + int'(d[D_KH]);
	wire signed [31:0] input_w = (tile_w - 1) * int'(d[D_SW]) + int'(d[D_KW]);
	wire signed [31:0] input_top = oy * int'(d[D_SH]) - int'(d[D_PT]);
	wire signed [31:0] input_left = ox * int'(d[D_SW]) - int'(d[D_PL]);
	// The ordinary loader overwrites every byte of an interior, full-Cin tile.
	wire overwrites_x = !fused && ic0 + int'(d[D_TIC]) <= int'(d[D_CIN]) &&
		input_top >= 0 && input_top + input_h <= int'(d[D_H]) &&
		input_left >= 0 && input_left + input_w <= int'(d[D_W]);

	wire [1023:0] d_words;
	for (genvar i = 0; i < 32; i = i + 1) begin : pack_d
		assign d_words[32 * i +: 32] = d[i];
	end
	wire [511:0] f_words;
	for (genvar i = 0; i < 16; i = i + 1) begin : pack_f
		assign f_words[32 * i +: 32] = f[i];
	end

	wire config_bad, addr_bad, desc_addr_ok, fuse_addr_ok;
	det_conv_descriptor descriptor_check (
		.descriptor(d_words),
		.fusion(f_words),
		.desc_addr(desc_addr),
		.desc_addr_ok(desc_addr_ok),
		.fuse_addr_ok(fuse_addr_ok),
		.config_bad(config_bad),
		.addr_bad(addr_bad)
	);

	// Tile coordinates, virtual-source selection and quantization checks.
	always @* begin
		spatial = m0 + ri / 4;
		outc = n0 + ri % 4;
		pindex = spatial * int'(d[D_TOC]) + outc;
		kc = kpos & (int'(d[D_TIC]) - 1);
		kxy = kpos >> channel_shift;
		ky = d[D_KW] == 3 ? kxy / 3 : 0;
		kx = d[D_KW] == 3 ? kxy % 3 : 0;

		scatter_y = sy * ratio + dy - ytop;
		scatter_x = sx * ratio + dx - xtop;
		scatter_index = (scatter_y * xw + scatter_x) * int'(d[D_TIC]) + sc - ic0;

		src_c = fused ? int'(branch_id == 0 ? f[F_C0] : f[F_C1]) : int'(d[D_CIN]);
		src_w = fused ? int'(branch_id == 0 ? f[F_W0] : f[F_W1]) : int'(d[D_W]);
		src_ratio = fused && branch_id == 0 ? 2 : 1;
		src_base = fused ? (branch_id == 0 ? f[F_SRC0] : f[F_SRC1]) : d[D_SRC];
		src_offset = !fused ? 0
							: ((f[F_ORDER] == 0 && branch_id == 1)
										? int'(f[F_C0])
										: ((f[F_ORDER] == 1 && branch_id == 0) ? int'(f[F_C1]) : 0));

		param_bad = 0;
		case (pi % 5)
			1, 3:
				param_bad = rdword[31];
			2, 4:
				param_bad = rdword > 62;
			default:
				param_bad = 0;
		endcase
		if (pi % 5 == 3 && d[D_ACT] == 1 && rdword != 0)
			param_bad = 1;
		if (pi % 5 == 3 && d[D_ACT] == 0 && rdword != check_mpos)
			param_bad = 1;
		if (pi % 5 == 4 && d[D_ACT] == 0 && rdword != check_spos)
			param_bad = 1;
	end
	wire fq_cfg_ready, fq_in_ready, fq_out_valid;
	wire signed [7:0] fq_data;
	/* verilator lint_off PINCONNECTEMPTY */
	fuse_requant input_q (
		.clk(clk),
		.rst(rst),
		.cfg_valid(state == CHECK_DESC && !config_bad && !addr_bad && fused),
		.cfg_ready(fq_cfg_ready),
		.m0(f[F_M0][30:0]),
		.m1(f[F_M1][30:0]),
		.s0(f[F_S0][5:0]),
		.s1(f[F_S1][5:0]),
		.in_valid(state == CONVERT_IN),
		.in_ready(fq_in_ready),
		.src_id(branch_id != 0),
		.in_data(sample_value),
		.in_token(16'b0),
		.out_valid(fq_out_valid),
		.out_ready(state == CONVERT_OUT),
		.out_data(fq_data),
		.out_token()
	);
	/* verilator lint_on PINCONNECTEMPTY */
	wire core_clear = state == MICRO_BEGIN && ic0 == 0;
	// Gather the next operands while the core consumes the previous vectors.
	// Nonblocking assignments preserve the old vectors at this clock edge.
	wire core_step = state == MAC_STEP ||
		(state == GATHER_A && lane == 0 && kpos != 0);

	// Exclusive phase counters include the DMA dispatch/wait for each operation.
	// MAC overlap is counted separately by COMPUTE_CYCLES, not added to phases.
	always @* begin
		phase_state = (state == READ_DISPATCH || state == READ_BUS) ? read_return : state;
		case (phase_state)
			TILE_BEGIN, X_ZERO, SOURCE_BEGIN, SAMPLE_REQ, SAMPLE_GOT,
			CONVERT_IN, CONVERT_OUT, SCATTER, SAMPLE_NEXT, SOURCE_NEXT, W_REQ, W_GOT:
				phase = 0;
			GATHER_A, MAC_STEP: phase = 1;
			P_READ, P_RESTORE, P_SAVE: phase = 2;
			PARAM_REQ, PARAM_GOT, MICRO_PARAM_REQ, MICRO_PARAM_GOT: phase = 3;
			RESULT, WRITE_OUT: phase = 4;
			default: phase = 5;
		endcase
	end

	assign reg_ready = reg_valid && !rst;

	wire start_job = reg_valid && reg_wstrb == 4'hf &&
		reg_addr == REG_CTRL && !busy && reg_wdata == 1;
	det_conv_counters counters (
		.clk(clk),
		.rst(rst),
		.start_job(start_job),
		.reg_addr(reg_addr),
		.reg_rdata(reg_rdata),
		.desc_addr(desc_addr),
		.error_code(error_code),
		.busy(busy),
		.done_flag(done_flag),
		.error_flag(error_flag),
		.reject_flag(reject_flag),
		.phase(phase),
		.gather(state == GATHER_A),
		.gather_parallel(gather_parallel),
		.core_step(core_step),
		.prefetch_busy(prefetch_busy),
		.waiting_prefetch(state == IC_NEXT && !final_ci && !prefetch_done),
		.dma_wait(dma_valid && !dma_ready),
		.read_word(dma_valid && dma_ready && dma_wstrb == 0),
		.write_word(state == WRITE_OUT && main_dma_ready),
		.write_count(write_count)
	);


	// Foreground DMA and local buffer addresses.
	wire [31:0] write_addr = d[D_DST] +
						32'(((oy + xi / imax(tw, 1)) * int'(d[D_WOUT]) + ox + xi % imax(tw, 1)) *
								int'(d[D_COUT]) +
							oc0 + wi);

	wire [31:0] weight_read_addr = d[D_WEIGHT] +
								32'(((oc0 + wi / (int'(d[D_KH]) * int'(d[D_KW]) * int'(d[D_TIC]))) *
											int'(d[D_KH]) * int'(d[D_KW]) +
										wi / int'(d[D_TIC]) % (int'(d[D_KH]) * int'(d[D_KW]))) *
										int'(d[D_CIN]) +
									ic0 + wi % int'(d[D_TIC]));
	wire weight_full = weight_read_addr[1:0] == 0 && wi % 4 == 0 &&
		wi % int'(d[D_TIC]) + 4 <= ci_count;
	wire [2:0] weight_advance = weight_full ? 3'd4 : 3'd1;
	// One shared P read address keeps restore prefetch on a single read port.
	wire [9:0] p_read_index = state == P_RESTORE
		? 10'((m0 + (ri + 1) / 4) * int'(d[D_TOC]) + n0 + (ri + 1) % 4)
		: 10'(pindex);
	wire signed [31:0] p_read_data;
	wire [31:0] output_word;
	wire bias_overflow;
	wire valid_result = spatial < th * tw && outc < co_count;

	wire [639:0] qp_words;
	for (genvar i = 0; i < 20; i = i + 1) begin : pack_qp
		assign qp_words[32 * i +: 32] = qp[i];
	end

	det_conv_datapath datapath (
		.clk(clk),
		.rst(rst),
		.clear(core_clear),
		.restore(state == P_RESTORE),
		.step(core_step),
		.ri(ri[3:0]),
		.restore_data(psum_rd),
		.avec(avec),
		.bvec(bvec),
		.quant_params(qp_words),
		.p_save(state == P_SAVE && valid_result),
		.result_save(state == RESULT && valid_result),
		.p_read_index(p_read_index),
		.p_write_index(10'(pindex)),
		.result_index(10'((spatial * int'(d[D_TOC]) + outc) / 4)),
		.output_index(10'((xi * int'(d[D_TOC]) + wi) / 4)),
		.result_lane(outc[1:0]),
		.p_read_data(p_read_data),
		.output_word(output_word),
		.bias_overflow(bias_overflow)
	);

	wire [2:0] channel_shift;
	wire [31:0] tile_k;
	wire gather_parallel;
	wire [31:0] next_a, next_b;
	reg x_write_valid, w_write_valid;
	reg [31:0] x_write_data, w_write_data;
	reg [3:0] x_write_strobe, w_write_strobe;
	integer x_write_index;
	wire ordinary_word = !fused && req_addr[1:0] == 0 && (sc - ic0) % 4 == 0 && sc + 3 <= sc1;

	always @* begin
		x_write_valid = 0;
		x_write_index = xi;
		x_write_data = 0;
		x_write_strobe = 4'b1111;
		if (state == X_ZERO)
			x_write_valid = 1;
		else if (state == SAMPLE_GOT && ordinary_word) begin
			x_write_valid = 1;
			x_write_index = ((sy - ytop) * xw + sx - xtop) * int'(d[D_TIC]) + sc - ic0;
			x_write_data = rdword;
		end else if (state == SCATTER && scatter_y >= 0 && scatter_y < xh &&
			scatter_x >= 0 && scatter_x < xw) begin
			x_write_valid = 1;
			x_write_index = scatter_index;
			x_write_data = {4{sample_value}};
			x_write_strobe = 4'b0001 << (scatter_index % 4);
		end

		w_write_valid = 0;
		w_write_data = 0;
		w_write_strobe = 4'b0001 << (wi % 4);
		if (state == W_REQ && (wi / imax(int'(tile_k), 1) >= co_count ||
			wi % imax(int'(d[D_TIC]), 1) >= ci_count)) begin
			w_write_valid = 1;
			w_write_strobe = wi % 4 == 0 ? 4'b1111 : w_write_strobe;
		end else if (state == W_GOT) begin
			w_write_valid = 1;
			w_write_data = weight_full ? rdword : {4{rdword[8 * req_addr[1:0] +: 8]}};
			w_write_strobe = weight_full ? 4'b1111 : (4'b0001 << (wi % 4));
		end
	end

	wire prefetch_busy, prefetch_done, prefetch_valid, prefetch_x_write, prefetch_w_write;
	wire [31:0] prefetch_addr, prefetch_write_data;
	wire [12:0] prefetch_write_index;
	wire [3:0] prefetch_write_strobe;
	wire prefetch_selected = prefetch_locked ||
		(prefetch_valid && state != READ_BUS && state != WRITE_OUT);
	wire main_dma_ready = dma_ready && !prefetch_selected;
	wire prefetch_ready = dma_ready && prefetch_selected;
	wire prefetch_consume = state == IC_NEXT && !final_ci && prefetch_done;

	tile_prefetch prefetch (
		.clk(clk),
		.rst(rst || !busy),
		.start(ENABLE_PREFETCH != 0 && state == MICRO_BEGIN && m0 == 0 && n0 == 0 && !final_ci && !prefetch_busy),
		.consume(prefetch_consume),
		.fused(fused),
		.src(d[D_SRC]),
		.weight(d[D_WEIGHT]),
		.src0(f[F_SRC0]),
		.src1(f[F_SRC1]),
		.width0(f[F_W0]),
		.width1(f[F_W1]),
		.channels0(f[F_C0]),
		.channels1(f[F_C1]),
		.order(f[F_ORDER]),
		.multiplier0(f[F_M0][30:0]),
		.multiplier1(f[F_M1][30:0]),
		.shift0(f[F_S0][5:0]),
		.shift1(f[F_S1][5:0]),
		.height(d[D_H]),
		.width(d[D_W]),
		.cin(d[D_CIN]),
		.cout(d[D_COUT]),
		.kh(d[D_KH]),
		.kw(d[D_KW]),
		.tic(d[D_TIC]),
		.toc(d[D_TOC]),
		.next_ic(32'(ic0) + d[D_TIC]),
		.oc(32'(oc0)),
		.xh(32'(xh)),
		.xw(32'(xw)),
		.ytop(32'(ytop)),
		.xtop(32'(xtop)),
		.busy(prefetch_busy),
		.done(prefetch_done),
		.read_valid(prefetch_valid),
		.read_addr(prefetch_addr),
		.read_ready(prefetch_ready),
		.read_data(dma_rdata),
		.x_write(prefetch_x_write),
		.w_write(prefetch_w_write),
		.write_index(prefetch_write_index),
		.write_data(prefetch_write_data),
		.write_strobe(prefetch_write_strobe)
	);

	det_conv_tile_buffer #(
		.ENABLE_BANKED_GATHER(ENABLE_BANKED_GATHER)
	) tile_buffer (
		.clk(clk),
		.rst(rst),
		.active_slot(active_slot),
		.tic(d[D_TIC]),
		.kh(d[D_KH]),
		.kw(d[D_KW]),
		.stride_w(d[D_SW]),
		.stride_h(d[D_SH]),
		.th(th),
		.tw(tw),
		.xh(xh),
		.xw(xw),
		.co_count(co_count),
		.m0(m0),
		.n0(n0),
		.kpos(kpos),
		.kc(kc),
		.kx(kx),
		.ky(ky),
		.lane(lane),
		.x_write_valid(x_write_valid),
		.w_write_valid(w_write_valid),
		.x_write_index(x_write_index),
		.w_write_index(wi),
		.x_write_data(x_write_data),
		.w_write_data(w_write_data),
		.x_write_strobe(x_write_strobe),
		.w_write_strobe(w_write_strobe),
		.prefetch_x_write(prefetch_x_write),
		.prefetch_w_write(prefetch_w_write),
		.prefetch_write_index(prefetch_write_index),
		.prefetch_write_data(prefetch_write_data),
		.prefetch_write_strobe(prefetch_write_strobe),
		.channel_shift(channel_shift),
		.tile_k(tile_k),
		.gather_parallel(gather_parallel),
		.next_a(next_a),
		.next_b(next_b)
	);

	always @(posedge clk) begin
		if (rst || !busy)
			prefetch_locked <= 0;
		else if (prefetch_selected && prefetch_valid)
			prefetch_locked <= !dma_ready;
	end

	assign dma_valid = !rst && (prefetch_selected ? prefetch_valid : (state == READ_BUS || state == WRITE_OUT));

	assign dma_addr = prefetch_selected ? prefetch_addr :
		(state == WRITE_OUT ? {write_addr[31:2], 2'b00} : {req_addr[31:2], 2'b00});

	wire write_full = write_addr[1:0] == 0 && wi % 4 == 0 && wi + 4 <= co_count;
	wire [7:0] output_byte = output_word[8 * (wi % 4) +: 8];
	wire [2:0] write_count = write_full ? 3'd4 : 3'd1;

	assign dma_wstrb = state == WRITE_OUT && !prefetch_selected
		? (write_full ? 4'b1111 : (4'b0001 << write_addr[1:0])) : 4'b0000;

	assign dma_wdata = state == WRITE_OUT
		? (write_full ? output_word : ({24'b0, output_byte} << (8 * write_addr[1:0])))
		: 32'b0;

	task automatic read_at (
		input [31:0] address,
		input state_t next_state
	);

		begin
			req_addr <= address;
			read_return <= next_state;
			state <= READ_DISPATCH;
		end
	endtask

	task automatic fail_job (
		input [31:0] code
	);

		begin
			busy <= 0;
			done_flag <= 0;
			error_flag <= 1;
			error_code <= code;
			state <= IDLE;
		end
	endtask

	// One job FSM owns the loop counters and schedules the datapath.
	always @(posedge clk) begin
		if (rst) begin
			state <= IDLE;
			read_return <= IDLE;
			busy <= 0;
			done_flag <= 0;
			error_flag <= 0;
			reject_flag <= 0;
			error_code <= 0;
			desc_addr <= 0;

			req_addr <= 0;
			rdword <= 0;
			cache_addr <= 0;
			cache_data <= 0;
			cache_valid <= 0;
			active_slot <= 0;
			weights_ready <= 0;

			di <= 0;
			fi <= 0;
			pi <= 0;
			oy <= 0;
			ox <= 0;
			oc0 <= 0;
			ic0 <= 0;
			th <= 0;
			tw <= 0;
			xh <= 0;
			xw <= 0;
			xsize <= 0;
			wsize <= 0;
			ci_count <= 0;
			co_count <= 0;

			xi <= 0;
			wi <= 0;
			branch_id <= 0;
			branch_offset <= 0;
			branch_c <= 0;
			branch_w <= 0;
			ratio <= 1;

			sy <= 0;
			sx <= 0;
			sc <= 0;
			sy1 <= 0;
			sx0 <= 0;
			sx1 <= 0;
			sc0 <= 0;
			sc1 <= 0;
			dy <= 0;
			dx <= 0;
			ytop <= 0;
			xtop <= 0;

			m0 <= 0;
			n0 <= 0;
			kpos <= 0;
			lane <= 0;
			ri <= 0;
			qi <= 0;
			sample_value <= 0;
			sample_advance <= 1;
			avec <= 0;
			bvec <= 0;
			psum_rd <= 0;
			check_mpos <= 0;
			check_spos <= 0;

			for (integer i = 0; i < 32; i = i + 1)
				d[i] <= 0;
			for (integer i = 0; i < 16; i = i + 1)
				f[i] <= 0;
			for (integer i = 0; i < 20; i = i + 1)
				qp[i] <= 0;
		end else begin
			case (state)

				IDLE: begin
				end

				DESC_REQ:
					read_at(desc_addr + 32'(di * 4), DESC_GOT);

				DESC_GOT: begin
					d[di] <= rdword;
					if (di == 31) begin
						fi <= 0;
						state <= FUSE_REQ;
					end else begin
						di <= di + 1;
						state <= DESC_REQ;
					end
				end

				FUSE_REQ: begin
					if (!fused)
						state <= CHECK_DESC;
					else if (!fuse_addr_ok)
						fail_job(3);
					else
						read_at(d[D_FUSE_ADDR] + 32'(fi * 4), FUSE_GOT);
				end

				FUSE_GOT: begin
					f[fi] <= rdword;
					if (fi == 15)
						state <= CHECK_DESC;
					else begin
						fi <= fi + 1;
						state <= FUSE_REQ;
					end
				end

				CHECK_DESC: begin
					if (config_bad)
						fail_job(2);
					else if (addr_bad)
						fail_job(4);
					else if (!fused || fq_cfg_ready) begin
						pi <= 0;
						state <= PARAM_REQ;
					end
				end

				PARAM_REQ:
					read_at(d[D_QPARAM] + 32'(pi * 4), PARAM_GOT);

				PARAM_GOT: begin
					if (param_bad)
						fail_job(5);
					else begin
						if (pi % 5 == 1)
							check_mpos <= rdword;
						if (pi % 5 == 2)
							check_spos <= rdword;
						if (pi + 1 == int'(d[D_COUT]) * 5) begin
							oy <= 0;
							ox <= 0;
							oc0 <= 0;
							ic0 <= 0;
							state <= TILE_BEGIN;
						end else begin
							pi <= pi + 1;
							state <= PARAM_REQ;
						end
					end
				end

				TILE_BEGIN: begin
					th <= tile_h;
					tw <= tile_w;
					xh <= input_h;
					xw <= input_w;
					xsize <= input_h * input_w * int'(d[D_TIC]);
					wsize <= int'(d[D_KH]) * int'(d[D_KW]) * int'(d[D_TIC]) * int'(d[D_TOC]);
					ci_count <= imin(int'(d[D_TIC]), int'(d[D_CIN]) - ic0);
					co_count <= imin(int'(d[D_TOC]), int'(d[D_COUT]) - oc0);
					ytop <= input_top;
					xtop <= input_left;
					xi <= 0;
					if (ic0 != 0 && weights_ready) begin
						// A prefetched channel block has both X and W ready.
						m0 <= 0;
						n0 <= 0;
						state <= MICRO_BEGIN;
					end else if (overwrites_x) begin
						branch_id <= 0;
						state <= SOURCE_BEGIN;
					end else
						state <= X_ZERO;
				end

				X_ZERO: begin
					if (xi + 4 == xsize) begin
						branch_id <= 0;
						state <= SOURCE_BEGIN;
					end else
						xi <= xi + 4;
				end

				SOURCE_BEGIN: begin
					branch_offset <= src_offset;
					branch_c <= src_c;
					branch_w <= src_w;
					ratio <= src_ratio;
					sy <= imax(0, ytop) / src_ratio;
					sy1 <= imin(int'(d[D_H]) - 1, ytop + xh - 1) / src_ratio;
					sx0 <= imax(0, xtop) / src_ratio;
					sx <= imax(0, xtop) / src_ratio;
					sx1 <= imin(int'(d[D_W]) - 1, xtop + xw - 1) / src_ratio;
					sc0 <= imax(ic0, src_offset);
					sc <= imax(ic0, src_offset);
					sc1 <= imin(ic0 + ci_count, src_offset + src_c) - 1;
					if (imax(ic0, src_offset) >= imin(ic0 + ci_count, src_offset + src_c) ||
						imax(0, ytop) > imin(int'(d[D_H]) - 1, ytop + xh - 1) ||
						imax(0, xtop) > imin(int'(d[D_W]) - 1, xtop + xw - 1))
						state <= SOURCE_NEXT;
					else
						state <= SAMPLE_REQ;
				end

				SAMPLE_REQ:
					read_at(src_base + 32'((sy * branch_w + sx) * branch_c + sc - branch_offset),
						SAMPLE_GOT);

				SAMPLE_GOT: begin
					sample_value <= $signed(rdword[8 * req_addr[1:0] +: 8]);
					dy <= 0;
					dx <= 0;
					sample_advance <= 1;
					if (ordinary_word) begin
						sample_advance <= 4;
						state <= SAMPLE_NEXT;
					end else
						state <= fused ? CONVERT_IN : SCATTER;
				end

				CONVERT_IN:
					if (fq_in_ready)
						state <= CONVERT_OUT;

				CONVERT_OUT:
					if (fq_out_valid) begin
						sample_value <= fq_data;
						state <= SCATTER;
					end

				SCATTER: begin
					if (dx + 1 < ratio)
						dx <= dx + 1;
					else if (dy + 1 < ratio) begin
						dx <= 0;
						dy <= dy + 1;
					end else
						state <= SAMPLE_NEXT;
				end

				SAMPLE_NEXT: begin
					if (sc + int'(sample_advance) <= sc1) begin
						sc <= sc + int'(sample_advance);
						state <= SAMPLE_REQ;
					end else if (sx < sx1) begin
						sx <= sx + 1;
						sc <= sc0;
						state <= SAMPLE_REQ;
					end else if (sy < sy1) begin
						sy <= sy + 1;
						sx <= sx0;
						sc <= sc0;
						state <= SAMPLE_REQ;
					end else
						state <= SOURCE_NEXT;
				end

				SOURCE_NEXT:
					if (fused && branch_id == 0) begin
						branch_id <= 1;
						state <= SOURCE_BEGIN;
					end else begin
						wi <= 0;
						m0 <= 0;
						n0 <= 0;
						state <= weights_ready ? MICRO_BEGIN : W_REQ;
					end

				W_REQ: begin
					if (wi / (int'(d[D_KH]) * int'(d[D_KW]) * int'(d[D_TIC])) >= co_count ||
						wi % int'(d[D_TIC]) >= ci_count) begin
						if (wi + (wi % 4 == 0 ? 4 : 1) == wsize) begin
							weights_ready <= 1;
							m0 <= 0;
							n0 <= 0;
							state <= MICRO_BEGIN;
						end else
							wi <= wi + (wi % 4 == 0 ? 4 : 1);
					end else
						read_at(weight_read_addr, W_GOT);
				end

				W_GOT: begin
					if (wi + int'(weight_advance) == wsize) begin
						weights_ready <= 1;
						m0 <= 0;
						n0 <= 0;
						state <= MICRO_BEGIN;
					end else begin
						wi <= wi + int'(weight_advance);
						state <= W_REQ;
					end
				end

				MICRO_BEGIN: begin
					ri <= 0;
					qi <= 0;
					kpos <= 0;
					lane <= 0;
					avec <= 0;
					bvec <= 0;
					state <= ic0 == 0 ? ((final_ci && m0 == 0) ? MICRO_PARAM_REQ : GATHER_A) : P_READ;
				end

				P_READ: begin
					psum_rd <= spatial < th * tw && outc < co_count ? p_read_data : 32'sd0;
					state <= P_RESTORE;
				end

				P_RESTORE: begin
					if (ri == 15) begin
						ri <= 0;
						state <= (final_ci && m0 == 0) ? MICRO_PARAM_REQ : GATHER_A;
					end else begin
						ri <= ri + 1;
						// Prefetch the following accumulator while restoring this one.
						psum_rd <= (m0 + (ri + 1) / 4 < th * tw && n0 + (ri + 1) % 4 < co_count)
							? p_read_data
							: 32'sd0;
					end
				end

				MICRO_PARAM_REQ: begin
					if (n0 + qi / 5 >= co_count) begin
						qp[qi] <= 0;
						if (qi == 19) begin
							lane <= 0;
							state <= GATHER_A;
						end else
							qi <= qi + 1;
					end else
						read_at(d[D_QPARAM] + 32'(((oc0 + n0 + qi / 5) * 5 + qi % 5) * 4),
							MICRO_PARAM_GOT);
				end

				MICRO_PARAM_GOT: begin
					qp[qi] <= rdword;
					if (qi == 19) begin
						lane <= 0;
						state <= GATHER_A;
					end else begin
						qi <= qi + 1;
						state <= MICRO_PARAM_REQ;
					end
				end

				GATHER_A: begin
					// Conflict-free pixels consume all four banks in one cycle.
					// Arbitrary short/odd row widths retain a serial fallback.
					if (gather_parallel) begin
						avec <= next_a;
						bvec <= next_b;
					end else begin
						avec[lane * 8 +: 8] <= next_a[lane * 8 +: 8];
						bvec[lane * 8 +: 8] <= next_b[lane * 8 +: 8];
					end
					if (gather_parallel || lane == 3) begin
						lane <= 0;
						if (kc + 1 == ci_count && kxy + 1 == int'(d[D_KH] * d[D_KW]))
							state <= MAC_STEP;
						else if (kc + 1 == ci_count)
							kpos <= (kxy + 1) * int'(d[D_TIC]);
						else
							kpos <= kpos + 1;
					end else
						lane <= lane + 1;
				end

				MAC_STEP: begin
					// Drain the last gathered vectors; earlier MACs overlap gather.
					ri <= 0;
					state <= final_ci ? RESULT : P_SAVE;
				end

				RESULT: begin
					if (valid_result && bias_overflow)
						fail_job(5);
					else begin
						if (ri == 15)
							state <= MICRO_NEXT;
						else
							ri <= ri + 1;
					end
				end

				P_SAVE: begin
					if (ri == 15)
						state <= MICRO_NEXT;
					else
						ri <= ri + 1;
				end

				MICRO_NEXT: begin
					// Keep one four-channel quantization vector across all spatial blocks.
					if (m0 + 4 < th * tw) begin
						m0 <= m0 + 4;
						state <= MICRO_BEGIN;
					end else if (n0 + 4 < co_count) begin
						n0 <= n0 + 4;
						m0 <= 0;
						state <= MICRO_BEGIN;
					end else
						state <= IC_NEXT;
				end

				IC_NEXT: begin
					if (!final_ci) begin
						if (ENABLE_PREFETCH == 0) begin
							weights_ready <= 0;
							ic0 <= ic0 + int'(d[D_TIC]);
							state <= TILE_BEGIN;
						end else if (prefetch_done) begin
							active_slot <= !active_slot;
							weights_ready <= 1;
							ic0 <= ic0 + int'(d[D_TIC]);
							state <= TILE_BEGIN;
						end
					end else begin
						xi <= 0;
						wi <= 0;
						state <= WRITE_OUT;
					end
				end

				WRITE_OUT:
					if (main_dma_ready) begin
						if (wi + int'(write_count) < co_count)
							wi <= wi + int'(write_count);
						else if (xi + 1 < th * tw) begin
							xi <= xi + 1;
							wi <= 0;
						end else
							state <= TILE_NEXT;
					end

				TILE_NEXT: begin
					// With one block on both channel axes, the active W
					// remains valid when only the spatial tile changes.
					weights_ready <= ic0 == 0 && oc0 == 0 && d[D_COUT] <= d[D_TOC];
					ic0 <= 0;
					if (oc0 + int'(d[D_TOC]) < int'(d[D_COUT])) begin
						oc0 <= oc0 + int'(d[D_TOC]);
						state <= TILE_BEGIN;
					end else if (ox + tw < int'(d[D_WOUT])) begin
						ox <= ox + tw;
						oc0 <= 0;
						state <= TILE_BEGIN;
					end else if (oy + th < int'(d[D_HOUT])) begin
						oy <= oy + th;
						ox <= 0;
						oc0 <= 0;
						state <= TILE_BEGIN;
					end else begin
						busy <= 0;
						done_flag <= 1;
						state <= IDLE;
					end
				end

				READ_DISPATCH: begin
					if (cache_valid && cache_addr == {req_addr[31:2], 2'b00}) begin
						rdword <= cache_data;
						state <= read_return;
					end else
						state <= READ_BUS;
				end

				READ_BUS:
					if (main_dma_ready) begin
						rdword <= dma_rdata;
						cache_data <= dma_rdata;
						cache_addr <= {req_addr[31:2], 2'b00};
						cache_valid <= 1;
						state <= read_return;
					end
				default:
					fail_job(6);
			endcase
			if (reg_valid && reg_wstrb != 0) begin
				if (reg_wstrb != 15 || reg_addr[1:0] != 0)
					reject_flag <= 1;
				else if (reg_addr == REG_STATUS) begin
					if (reg_wdata[1])
						done_flag <= 0;
					if (reg_wdata[2])
						error_flag <= 0;
					if (reg_wdata[3])
						reject_flag <= 0;
				end else if (busy)
					reject_flag <= 1;
				else if (reg_addr == REG_DESC_ADDR)
					desc_addr <= reg_wdata;
				else if (reg_addr == REG_CTRL && reg_wdata == 1) begin
					done_flag <= 0;
					error_flag <= 0;
					reject_flag <= 0;
					error_code <= 0;
					cache_valid <= 0;
					active_slot <= 0;
					weights_ready <= 0;

					if (!desc_addr_ok) begin
						error_flag <= 1;
						error_code <= 3;
					end else begin
						busy <= 1;
						di <= 0;
						state <= DESC_REQ;
					end
				end else
					reject_flag <= 1;
			end
		end
	end
`ifndef SYNTHESIS

	always @(posedge clk)
		if (!rst && busy) begin
			if (state == X_ZERO)
				assert (xi >= 0 && xi < 8192);
			if (state == SCATTER && scatter_y >= 0 && scatter_y < xh && scatter_x >= 0 &&
				scatter_x < xw)
				assert (scatter_index >= 0 && scatter_index < 8192);
			if (state == P_SAVE && spatial < th * tw && outc < co_count)
				assert (pindex >= 0 && pindex < 1024);
		end
`endif
endmodule
