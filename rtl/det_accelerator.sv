`timescale 1ns/1ps
// Single-bank implementation. SRAM: X 8KiB, W 8KiB, P 4KiB, O 4KiB.
// Second X/W banks are intentionally not implemented; flag bit1 is rejected.
module det_accelerator(
 input wire clk,rst,
 input wire reg_valid,input wire [7:0] reg_addr,input wire [31:0] reg_wdata,
 input wire [3:0] reg_wstrb,output wire reg_ready,output reg [31:0] reg_rdata,
 output wire dma_valid,output wire [31:0] dma_addr,dma_wdata,output wire [3:0] dma_wstrb,
 input wire dma_ready,input wire [31:0] dma_rdata
);
 `include "spec.vh"
 localparam [31:0] DATA_BASE=32'h01000000,DATA_END=32'h05000000;
 typedef enum logic [5:0] {IDLE,DESC_REQ,DESC_GOT,FUSE_REQ,FUSE_GOT,CHECK_DESC,
  PARAM_REQ,PARAM_GOT,TILE_BEGIN,X_ZERO,SOURCE_BEGIN,SAMPLE_REQ,SAMPLE_GOT,
  CONVERT_IN,CONVERT_OUT,SCATTER,SAMPLE_NEXT,SOURCE_NEXT,W_REQ,W_GOT,
  MICRO_BEGIN,P_READ,P_RESTORE,GATHER_A,GATHER_B,MAC_STEP,K_NEXT,
  MICRO_PARAM_REQ,MICRO_PARAM_GOT,RESULT,P_SAVE,RESULT_NEXT,MICRO_NEXT,
  IC_NEXT,WRITE_OUT,TILE_NEXT,READ_DISPATCH,READ_BUS} state_t;
 state_t state,read_return;
 reg busy,done_flag,error_flag,reject_flag;reg [31:0] error_code,desc_addr;
 reg [63:0] job_cycles,compute_cycles,read_words,write_bytes,wait_cycles;
 reg [31:0] d[0:31],f[0:15];
 reg [31:0] req_addr,rdword,cache_addr,cache_data;reg cache_valid;
 integer di,fi,pi;
 integer oy,ox,oc0,ic0,th,tw,xh,xw,xsize,wsize,ci_count,co_count;
 integer xi,wi,branch_id,branch_offset,branch_c,branch_w,ratio;
 integer sy,sx,sc,sy1,sx0,sx1,sc0,sc1,dy,dx,ytop,xtop;
 integer m0,n0,kpos,lane,ri,qi;
 reg signed [7:0] sample_value;
 reg [31:0] avec,bvec;
 reg signed [31:0] psum_rd;
 reg [31:0] qp[0:19];
 reg [31:0] check_mpos,check_spos;
 reg signed [7:0] xbuf[0:8191],wbuf[0:8191],obuf[0:4095];
 reg signed [31:0] psum[0:1023];
 wire fused=d[D_FLAGS][2];
 wire final_ci=(ic0+int'(d[D_TIC])>=int'(d[D_CIN]));
 integer px,py,kc,kxy,ky,kx,spatial,outc,local_x,local_y,local_c,pindex;
 integer scatter_x,scatter_y,scatter_index;
 integer src_c,src_w,src_ratio,src_offset;
 reg [31:0] src_base;
 reg [63:0] xbytes,wbytes,pbytes;
 reg config_bad,addr_bad,param_bad;
 function automatic integer imin(input integer a,b);imin=a<b?a:b;endfunction
 function automatic integer imax(input integer a,b);imax=a>b?a:b;endfunction
 function automatic bit in_range(input [31:0] a,input [63:0] n);
   in_range=(n!=0 && a>=DATA_BASE && {32'b0,a}+n<={32'b0,DATA_END} && a[1:0]==0);
 endfunction
 function automatic bit overlap(input [31:0] a,input [63:0] an,input [31:0] b,input [63:0] bn);
   overlap=({32'b0,a}<{32'b0,b}+bn && {32'b0,b}<{32'b0,a}+an);
 endfunction
 wire [63:0] insize={32'b0,d[D_H]}*{32'b0,d[D_W]}*{32'b0,d[D_CIN]};
 wire [63:0] weight_size={32'b0,d[D_COUT]}*{32'b0,d[D_KH]}*{32'b0,d[D_KW]}*{32'b0,d[D_CIN]};
 wire [63:0] output_size={32'b0,d[D_HOUT]}*{32'b0,d[D_WOUT]}*{32'b0,d[D_COUT]};
 wire [63:0] param_size=64'd20*{32'b0,d[D_COUT]};
 wire [63:0] src0_size={32'b0,f[F_H0]}*{32'b0,f[F_W0]}*{32'b0,f[F_C0]};
 wire [63:0] src1_size={32'b0,f[F_H1]}*{32'b0,f[F_W1]}*{32'b0,f[F_C1]};
 always @* begin
  xbytes=((64'(d[D_TH])-1)*64'(d[D_SH])+64'(d[D_KH]))*((64'(d[D_TW])-1)*64'(d[D_SW])+64'(d[D_KW]))*64'(d[D_TIC]);
  wbytes=64'(d[D_KH])*64'(d[D_KW])*64'(d[D_TIC])*64'(d[D_TOC]);
  pbytes=64'(d[D_TH])*64'(d[D_TW])*64'(d[D_TOC])*4;
  config_bad=d[D_H]<1 || d[D_H]>160 || d[D_W]<1 || d[D_W]>160 || d[D_CIN]<1 || d[D_CIN]>1024 || d[D_COUT]<1 || d[D_COUT]>1024 ||
    !(d[D_KH]==1 || d[D_KH]==3) || d[D_KW]!=d[D_KH] || !(d[D_SH]==1 || d[D_SH]==2) || d[D_SW]!=d[D_SH] ||
    d[D_PT]>1 || d[D_PB]>1 || d[D_PL]>1 || d[D_PR]>1 || d[D_HOUT]<1 || d[D_WOUT]<1 ||
    (int'(d[D_H])+int'(d[D_PT])+int'(d[D_PB])-int'(d[D_KH]))<0 ||
    (int'(d[D_W])+int'(d[D_PL])+int'(d[D_PR])-int'(d[D_KW]))<0 ||
    int'(d[D_HOUT])!=(int'(d[D_H])+int'(d[D_PT])+int'(d[D_PB])-int'(d[D_KH]))/int'(d[D_SH]|1*(d[D_SH]==0))+1 ||
    int'(d[D_WOUT])!=(int'(d[D_W])+int'(d[D_PL])+int'(d[D_PR])-int'(d[D_KW]))/int'(d[D_SW]|1*(d[D_SW]==0))+1 ||
    d[D_TH]<1 || d[D_TH]>16 || d[D_TW]<1 || d[D_TW]>16 ||
    !(d[D_TIC]==4 || d[D_TIC]==8 || d[D_TIC]==16) || !(d[D_TOC]==4 || d[D_TOC]==8 || d[D_TOC]==16) ||
    xbytes>8192 || wbytes>8192 || pbytes>4096 || d[D_ACT]>2 ||
    (d[D_FLAGS]&32'hfffffffa)!=0 || !d[D_FLAGS][0] || (!fused && d[D_FUSE_ADDR]!=0);
  for(integer i=25;i<32;i=i+1) if(d[i]!=0) config_bad=1;
  if(fused) begin
    if(d[D_SRC]!=0 || {32'b0,f[F_H0]}*2!={32'b0,d[D_H]} || f[F_H1]!=d[D_H] ||
      {32'b0,f[F_W0]}*2!={32'b0,d[D_W]} || f[F_W1]!=d[D_W] ||
      {32'b0,f[F_C0]}+{32'b0,f[F_C1]}!={32'b0,d[D_CIN]} || f[F_C0]==0 || f[F_C1]==0 ||
      f[F_R0]!=2 || f[F_R1]!=1 || f[F_ORDER]>1 || f[F_RESERVED]!=0 ||
      f[F_M0][31] || f[F_M1][31] || f[F_S0]>62 || f[F_S1]>62) config_bad=1;
  end
  addr_bad=!in_range(d[D_WEIGHT],weight_size) || !in_range(d[D_DST],output_size) || !in_range(d[D_QPARAM],param_size) ||
    overlap(d[D_DST],output_size,d[D_WEIGHT],weight_size) || overlap(d[D_DST],output_size,d[D_QPARAM],param_size) ||
    overlap(d[D_DST],output_size,desc_addr,128);
  if(fused) addr_bad=addr_bad || !in_range(f[F_SRC0],src0_size) || !in_range(f[F_SRC1],src1_size) ||
    overlap(d[D_DST],output_size,f[F_SRC0],src0_size) || overlap(d[D_DST],output_size,f[F_SRC1],src1_size) || overlap(d[D_DST],output_size,d[D_FUSE_ADDR],64);
  else addr_bad=addr_bad || !in_range(d[D_SRC],insize) || overlap(d[D_DST],output_size,d[D_SRC],insize);
  spatial=m0+ri/4;outc=n0+ri%4;
  pindex=spatial*int'(d[D_TOC])+outc;
  kc=kpos%int'(d[D_TIC]|1*(d[D_TIC]==0));kxy=kpos/int'(d[D_TIC]|1*(d[D_TIC]==0));
  ky=kxy/int'(d[D_KW]|1*(d[D_KW]==0));kx=kxy%int'(d[D_KW]|1*(d[D_KW]==0));
  px=(m0+lane)%imax(tw,1);py=(m0+lane)/imax(tw,1);
  local_x=px*int'(d[D_SW])+kx;local_y=py*int'(d[D_SH])+ky;local_c=kc;
  scatter_y=sy*ratio+dy-ytop;scatter_x=sx*ratio+dx-xtop;
  scatter_index=(scatter_y*xw+scatter_x)*int'(d[D_TIC])+sc-ic0;
  src_c=fused ? int'(branch_id==0 ? f[F_C0]:f[F_C1]) : int'(d[D_CIN]);
  src_w=fused ? int'(branch_id==0 ? f[F_W0]:f[F_W1]) : int'(d[D_W]);
  src_ratio=fused && branch_id==0 ? 2:1;
  src_base=fused ? (branch_id==0 ? f[F_SRC0]:f[F_SRC1]):d[D_SRC];
  src_offset=!fused ? 0 : ((f[F_ORDER]==0 && branch_id==1) ? int'(f[F_C0]) : ((f[F_ORDER]==1 && branch_id==0) ? int'(f[F_C1]):0));
  param_bad=0;
  case(pi%5)
   1,3: param_bad=rdword[31];
   2,4: param_bad=rdword>62;
   default: param_bad=0;
  endcase
  if(pi%5==3 && d[D_ACT]==1 && rdword!=0) param_bad=1;
  if(pi%5==3 && d[D_ACT]==0 && rdword!=check_mpos) param_bad=1;
  if(pi%5==4 && d[D_ACT]==0 && rdword!=check_spos) param_bad=1;
 end
 wire fq_cfg_ready,fq_in_ready,fq_out_valid;
 wire signed [7:0] fq_data;
 /* verilator lint_off PINCONNECTEMPTY */
 fuse_requant input_q(.clk(clk),.rst(rst),.cfg_valid(state==CHECK_DESC && !config_bad && !addr_bad && fused),.cfg_ready(fq_cfg_ready),
  .m0(f[F_M0][30:0]),.m1(f[F_M1][30:0]),.s0(f[F_S0][5:0]),.s1(f[F_S1][5:0]),
  .in_valid(state==CONVERT_IN),.in_ready(fq_in_ready),.src_id(branch_id!=0),.in_data(sample_value),.in_token(16'b0),
  .out_valid(fq_out_valid),.out_ready(state==CONVERT_OUT),.out_data(fq_data),.out_token());
 /* verilator lint_on PINCONNECTEMPTY */
 wire signed [31:0] core_result;
 wire core_clear=state==MICRO_BEGIN && ic0==0;
 conv_core core(.clk(clk),.rst(rst),.clear(core_clear),.restore(state==P_RESTORE),.index(ri[3:0]),.restore_data(psum_rd),
  .step(state==MAC_STEP),.a_vector(avec),.b_vector(bvec),.result(core_result));
 wire signed [63:0] biased=$signed({{32{core_result[31]}},core_result})+$signed({{32{qp[(ri%4)*5][31]}},qp[(ri%4)*5]});
 wire [30:0] qmult=biased<0 ? qp[(ri%4)*5+3][30:0]:qp[(ri%4)*5+1][30:0];
 wire [5:0] qshift=biased<0 ? qp[(ri%4)*5+4][5:0]:qp[(ri%4)*5+2][5:0];
 wire signed [7:0] qresult;
 requant output_q(.value(biased[31:0]),.multiplier(qmult),.shift(qshift),.result(qresult));
 assign reg_ready=reg_valid && !rst;
 always @* begin
  reg_rdata=0;
  case(reg_addr)
   REG_STATUS:reg_rdata={28'b0,reject_flag,error_flag,done_flag,busy};
   REG_DESC_ADDR:reg_rdata=desc_addr;REG_ERROR_CODE:reg_rdata=error_code;
   REG_JOB_CYCLES_LO:reg_rdata=job_cycles[31:0];REG_JOB_CYCLES_HI:reg_rdata=job_cycles[63:32];
   REG_COMPUTE_CYCLES_LO:reg_rdata=compute_cycles[31:0];REG_COMPUTE_CYCLES_HI:reg_rdata=compute_cycles[63:32];
   REG_READ_WORDS_LO:reg_rdata=read_words[31:0];REG_READ_WORDS_HI:reg_rdata=read_words[63:32];
   REG_WRITE_BYTES_LO:reg_rdata=write_bytes[31:0];REG_WRITE_BYTES_HI:reg_rdata=write_bytes[63:32];
   REG_DMA_WAIT_LO:reg_rdata=wait_cycles[31:0];REG_DMA_WAIT_HI:reg_rdata=wait_cycles[63:32];
   REG_VERSION:reg_rdata=DET_INTERFACE_VERSION;
   default:reg_rdata=0;
  endcase
 end
 wire [31:0] write_addr=d[D_DST]+32'(((oy+xi/imax(tw,1))*int'(d[D_WOUT])+ox+xi%imax(tw,1))*int'(d[D_COUT])+oc0+wi);
 assign dma_valid=!rst && (state==READ_BUS || state==WRITE_OUT);
 assign dma_addr=state==WRITE_OUT ? {write_addr[31:2],2'b00}:{req_addr[31:2],2'b00};
 assign dma_wstrb=state==WRITE_OUT ? (4'b0001<<write_addr[1:0]):4'b0000;
 assign dma_wdata=state==WRITE_OUT ? ({24'b0,obuf[xi*int'(d[D_TOC])+wi]}<<(8*write_addr[1:0])):32'b0;
 task automatic read_at(input [31:0] address,input state_t next_state);
  begin req_addr<=address;read_return<=next_state;state<=READ_DISPATCH;end
 endtask
 task automatic fail_job(input [31:0] code);
  begin busy<=0;done_flag<=0;error_flag<=1;error_code<=code;state<=IDLE;end
 endtask
 always @(posedge clk) begin
  if(rst) begin
   state<=IDLE;read_return<=IDLE;busy<=0;done_flag<=0;error_flag<=0;reject_flag<=0;error_code<=0;desc_addr<=0;
   job_cycles<=0;compute_cycles<=0;read_words<=0;write_bytes<=0;wait_cycles<=0;
   req_addr<=0;rdword<=0;cache_addr<=0;cache_data<=0;cache_valid<=0;
   di<=0;fi<=0;pi<=0;oy<=0;ox<=0;oc0<=0;ic0<=0;th<=0;tw<=0;xh<=0;xw<=0;xsize<=0;wsize<=0;ci_count<=0;co_count<=0;
   xi<=0;wi<=0;branch_id<=0;branch_offset<=0;branch_c<=0;branch_w<=0;ratio<=1;
   sy<=0;sx<=0;sc<=0;sy1<=0;sx0<=0;sx1<=0;sc0<=0;sc1<=0;dy<=0;dx<=0;ytop<=0;xtop<=0;
   m0<=0;n0<=0;kpos<=0;lane<=0;ri<=0;qi<=0;sample_value<=0;avec<=0;bvec<=0;psum_rd<=0;check_mpos<=0;check_spos<=0;
   for(integer i=0;i<32;i=i+1) d[i]<=0;
   for(integer i=0;i<16;i=i+1) f[i]<=0;
   for(integer i=0;i<20;i=i+1) qp[i]<=0;
  end else begin
   if(busy) job_cycles<=job_cycles+1;
   if(state==MAC_STEP) compute_cycles<=compute_cycles+1;
   if(dma_valid && !dma_ready) wait_cycles<=wait_cycles+1;
   if(state==READ_BUS && dma_ready) read_words<=read_words+1;
   if(state==WRITE_OUT && dma_ready) write_bytes<=write_bytes+1;
   case(state)
    IDLE:begin end
    DESC_REQ:read_at(desc_addr+32'(di*4),DESC_GOT);
    DESC_GOT:begin d[di]<=rdword;if(di==31) begin fi<=0;state<=FUSE_REQ;end else begin di<=di+1;state<=DESC_REQ;end end
    FUSE_REQ:begin
      if(!fused) state<=CHECK_DESC;
      else if(!in_range(d[D_FUSE_ADDR],64) || d[D_FUSE_ADDR][3:0]!=0) fail_job(3);
      else read_at(d[D_FUSE_ADDR]+32'(fi*4),FUSE_GOT);
    end
    FUSE_GOT:begin f[fi]<=rdword;if(fi==15) state<=CHECK_DESC;else begin fi<=fi+1;state<=FUSE_REQ;end end
    CHECK_DESC:begin
     if(config_bad) fail_job(2);else if(addr_bad) fail_job(4);
     else if(!fused || fq_cfg_ready) begin pi<=0;state<=PARAM_REQ;end
    end
    PARAM_REQ:read_at(d[D_QPARAM]+32'(pi*4),PARAM_GOT);
    PARAM_GOT:begin
     if(param_bad) fail_job(5);
     else begin
      if(pi%5==1) check_mpos<=rdword;if(pi%5==2) check_spos<=rdword;
      if(pi+1==int'(d[D_COUT])*5) begin oy<=0;ox<=0;oc0<=0;ic0<=0;state<=TILE_BEGIN;end
      else begin pi<=pi+1;state<=PARAM_REQ;end
     end
    end
    TILE_BEGIN:begin
     th<=imin(int'(d[D_TH]),int'(d[D_HOUT])-oy);tw<=imin(int'(d[D_TW]),int'(d[D_WOUT])-ox);
     xh<=(imin(int'(d[D_TH]),int'(d[D_HOUT])-oy)-1)*int'(d[D_SH])+int'(d[D_KH]);
     xw<=(imin(int'(d[D_TW]),int'(d[D_WOUT])-ox)-1)*int'(d[D_SW])+int'(d[D_KW]);
     xsize<=((imin(int'(d[D_TH]),int'(d[D_HOUT])-oy)-1)*int'(d[D_SH])+int'(d[D_KH]))*((imin(int'(d[D_TW]),int'(d[D_WOUT])-ox)-1)*int'(d[D_SW])+int'(d[D_KW]))*int'(d[D_TIC]);
     wsize<=int'(d[D_KH])*int'(d[D_KW])*int'(d[D_TIC])*int'(d[D_TOC]);
     ci_count<=imin(int'(d[D_TIC]),int'(d[D_CIN])-ic0);co_count<=imin(int'(d[D_TOC]),int'(d[D_COUT])-oc0);
     ytop<=oy*int'(d[D_SH])-int'(d[D_PT]);xtop<=ox*int'(d[D_SW])-int'(d[D_PL]);
     xi<=0;state<=X_ZERO;
    end
    X_ZERO:begin xbuf[xi]<=0;if(xi+1==xsize) begin branch_id<=0;state<=SOURCE_BEGIN;end else xi<=xi+1;end
    SOURCE_BEGIN:begin
     branch_offset<=src_offset;branch_c<=src_c;branch_w<=src_w;ratio<=src_ratio;
     sy<=imax(0,ytop)/src_ratio;sy1<=imin(int'(d[D_H])-1,ytop+xh-1)/src_ratio;
     sx0<=imax(0,xtop)/src_ratio;sx<=imax(0,xtop)/src_ratio;sx1<=imin(int'(d[D_W])-1,xtop+xw-1)/src_ratio;
     sc0<=imax(ic0,src_offset);sc<=imax(ic0,src_offset);sc1<=imin(ic0+ci_count,src_offset+src_c)-1;
     if(imax(ic0,src_offset)>=imin(ic0+ci_count,src_offset+src_c) || imax(0,ytop)>imin(int'(d[D_H])-1,ytop+xh-1) || imax(0,xtop)>imin(int'(d[D_W])-1,xtop+xw-1)) state<=SOURCE_NEXT;
     else state<=SAMPLE_REQ;
    end
    SAMPLE_REQ:read_at(src_base+32'((sy*branch_w+sx)*branch_c+sc-branch_offset),SAMPLE_GOT);
    SAMPLE_GOT:begin sample_value<=$signed(rdword[8*req_addr[1:0]+:8]);dy<=0;dx<=0;state<=fused?CONVERT_IN:SCATTER;end
    CONVERT_IN:if(fq_in_ready) state<=CONVERT_OUT;
    CONVERT_OUT:if(fq_out_valid) begin sample_value<=fq_data;state<=SCATTER;end
    SCATTER:begin
     if(scatter_y>=0 && scatter_y<xh && scatter_x>=0 && scatter_x<xw) xbuf[scatter_index]<=sample_value;
     if(dx+1<ratio) dx<=dx+1;
     else if(dy+1<ratio) begin dx<=0;dy<=dy+1;end
     else state<=SAMPLE_NEXT;
    end
    SAMPLE_NEXT:begin
     if(sc<sc1) begin sc<=sc+1;state<=SAMPLE_REQ;end
     else if(sx<sx1) begin sx<=sx+1;sc<=sc0;state<=SAMPLE_REQ;end
     else if(sy<sy1) begin sy<=sy+1;sx<=sx0;sc<=sc0;state<=SAMPLE_REQ;end
     else state<=SOURCE_NEXT;
    end
    SOURCE_NEXT:if(fused && branch_id==0) begin branch_id<=1;state<=SOURCE_BEGIN;end else begin wi<=0;state<=W_REQ;end
    W_REQ:begin
     if(wi/(int'(d[D_KH])*int'(d[D_KW])*int'(d[D_TIC]))>=co_count || wi%int'(d[D_TIC])>=ci_count) begin
      wbuf[wi]<=0;if(wi+1==wsize) begin m0<=0;n0<=0;state<=MICRO_BEGIN;end else wi<=wi+1;
     end else read_at(d[D_WEIGHT]+32'(((oc0+wi/(int'(d[D_KH])*int'(d[D_KW])*int'(d[D_TIC])))*int'(d[D_KH])*int'(d[D_KW])+wi/int'(d[D_TIC])%(int'(d[D_KH])*int'(d[D_KW])))*int'(d[D_CIN])+ic0+wi%int'(d[D_TIC])),W_GOT);
    end
    W_GOT:begin
     wbuf[wi]<=$signed(rdword[8*req_addr[1:0]+:8]);
     if(wi+1==wsize) begin m0<=0;n0<=0;state<=MICRO_BEGIN;end else begin wi<=wi+1;state<=W_REQ;end
    end
    MICRO_BEGIN:begin ri<=0;qi<=0;kpos<=0;lane<=0;avec<=0;bvec<=0;state<=ic0==0 ? (final_ci?MICRO_PARAM_REQ:GATHER_A):P_READ;end
    P_READ:begin psum_rd<=spatial<th*tw && outc<co_count ? psum[pindex]:32'sd0;state<=P_RESTORE;end
    P_RESTORE:begin if(ri==15) begin ri<=0;state<=final_ci?MICRO_PARAM_REQ:GATHER_A;end else begin ri<=ri+1;state<=P_READ;end end
    MICRO_PARAM_REQ:begin
      if(n0+qi/5>=co_count) begin qp[qi]<=0;if(qi==19) begin lane<=0;state<=GATHER_A;end else qi<=qi+1;end
      else read_at(d[D_QPARAM]+32'(((oc0+n0+qi/5)*5+qi%5)*4),MICRO_PARAM_GOT);
    end
    MICRO_PARAM_GOT:begin qp[qi]<=rdword;if(qi==19) begin lane<=0;state<=GATHER_A;end else begin qi<=qi+1;state<=MICRO_PARAM_REQ;end end
    GATHER_A:begin
     avec[lane*8+:8]<=m0+lane<th*tw ? xbuf[(local_y*xw+local_x)*int'(d[D_TIC])+local_c]:8'sd0;
     if(lane==3) begin lane<=0;state<=GATHER_B;end else lane<=lane+1;
    end
    GATHER_B:begin
     bvec[lane*8+:8]<=wbuf[((n0+lane)*int'(d[D_KH])*int'(d[D_KW]))*int'(d[D_TIC])+kpos];
     if(lane==3) begin lane<=0;state<=MAC_STEP;end else lane<=lane+1;
    end
    MAC_STEP:state<=K_NEXT;
    K_NEXT:begin
     if(kpos+1==int'(d[D_KH])*int'(d[D_KW])*int'(d[D_TIC])) begin ri<=0;state<=final_ci?RESULT:P_SAVE;end
     else begin kpos<=kpos+1;state<=GATHER_A;end
    end
    RESULT:begin
     if(spatial<th*tw && outc<co_count) begin
      if(biased>64'sh7fffffff || biased< -64'sh80000000) fail_job(5);
      else begin obuf[spatial*int'(d[D_TOC])+outc]<=qresult;state<=RESULT_NEXT;end
     end else state<=RESULT_NEXT;
    end
    P_SAVE:begin if(spatial<th*tw && outc<co_count) psum[pindex]<=core_result;state<=RESULT_NEXT;end
    RESULT_NEXT:begin if(ri==15) state<=MICRO_NEXT;else begin ri<=ri+1;state<=final_ci?RESULT:P_SAVE;end end
    MICRO_NEXT:begin
     if(n0+4<int'(d[D_TOC])) begin n0<=n0+4;state<=MICRO_BEGIN;end
     else if(m0+4<th*tw) begin m0<=m0+4;n0<=0;state<=MICRO_BEGIN;end
     else state<=IC_NEXT;
    end
    IC_NEXT:begin
     if(!final_ci) begin ic0<=ic0+int'(d[D_TIC]);state<=TILE_BEGIN;end
     else begin xi<=0;wi<=0;state<=WRITE_OUT;end
    end
    WRITE_OUT:if(dma_ready) begin
     if(wi+1<co_count) wi<=wi+1;
     else if(xi+1<th*tw) begin xi<=xi+1;wi<=0;end
     else state<=TILE_NEXT;
    end
    TILE_NEXT:begin
     ic0<=0;
     if(oc0+int'(d[D_TOC])<int'(d[D_COUT])) begin oc0<=oc0+int'(d[D_TOC]);state<=TILE_BEGIN;end
     else if(ox+tw<int'(d[D_WOUT])) begin ox<=ox+tw;oc0<=0;state<=TILE_BEGIN;end
     else if(oy+th<int'(d[D_HOUT])) begin oy<=oy+th;ox<=0;oc0<=0;state<=TILE_BEGIN;end
     else begin busy<=0;done_flag<=1;state<=IDLE;end
    end
    READ_DISPATCH:begin
     if(cache_valid && cache_addr=={req_addr[31:2],2'b00}) begin rdword<=cache_data;state<=read_return;end
     else state<=READ_BUS;
    end
    READ_BUS:if(dma_ready) begin rdword<=dma_rdata;cache_data<=dma_rdata;cache_addr<={req_addr[31:2],2'b00};cache_valid<=1;state<=read_return;end
    default:fail_job(6);
   endcase
   if(reg_valid && reg_wstrb!=0) begin
    if(reg_wstrb!=15 || reg_addr[1:0]!=0) reject_flag<=1;
    else if(reg_addr==REG_STATUS) begin
     if(reg_wdata[1]) done_flag<=0;if(reg_wdata[2]) error_flag<=0;if(reg_wdata[3]) reject_flag<=0;
    end else if(busy) reject_flag<=1;
    else if(reg_addr==REG_DESC_ADDR) desc_addr<=reg_wdata;
    else if(reg_addr==REG_CTRL && reg_wdata==1) begin
     done_flag<=0;error_flag<=0;reject_flag<=0;error_code<=0;cache_valid<=0;
     job_cycles<=0;compute_cycles<=0;read_words<=0;write_bytes<=0;wait_cycles<=0;
     if(desc_addr[3:0]!=0 || !in_range(desc_addr,128)) begin error_flag<=1;error_code<=3;end
     else begin busy<=1;di<=0;state<=DESC_REQ;end
    end else reject_flag<=1;
   end
  end
 end
`ifndef SYNTHESIS
 always @(posedge clk) if(!rst && busy) begin
  if(state==X_ZERO) assert(xi>=0 && xi<8192);
  if(state==SCATTER && scatter_y>=0 && scatter_y<xh && scatter_x>=0 && scatter_x<xw) assert(scatter_index>=0 && scatter_index<8192);
  if(state==P_SAVE && spatial<th*tw && outc<co_count) assert(pindex>=0 && pindex<1024);
 end
`endif
endmodule
