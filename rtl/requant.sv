`timescale 1ns/1ps
// Full signed 64-bit intermediate; ties away from zero, clamp to [-127,127].
module requant(
 input wire signed [31:0] value,
 input wire [30:0] multiplier,
 input wire [5:0] shift,
 output reg signed [7:0] result
);
 reg signed [63:0] product;
 reg [63:0] magnitude,rounded;
 always @* begin
   product=$signed(value)*$signed({1'b0,multiplier});
   magnitude=product<0 ? $unsigned(-product) : $unsigned(product);
   rounded=shift==0 ? magnitude : (magnitude+(64'd1<<(shift-1)))>>shift;
   if(rounded>127) result=product<0 ? -8'sd127 : 8'sd127;
   else result=product<0 ? -$signed(rounded[7:0]) : $signed(rounded[7:0]);
 end
endmodule
