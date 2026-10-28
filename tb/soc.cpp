#include "Vdet_soc_top.h"
#include "verilated.h"
#include "memory.hpp"
#include <random>
#include <chrono>
struct Counts{uint64_t reads=0,writes=0,read_bytes=0,write_bytes=0;};
int main(int argc,char**argv){try{
 Verilated::commandArgs(argc,argv);if(argc<5)throw std::runtime_error("usage: model.mem firmware.bin checks.txt boxes.bin [delay] [whole]");
 Vdet_soc_top t;Memory mem;mem.load(argv[1]);std::ifstream firmware(argv[2],std::ios::binary);firmware.read((char*)mem.code.data(),mem.code.size());
 int delay=argc>5?std::stoi(argv[5]):0;if(argc>6 && std::stoi(argv[6]))mem.write(0x01008000+28,1,15);
 std::mt19937 rng(20261028);uint64_t cycles=0,start=0;int left=-1;bool roi=false,finished=false;uint32_t roi_id=0;
 std::array<Counts,3> count{};uint32_t helda=0,heldd=0;uint8_t helds=0;
 auto report=[&](){std::cout<<"ROI {\"id\":"<<roi_id<<",\"cycles\":"<<cycles-start;
  const char*names[]={"cpu_data","cpu_instr","dma"};for(int i=0;i<3;i++)std::cout<<",\""<<names[i]<<"\":{\"reads\":"<<count[i].reads<<",\"writes\":"<<count[i].writes<<",\"read_bytes\":"<<count[i].read_bytes<<",\"write_bytes\":"<<count[i].write_bytes<<"}";
  std::cout<<"}\n";
 };
 auto tick=[&](){
  t.clk=0;t.mem_ready=0;t.eval();bool access=false;uint32_t a=0,w=0;uint8_t st=0;
  if(t.mem_valid){
   if(left<0){left=int(rng()%(delay+1));helda=t.mem_addr;heldd=t.mem_wdata;helds=t.mem_wstrb;}
   else if(helda!=t.mem_addr||heldd!=t.mem_wdata||helds!=t.mem_wstrb)throw std::runtime_error("unstable shared bus");
   if(left==0){t.mem_ready=1;t.mem_rdata=t.mem_addr>=0x20000000?0:mem.read(t.mem_addr);access=true;a=t.mem_addr;w=t.mem_wdata;st=t.mem_wstrb;}else --left;
  }
  t.eval();
  if(access){
   if(a==0x20000008 && st){
    if(w&0x80000000){if(roi)throw std::runtime_error("nested ROI");roi=true;roi_id=w&65535;count={};start=cycles;}
    else{if(!roi||roi_id!=(w&65535))throw std::runtime_error("ROI end mismatch");report();roi=false;}
   }else{
    if(roi){auto&c=count[t.mem_dma?2:(t.mem_instr?1:0)];if(st){c.writes++;c.write_bytes+=__builtin_popcount(unsigned(st));}else{c.reads++;c.read_bytes+=4;}}
    if(a==0x20000000 && st)std::cout<<char(w&255)<<std::flush;
    else if(a==0x20000004 && st){if(w!=1)throw std::runtime_error("firmware FAIL exit");finished=true;}
    else if(st)mem.write(a,w,st);
   }
  }
  t.clk=1;t.eval();if(access)left=-1;
  if(t.trap)throw std::runtime_error("CPU trap");if(++cycles>100000000000ULL)throw std::runtime_error("watchdog");
  if(cycles%200000000==0)std::cerr<<"sim cycles="<<cycles<<"\n";
 };
 t.rst=1;for(int i=0;i<5;i++)tick();t.rst=0;auto wall=std::chrono::steady_clock::now();while(!finished)tick();
 std::ifstream checks(argv[3]);uint32_t addr,n;std::string ref;unsigned layers=0;while(checks>>addr>>n>>ref){mem.compare(addr,n,ref);++layers;}
 uint32_t ba=mem.read(0x01008000+24),nb=mem.read(ba);if(nb>100)throw std::runtime_error("invalid box count");
 std::ofstream boxes(argv[4],std::ios::binary);for(uint32_t i=0;i<4+nb*24;i++){char v=char(mem.at(ba+i));boxes.put(v);}
 std::cout<<"DETECTION SOC PASS layers="<<layers<<" boxes="<<nb<<" cycles="<<cycles<<" wall_s="<<std::chrono::duration<double>(std::chrono::steady_clock::now()-wall).count()<<"\n";t.final();return 0;
 }catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}}
