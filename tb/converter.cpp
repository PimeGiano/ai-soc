#include "Vfuse_requant.h"
#include "verilated.h"
#include <random>
#include <iostream>
#include <stdexcept>
#include <deque>
struct Item{int8_t value;uint16_t token;};
int main(int argc,char**argv){try{Verilated::commandArgs(argc,argv);Vfuse_requant t;std::mt19937 r(77);unsigned count=0;
 auto edge=[&](){t.clk=1;t.eval();t.clk=0;t.eval();};t.rst=1;t.cfg_valid=0;t.in_valid=0;t.out_ready=0;edge();t.rst=0;
 for(unsigned sh: {0u,1u,31u,62u}){
  t.cfg_valid=1;t.m0=0x7fffffff;t.m1=3;t.s0=sh;t.s1=sh;t.eval();if(!t.cfg_ready)throw std::runtime_error("cfg ready");edge();t.cfg_valid=0;
  std::deque<Item> expected;int next=0;bool holding=false;int8_t last=0;uint16_t token=0;
  for(unsigned cycle=0;next<512||!expected.empty()||t.out_valid;cycle++){
   if(cycle>30000)throw std::runtime_error("converter watchdog");
   t.in_valid=next<512;t.in_data=uint8_t(next/2-128);t.src_id=next%2;t.in_token=next;t.out_ready=(r()%4)!=0;t.eval();
   if(holding && (!t.out_valid||int8_t(t.out_data)!=last||t.out_token!=token))throw std::runtime_error("unstable converter output");
   if(t.out_valid && t.out_ready){if(expected.empty()||expected.front().value!=int8_t(t.out_data)||expected.front().token!=t.out_token)throw std::runtime_error("converter mismatch");expected.pop_front();++count;}
   holding=t.out_valid&&!t.out_ready;last=int8_t(t.out_data);token=t.out_token;
   if(t.in_valid && t.in_ready){int64_t p=int64_t(int8_t(t.in_data))*(t.src_id?3:0x7fffffff);uint64_t a=p<0?-p:p;if(sh)a=(a+(1ULL<<(sh-1)))>>sh;int v=a>127?127:int(a);expected.push_back({int8_t(p<0?-v:v),uint16_t(next)});++next;}
   edge();
  }
 }
 // Reset must discard a blocked result and invalidate configuration.
 t.in_valid=1;t.in_data=1;t.out_ready=0;edge();t.rst=1;edge();t.rst=0;t.in_valid=0;t.eval();if(t.out_valid||t.in_ready)throw std::runtime_error("reset contract");
 std::cout<<"INPUT CONVERTER PASS samples="<<count<<" backpressure/reset\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
