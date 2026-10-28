`timescale 1ns/1ps
module det_soc_top(
 input wire clk,rst,output wire trap,
 output wire mem_valid,output wire [31:0] mem_addr,mem_wdata,output wire [3:0] mem_wstrb,
 input wire mem_ready,input wire [31:0] mem_rdata,
 output wire mem_dma,mem_instr
);
 wire cv,cr,dv,dr,sv,sr,ci;
 wire [31:0] ca,cw,cd,da,dw,dd,sa,sw,sd;
 wire [3:0] cs,ds,ss;
 wire reg_select=sa[31:8]==24'h100001;
 wire rr;wire [31:0] rd;
 /* verilator lint_off PINCONNECTEMPTY */
 picorv32 #(.ENABLE_FAST_MUL(1),.ENABLE_DIV(1),.ENABLE_COUNTERS(1),.ENABLE_IRQ(0),.COMPRESSED_ISA(0),
  .PROGADDR_RESET(0),.STACKADDR(32'h05000000)) cpu(
  .clk(clk),.resetn(!rst),.trap(trap),.mem_valid(cv),.mem_instr(ci),.mem_ready(cr),.mem_addr(ca),.mem_wdata(cw),.mem_wstrb(cs),.mem_rdata(cd),
  .mem_la_read(),.mem_la_write(),.mem_la_addr(),.mem_la_wdata(),.mem_la_wstrb(),
  .pcpi_valid(),.pcpi_insn(),.pcpi_rs1(),.pcpi_rs2(),.pcpi_wr(1'b0),.pcpi_rd(32'b0),.pcpi_wait(1'b0),.pcpi_ready(1'b0),
  .irq(32'b0),.eoi(),.trace_valid(),.trace_data());
 /* verilator lint_on PINCONNECTEMPTY */
 native_arbiter arb(.clk(clk),.rst(rst),.c_valid(cv),.c_addr(ca),.c_wdata(cw),.c_wstrb(cs),.c_ready(cr),.c_rdata(cd),
  .d_valid(dv),.d_addr(da),.d_wdata(dw),.d_wstrb(ds),.d_ready(dr),.d_rdata(dd),
  .s_valid(sv),.s_addr(sa),.s_wdata(sw),.s_wstrb(ss),.s_ready(sr),.s_rdata(sd));
 det_accelerator accel(.clk(clk),.rst(rst),.reg_valid(sv&&reg_select),.reg_addr(sa[7:0]),.reg_wdata(sw),.reg_wstrb(ss),.reg_ready(rr),.reg_rdata(rd),
  .dma_valid(dv),.dma_addr(da),.dma_wdata(dw),.dma_wstrb(ds),.dma_ready(dr),.dma_rdata(dd));
 assign mem_valid=sv && !reg_select;
 assign mem_addr=sa;assign mem_wdata=sw;assign mem_wstrb=ss;
 assign sr=reg_select?rr:mem_ready;assign sd=reg_select?rd:mem_rdata;
 // Only meaningful on a completed external transaction, when dr identifies owner.
 assign mem_dma=dr && !reg_select;assign mem_instr=ci && !mem_dma;
endmodule
