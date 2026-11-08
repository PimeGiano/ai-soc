#include "Vpool_accelerator.h"
#include "verilated.h"
#include "memory.hpp"
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
		uint32_t out = 0, bytes = 0, held_addr = 0, held_data = 0;
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
								if (t.dma_addr + lane < out || t.dma_addr + lane >= out + bytes)
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
		for (unsigned job = 0; job < 100; job++) {
			unsigned h = 1 + rng() % 17, w = 1 + rng() % 19;
			unsigned choices[] = {1, 3, 4, 7, 16, 33};
			unsigned c = choices[job % 6], stride = 1 + job % 2;
			unsigned ho = (h - 1) / stride + 1, wo = (w - 1) / stride + 1;
			uint32_t src = 0x01010000;
			out = 0x01100000;
			bytes = ho * wo * c;
			for (unsigned i = 0; i < h * w * c; i++)
				mem.at(src + i) = uint8_t(rng());
			for (unsigned i = 0; i <= bytes; i++)
				mem.at(out + i) = 0x55;
			auto configure = [&]() {
				wr(0, src);
				wr(4, out);
				wr(8, h);
				wr(12, w);
				wr(16, c);
				wr(20, stride);
				wr(24, 1);
			};
			configure();
			uint64_t start = cycles;
			writes = 0;
			bool reset_done = false;
			while (status() & 1) {
				if (job == 99 && !reset_done && cycles - start > 200) {
					reset();
					configure();
					writes = 0;
					reset_done = true;
				} else
					tick();
			}
			if (status() != 2 || writes != bytes)
				throw std::runtime_error("pool completion/count mismatch");
			for (unsigned y = 0; y < ho; y++)
				for (unsigned x = 0; x < wo; x++)
					for (unsigned ch = 0; ch < c; ch++) {
						int expected = -127;
						for (unsigned ky = 0; ky < 2; ky++)
							for (unsigned kx = 0; kx < 2; kx++)
								if (y * stride + ky < h && x * stride + kx < w)
									expected = std::max(expected,
										int(int8_t(mem.at(src +
											((y * stride + ky) * w + x * stride + kx) * c + ch))));
						if (int8_t(mem.at(out + (y * wo + x) * c + ch)) != expected)
							throw std::runtime_error("pool numerical mismatch");
					}
			if (mem.at(out + bytes) != 0x55 || (job == 99 && !reset_done))
				throw std::runtime_error("pool tail/reset coverage mismatch");
		}
		for (unsigned invalid = 0; invalid < 5; invalid++) {
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
			uint64_t before = reads;
			wr(24, 1);
			for (int i = 0; i < 4; i++)
				tick();
			if (status() != 4 || reads != before)
				throw std::runtime_error("invalid pool descriptor accepted");
		}
		t.final();
		std::cout << "POOL PASS cases=100 invalid=5 tail/stride/wait/reset cycles=" << cycles
				  << "\n";
		return 0;
	} catch (const std::exception &e) {
		std::cerr << "FAIL " << e.what() << "\n";
		return 1;
	}
}
