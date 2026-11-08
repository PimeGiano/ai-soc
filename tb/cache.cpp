#include "Vinstruction_cache.h"
#include "verilated.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <unordered_map>

int main(int argc, char **argv)
{
	try {
		Verilated::commandArgs(argc, argv);
		Vinstruction_cache t;
		std::unordered_map<uint32_t, uint32_t> memory;
		memory[0] = 0x11223344;
		memory[0x400] = 0xaabbccdd;
		memory[0x01000000] = 0x76543210;
		auto edge = [&]() {
			t.clk = 0;
			t.eval();
			t.clk = 1;
			t.eval();
		};
		t.cpu_valid = 0;
		t.bus_ready = 0;
		t.rst = 1;
		edge();
		t.rst = 0;

		auto access =
			[&](uint32_t addr, bool instr, uint8_t strobe, uint32_t data, bool expect_hit) {
				t.cpu_valid = 1;
				t.cpu_instr = instr;
				t.cpu_addr = addr;
				t.cpu_wstrb = strobe;
				t.bus_ready = 0;
				t.clk = 0;
				t.eval();
				if (expect_hit) {
					if (!t.cpu_ready || t.bus_valid || t.cpu_rdata != memory[addr])
						throw std::runtime_error("cache hit mismatch");
				} else {
					for (int wait = 0; wait < 5; wait++) {
						if (t.cpu_ready || !t.bus_valid)
							throw std::runtime_error("miss did not wait for memory");
						edge();
					}
					if (strobe)
						for (int lane = 0; lane < 4; lane++)
							if (strobe & (1 << lane))
								memory[addr] = (memory[addr] & ~(0xffu << (8 * lane))) |
									(data & (0xffu << (8 * lane)));
					t.bus_rdata = memory[addr];
					t.bus_ready = 1;
					t.clk = 0;
					t.eval();
					if (!t.cpu_ready || (!strobe && t.cpu_rdata != memory[addr]))
						throw std::runtime_error("memory completion mismatch");
				}
				edge();
				t.cpu_valid = 0;
				t.bus_ready = 0;
				edge();
			};

		access(0, true, 0, 0, false);
		access(0, true, 0, 0, true);
		access(0x400, true, 0, 0, false);
		access(0, true, 0, 0, false);
		access(0, false, 0, 0, false);
		access(0, false, 2, 0x0000ee00, false);
		access(0, true, 0, 0, false);
		access(0, true, 0, 0, true);
		access(0x01000000, true, 0, 0, false);
		access(0x01000000, true, 0, 0, false);

		// Reset while a conflicting miss is stalled: no stale hit may survive.
		t.cpu_valid = 1;
		t.cpu_instr = 1;
		t.cpu_addr = 0x400;
		t.rst = 1;
		edge();
		if (t.cpu_ready || t.bus_valid)
			throw std::runtime_error("request escaped reset");
		t.cpu_valid = 0;
		t.rst = 0;
		access(0, true, 0, 0, false);
		t.final();
		std::cout << "INSTRUCTION CACHE PASS hit/conflict/bypass/partial-store/reset/wait\n";
		return 0;
	} catch (const std::exception &e) {
		std::cerr << "FAIL " << e.what() << "\n";
		return 1;
	}
}
