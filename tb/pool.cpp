#include "Vpool_accelerator.h"
#include "verilated.h"
#include "memory.hpp"
#include "../firmware/spec.h"
#include <algorithm>
#include <random>

int main(int argc, char **argv)
{
	try {
		Verilated::commandArgs(argc, argv);
		Vpool_accelerator t;
		Memory mem;
		std::mt19937 rng(20261108);
		uint64_t cycles = 0, reads = 0, writes = 0;
		uint32_t out = 0, bytes = 0, output_pitch = 0, output_channels = 0;
		uint32_t held_addr = 0, held_data = 0;
		uint8_t held_strobe = 0;
		int left = -1;
		auto tick = [&]() {
			t.clk = 0;
			t.dma_ready = 0;
			t.eval();
			bool complete = false;
			if (t.dma_valid) {
				if (left < 0) {
					left = rng() % 16;
					held_addr = t.dma_addr;
					held_data = t.dma_wdata;
					held_strobe = t.dma_wstrb;
				} else if (held_addr != t.dma_addr || held_data != t.dma_wdata ||
					held_strobe != t.dma_wstrb)
					throw std::runtime_error("unstable pool DMA");
				if (left == 0) {
					t.dma_ready = 1;
					t.dma_rdata = mem.read(t.dma_addr);
					if (t.dma_wstrb) {
						for (unsigned lane = 0; lane < 4; lane++)
							if (t.dma_wstrb & (1 << lane)) {
								uint32_t offset = t.dma_addr + lane - out;
								if (offset >= bytes || offset % output_pitch >= output_channels)
									throw std::runtime_error("pool write outside tensor");
								writes++;
							}
						mem.write(t.dma_addr, t.dma_wdata, t.dma_wstrb);
					} else
						reads++;
					complete = true;
				} else
					left--;
			}
			t.eval();
			t.clk = 1;
			t.eval();
			if (complete)
				left = -1;
			if (++cycles > 100000000)
				throw std::runtime_error("pool watchdog");
		};
		auto reset = [&]() {
			t.rst = 1;
			t.reg_valid = 0;
			left = -1;
			for (int i = 0; i < 3; i++)
				tick();
			t.rst = 0;
		};
		auto wr = [&](unsigned addr, uint32_t value) {
			t.reg_valid = 1;
			t.reg_addr = addr;
			t.reg_wdata = value;
			t.reg_wstrb = 15;
			tick();
			t.reg_valid = 0;
			t.reg_wstrb = 0;
		};
		auto status = [&]() {
			t.clk = 0;
			t.reg_addr = 28;
			t.eval();
			return t.reg_rdata;
		};
		reset();
		for (unsigned job = 0; job < 124; job++) {
			unsigned h = 1 + rng() % 17, w = 1 + rng() % 19;
			unsigned choices[] = {1, 3, 4, 7, 16, 33};
			unsigned c = choices[job % 6], stride = 1 + job % 2;
			bool strided = job >= 100 && job % 5 != 0;
			unsigned mult[] = {1, 5, 0, 0x7fffffff, 3, 1};
			unsigned shifts[] = {0, 3, 62, 30, 1, 62};
			unsigned quant = job >= 100 ? (job - 100) / 4 : 0;
			uint32_t m = mult[quant], s = shifts[quant];
			if (job == 101) {
				m = 5;
				s = 3;
				stride = 1;
			}
			unsigned ho = (h - 1) / stride + 1, wo = (w - 1) / stride + 1;
			uint32_t src = 0x01010000;
			out = 0x01100000;
			output_channels = c;
			output_pitch = strided ? c + (job % 4 == 0 ? 3 : 4) : c;
			bytes = (ho * wo - 1) * output_pitch + c;
			for (unsigned i = 0; i < h * w * c; i++)
				mem.at(src + i) = job == 101 ? 128 : uint8_t(rng());
			for (unsigned i = 0; i <= bytes; i++)
				mem.at(out + i) = 0x55;
			auto configure = [&]() {
				wr(0, src);
				wr(4, out);
				wr(8, h);
				wr(12, w);
				wr(16, c);
				wr(20, stride);
				if (strided) {
					wr(POOL_REG_DST_PITCH, output_pitch);
					wr(POOL_REG_Q_MULT, m);
					wr(POOL_REG_Q_SHIFT, s);
				}
				wr(24, strided ? 2 : 1);
			};
			configure();
			uint64_t start = cycles;
			uint64_t start_reads = reads;
			writes = 0;
			bool reset_done = false;
			while (status() & 1) {
				if (job == 99 && !reset_done && cycles - start > 200) {
					reset();
					configure();
					start_reads = reads;
					writes = 0;
					reset_done = true;
				} else
					tick();
			}
			if (status() != 2 || writes != ho * wo * c)
				throw std::runtime_error("pool completion/count mismatch");
			unsigned groups = c % 4 == 0 && output_pitch % 4 == 0 ? c / 4 : c;
			unsigned input_rows = stride == 1 ? 2 * h - 1 : h;
			if (reads - start_reads != uint64_t(input_rows) * w * groups)
				throw std::runtime_error("pool window reuse/read count mismatch");
			for (unsigned y = 0; y < ho; y++)
				for (unsigned x = 0; x < wo; x++)
					for (unsigned ch = 0; ch < c; ch++) {
						int expected = -127;
						for (unsigned ky = 0; ky < 2; ky++)
							for (unsigned kx = 0; kx < 2; kx++)
								if (y * stride + ky < h && x * stride + kx < w) {
									auto at = ((y * stride + ky) * w + x * stride + kx) * c + ch;
									int sample = int8_t(mem.at(src + at));
									if (strided) {
										int64_t mag = int64_t(std::abs(sample)) * m;
										if (s)
											mag = (mag + (int64_t(1) << (s - 1))) >> s;
										int clipped = int(std::min(mag, int64_t(127)));
										sample = sample < 0 ? -clipped : clipped;
									}
									expected = std::max(expected, sample);
								}
						if (int8_t(mem.at(out + (y * wo + x) * output_pitch + ch)) != expected)
							throw std::runtime_error("pool numerical mismatch");
					}
			if (mem.at(out + bytes) != 0x55 || (job == 99 && !reset_done))
				throw std::runtime_error("pool tail/reset coverage mismatch");
		}
		for (unsigned invalid = 0; invalid < 9; invalid++) {
			wr(0, 0x01010000);
			wr(4, 0x01100000);
			wr(8, 2);
			wr(12, 2);
			wr(16, 4);
			wr(20, 1);
			if (invalid == 0)
				wr(8, 0);
			if (invalid == 1)
				wr(4, 0x01010000);
			if (invalid == 2)
				wr(0, 0x01010001);
			if (invalid == 3)
				wr(20, 3);
			if (invalid == 4)
				wr(0, 0x04fffffc);
			if (invalid >= 5) {
				wr(POOL_REG_DST_PITCH, invalid == 5 ? 3 : 8);
				wr(POOL_REG_Q_MULT, invalid == 6 ? 0x80000000u : 5);
				wr(POOL_REG_Q_SHIFT, invalid == 7 ? 63 : 3);
				if (invalid == 8)
					wr(4, 0x04fffff0);
			}
			uint64_t before = reads;
			wr(24, invalid >= 5 ? 2 : 1);
			for (int i = 0; i < 4; i++)
				tick();
			if (status() != 4 || reads != before)
				throw std::runtime_error("invalid pool descriptor accepted");
		}
		t.final();
		std::cout << "POOL PASS cases=124 invalid=9 tail/stride/scale/wait/reset cycles=" << cycles
				  << "\n";
		return 0;
	} catch (const std::exception &e) {
		std::cerr << "FAIL " << e.what() << "\n";
		return 1;
	}
}
