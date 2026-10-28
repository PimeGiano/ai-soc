`timescale 1ns/1ps
// Lock the selected master until completion. Alternate when both are pending.
module native_arbiter(
 input wire clk,rst,
 input wire c_valid, input wire [31:0] c_addr,c_wdata,input wire [3:0] c_wstrb,
 output wire c_ready,output wire [31:0] c_rdata,
 input wire d_valid,input wire [31:0] d_addr,d_wdata,input wire [3:0] d_wstrb,
 output wire d_ready,output wire [31:0] d_rdata,
 output wire s_valid,output wire [31:0] s_addr,s_wdata,output wire [3:0] s_wstrb,
 input wire s_ready,input wire [31:0] s_rdata
);
 reg locked,owner,last_owner;
 wire selected=locked ? owner : ((c_valid && d_valid) ? !last_owner : d_valid);
 assign s_valid=!rst && (selected ? d_valid : c_valid);
 assign s_addr=selected ? d_addr : c_addr;
 assign s_wdata=selected ? d_wdata : c_wdata;
 assign s_wstrb=selected ? d_wstrb : c_wstrb;
 assign c_ready=s_valid && !selected && s_ready;
 assign d_ready=s_valid && selected && s_ready;
 assign c_rdata=s_rdata;
 assign d_rdata=s_rdata;
 always @(posedge clk) begin
   if(rst) begin locked<=0;owner<=0;last_owner<=1;end
   else if(s_valid) begin
     if(s_ready) begin locked<=0;last_owner<=selected;end
     else begin locked<=1;owner<=selected;end
   end
 end
endmodule
