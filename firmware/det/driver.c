#include "driver.h"
#define MMIO(o) (*(volatile uint32_t *)(DET_BASE+(o)))
void text(const char*s){while(*s)*(volatile uint32_t*)0x20000000u=(uint8_t)*s++;}
void num(uint32_t x){char b[11];unsigned n=0;do{b[n++]=(char)('0'+x%10);x/=10;}while(x);while(n){char c[2]={b[--n],0};text(c);}}
void die(const char*s){text("FAIL ");text(s);text("\n");*(volatile uint32_t*)0x20000004u=2;for(;;){}}
int det_conv(uint32_t desc){
 MMIO(DET_REG_DESC_ADDR)=desc;det_fence();MMIO(DET_REG_CTRL)=1;
 uint32_t start=ticks(),s;do{s=MMIO(DET_REG_STATUS);if(ticks()-start>2000000000u)return -3;}while(s&1);
 det_fence();return (s&2) && !(s&12)?0:-(int)(MMIO(DET_REG_ERROR_CODE)+10);
}
int8_t det_requant(int32_t x,uint32_t m,uint32_t s){
 int64_t p=(int64_t)x*m;uint64_t a=p<0?(uint64_t)(-p):(uint64_t)p;
 if(s)a=(a+((uint64_t)1<<(s-1)))>>s;
 int32_t v=a>127?127:(int32_t)a;return (int8_t)(p<0?-v:v);
}
uint32_t det_hash(const int8_t*p,uint32_t n){uint32_t h=2166136261u;while(n--)h=(h^(uint8_t)*p++)*16777619u;return h;}
void det_cpu_conv(const uint32_t*d){
 const int8_t*x=(const int8_t*)d[D_SRC],*w=(const int8_t*)d[D_WEIGHT];int8_t*y=(int8_t*)d[D_DST];const int32_t*q=(const int32_t*)d[D_QPARAM];
 for(uint32_t oy=0;oy<d[D_HOUT];oy++)for(uint32_t ox=0;ox<d[D_WOUT];ox++)for(uint32_t oc=0;oc<d[D_COUT];oc++){
  int32_t a=0;
  for(uint32_t ky=0;ky<d[D_KH];ky++)for(uint32_t kx=0;kx<d[D_KW];kx++){
   int32_t iy=(int32_t)(oy*d[D_SH]+ky)-(int32_t)d[D_PT],ix=(int32_t)(ox*d[D_SW]+kx)-(int32_t)d[D_PL];
   if(iy<0||ix<0||iy>=(int32_t)d[D_H]||ix>=(int32_t)d[D_W])continue;
   for(uint32_t c=0;c<d[D_CIN];c++)a+=(int32_t)x[((uint32_t)iy*d[D_W]+(uint32_t)ix)*d[D_CIN]+c]*(int32_t)w[((oc*d[D_KH]+ky)*d[D_KW]+kx)*d[D_CIN]+c];
  }
  int64_t z=(int64_t)a+q[oc*5];if(z>2147483647LL||z< -2147483648LL)die("bias overflow");
  unsigned j=z<0?3:1;y[(oy*d[D_WOUT]+ox)*d[D_COUT]+oc]=det_requant((int32_t)z,(uint32_t)q[oc*5+j],(uint32_t)q[oc*5+j+1]);
 }
}
void *memset(void*d,int c,size_t n){uint8_t*p=d;while(n--)*p++=(uint8_t)c;return d;}
void *memcpy(void*d,const void*s,size_t n){uint8_t*p=d;const uint8_t*q=s;while(n--)*p++=*q++;return d;}
