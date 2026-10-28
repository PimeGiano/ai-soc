`timescale 1ns/1ps
// Independent one-entry I9 converter. Elastic output, configuration when empty.
module fuse_requant(
 input wire clk,rst,
 input wire cfg_valid,output wire cfg_ready,
 input wire [30:0] m0,m1,input wire [5:0] s0,s1,
 input wire in_valid,output wire in_ready,input wire src_id,
 input wire signed [7:0] in_data,input wire [15:0] in_token,
 output reg out_valid,input wire out_ready,
 output reg signed [7:0] out_data,output reg [15:0] out_token
);
 reg [30:0] m[0:1];reg [5:0] s[0:1];reg configured;
 wire signed [7:0] converted;
 requant q(.value({{24{in_data[7]}},in_data}),.multiplier(m[src_id]),.shift(s[src_id]),.result(converted));
 assign cfg_ready=!out_valid;
 assign in_ready=configured && !cfg_valid && (!out_valid || out_ready);
 always @(posedge clk) begin
  if(rst) begin out_valid<=0;out_data<=0;out_token<=0;configured<=0;m[0]<=0;m[1]<=0;s[0]<=0;s[1]<=0;end
  else begin
   if(cfg_valid && cfg_ready) begin m[0]<=m0;m[1]<=m1;s[0]<=s0;s[1]<=s1;configured<=1;end
   if(out_valid && out_ready) out_valid<=0;
   if(in_valid && in_ready) begin out_valid<=1;out_data<=converted;out_token<=in_token;end
  end
 end
endmodule
