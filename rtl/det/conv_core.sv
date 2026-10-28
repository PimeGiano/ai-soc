`timescale 1ns/1ps
// Output-stationary 4x4 broadcast MAC array. One K position per step.
// Serial restore/export preserves single-port scratch memory in its controller.
module conv_core(
 input wire clk,rst,clear,
 input wire restore,input wire [3:0] index,input wire signed [31:0] restore_data,
 input wire step,input wire [31:0] a_vector,b_vector,
 output wire signed [31:0] result
);
 reg signed [31:0] acc[0:15];
 wire signed [15:0] product[0:15];
 for(genvar r=0;r<4;r=r+1) begin: rows
  for(genvar c=0;c<4;c=c+1) begin: cols
   assign product[r*4+c]=$signed(a_vector[r*8+:8])*$signed(b_vector[c*8+:8]);
  end
 end
 assign result=acc[index];
 always @(posedge clk) begin
  if(rst || clear) begin for(integer i=0;i<16;i=i+1) acc[i]<=0;end
  else if(restore) acc[index]<=restore_data;
  else if(step) begin for(integer i=0;i<16;i=i+1) acc[i]<=acc[i]+{{16{product[i][15]}},product[i]};end
 end
endmodule
