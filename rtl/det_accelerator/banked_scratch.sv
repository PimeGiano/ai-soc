`timescale 1ns / 1ps

// Four independent 2KiB banks. Each bank has one read and one byte-enabled
// write port. Banking changes layout, never replicates the stored tensor.
module banked_scratch (
	input wire clk,
	input wire write_valid,
	input wire [1:0] write_bank,
	input wire [8:0] write_addr,
	input wire [31:0] write_data,
	input wire [3:0] write_strobe,
	input wire [35:0] read_addr,
	output wire [127:0] read_data
);
	for (genvar bank = 0; bank < 4; bank = bank + 1) begin : banks
		reg [31:0] words[0:511];
		assign read_data[bank * 32 +: 32] = words[read_addr[bank * 9 +: 9]];

		always @(posedge clk) begin
			if (write_valid && write_bank == bank) begin
				for (integer byte_lane = 0; byte_lane < 4; byte_lane = byte_lane + 1)
					if (write_strobe[byte_lane])
						words[write_addr][byte_lane * 8 +: 8] <= write_data[byte_lane * 8 +: 8];
			end
		end
	end
endmodule
