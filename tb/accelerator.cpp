#include "Vdet_accelerator.h"
#include "verilated.h"
#include "memory.hpp"
#include <random>
int main(int argc,char**argv){try{
 Verilated::commandArgs(argc,argv);Vdet_accelerator t;Memory mem;
 if(argc<3)throw std::runtime_error("usage: vectors.mem jobs.txt [delay]");mem.load(argv[1]);int delay=argc>3?std::stoi(argv[3]):0;
 std::mt19937 rng(20261028);uint64_t cycles=0;int left=-1;uint32_t helda=0,heldd=0;uint8_t helds=0;
 auto tick=[&](){
  t.clk=0;t.dma_ready=0;t.eval();
  if(t.dma_valid){if(left<0){left=int(rng()%(delay+1));helda=t.dma_addr;heldd=t.dma_wdata;helds=t.dma_wstrb;}
   else if(helda!=t.dma_addr||heldd!=t.dma_wdata||helds!=t.dma_wstrb)throw std::runtime_error("unstable DMA");
   if(left==0){t.dma_ready=1;t.dma_rdata=mem.read(t.dma_addr);if(t.dma_wstrb)mem.write(t.dma_addr,t.dma_wdata,t.dma_wstrb);}else --left;
  }
  t.eval();bool completed=t.dma_valid&&t.dma_ready;t.clk=1;t.eval();if(completed)left=-1;if(++cycles>500000000)throw std::runtime_error("watchdog");
 };
 t.rst=1;t.reg_valid=0;for(int i=0;i<4;i++)tick();t.rst=0;
 auto wr=[&](int a,uint32_t d,uint8_t s=15){t.reg_valid=1;t.reg_addr=a;t.reg_wdata=d;t.reg_wstrb=s;tick();t.reg_valid=0;t.reg_wstrb=0;};
 auto rd=[&](int a){t.clk=0;t.reg_valid=1;t.reg_addr=a;t.reg_wstrb=0;t.eval();uint32_t x=t.reg_rdata;t.reg_valid=0;return x;};
 std::ifstream jobs(argv[2]);uint32_t da,out,n,err;std::string ref;unsigned job=0;
 while(jobs>>da>>out>>n>>ref>>err){
  wr(8,da);wr(0,1);bool injected=false,reset_once=false;uint64_t job_start=cycles;
  while(rd(4)&1){if(job==2 && !reset_once && cycles-job_start>5000){t.rst=1;left=-1;for(int z=0;z<4;z++)tick();t.rst=0;wr(8,da);wr(0,1);reset_once=true;}else if(!injected && job==0 && cycles%7==0){wr(8,0);injected=true;}else tick();}
  auto status=rd(4);if(err){if(!(status&4)||rd(12)!=err||rd(40)!=0)throw std::runtime_error("missing expected descriptor error");}
  else{if(!(status&2)||(status&4))throw std::runtime_error("accelerator error "+std::to_string(rd(12)));mem.compare(out,n,ref);if(mem.at(out+n)!=0x55)throw std::runtime_error("tail write clobber");}
  if(job==0 && injected && !(status&8))throw std::runtime_error("busy write accepted");
  wr(4,14);if(rd(4)&14)throw std::runtime_error("W1C failed");
  std::cout<<"CASE "<<job++<<" PASS cycles="<<rd(16)<<" compute="<<rd(24)<<" reads="<<rd(32)<<" writes="<<rd(40)<<"\n";
 }
 if(job==0)throw std::runtime_error("no jobs");
 // Misalignment must fail without reading memory.
 wr(8,0x01010001);wr(0,1);if(!(rd(4)&4)||rd(12)!=3||rd(32)!=0)throw std::runtime_error("alignment check");
 std::cout<<"DETECTION ACCEL PASS jobs="<<job<<" cycles="<<cycles<<" delay="<<delay<<"\n";t.final();return 0;
 }catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}}
