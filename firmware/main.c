#include "driver.h"
// Host graph header fixed at 0x01008000: magic, nops, ops_addr, mode.
// 24-word records: type, src0, src1, dst, H,W,C0,C1,R0,ORDER,M0,S0,M1,S1,
// descriptor, expected_hash, nbytes, layer_id, pool_size, pool_stride, roi_id, flags,0,0.
static void materialize(const uint32_t*o){
 const int8_t*a=(const int8_t*)o[1],*b=(const int8_t*)o[2];int8_t*y=(int8_t*)o[3];
 uint32_t h=o[4],w=o[5],c0=o[6],c1=o[7],r=o[8];
 for(uint32_t iy=0;iy<h;iy++)for(uint32_t ix=0;ix<w;ix++)for(uint32_t c=0;c<c0+c1;c++){
  uint32_t first=o[9]?c1:c0;int low=o[9]?c>=first:c<first;uint32_t cc=c<first?c:c-first;
  int8_t v=low?a[((iy/r)*(w/r)+ix/r)*c0+cc]:b[(iy*w+ix)*c1+cc];
  y[(iy*w+ix)*(c0+c1)+c]=det_requant(v,o[low?10:12],o[low?11:13]);
 }
}
static void pool(const uint32_t*o){
 const int8_t*x=(const int8_t*)o[1];int8_t*y=(int8_t*)o[3];uint32_t h=o[4],w=o[5],c=o[6],k=o[18],st=o[19];
 // Darknet size2 pools use total padding=1: asymmetric right/bottom at stride1.
 uint32_t ho=(h+1-k)/st+1,wo=(w+1-k)/st+1;
 for(uint32_t oy=0;oy<ho;oy++)for(uint32_t ox=0;ox<wo;ox++)for(uint32_t ch=0;ch<c;ch++){
  int8_t v=-127;for(uint32_t ky=0;ky<k;ky++)for(uint32_t kx=0;kx<k;kx++){
   uint32_t iy=oy*st+ky,ix=ox*st+kx;if(iy<h&&ix<w){int8_t t=x[(iy*w+ix)*c+ch];if(t>v)v=t;}
  }y[(oy*wo+ox)*c+ch]=v;
 }
}
static void slice(const uint32_t*o){
 const int8_t*x=(const int8_t*)o[1];int8_t*y=(int8_t*)o[3];
 for(uint32_t p=0;p<o[4]*o[5];p++)for(uint32_t c=0;c<o[7];c++)y[p*o[7]+c]=x[p*o[6]+o[8]+c];
}
extern void det_postprocess(const uint32_t *header);
static void upsample(const uint32_t*o){
 const int8_t*x=(const int8_t*)o[1];int8_t*y=(int8_t*)o[3];uint32_t h=o[4],w=o[5],c=o[6],r=o[8];
 for(uint32_t iy=0;iy<h;iy++)for(uint32_t ix=0;ix<w;ix++)for(uint32_t ch=0;ch<c;ch++)y[(iy*w+ix)*c+ch]=det_requant(x[((iy/r)*(w/r)+ix/r)*c+ch],o[10],o[11]);
}
int main(void){
 const uint32_t*h=(const uint32_t*)0x01008000u;if(h[0]!=0x44455431u)die("graph magic");
 if(*(volatile uint32_t*)(DET_BASE+DET_REG_VERSION)!=DET_VERSION)die("version");
 const uint32_t*ops=(const uint32_t*)h[2];uint32_t mode=h[3],whole=h[7];
 if(whole){det_fence();*(volatile uint32_t*)0x20000008u=0x8000fffeu;}
 for(uint32_t i=0;i<h[1];i++){
  const uint32_t*o=ops+i*24;uint32_t roi=o[20];
  if(roi && !whole){det_fence();*(volatile uint32_t*)0x20000008u=0x80000000u|roi;}
  if(o[0]==1){if(mode==2)det_cpu_conv((const uint32_t*)o[14]);else{int e=det_conv(o[14]);if(e){num((uint32_t)-e);die("conv");}}}
  else if(o[0]==2)pool(o);else if(o[0]==3)materialize(o);else if(o[0]==4)slice(o);else if(o[0]==5)upsample(o);else die("op");
  if(o[21] && !whole){det_fence();*(volatile uint32_t*)0x20000008u=o[21];}
 }
 if(whole){det_fence();*(volatile uint32_t*)0x20000008u=0x0000fffeu;}
 // Verification and printing are outside all measurement regions.
 for(uint32_t i=0;i<h[1];i++){const uint32_t*o=ops+i*24;
  if(det_hash((const int8_t*)o[3],o[16])!=o[15]){text("layer ");num(o[17]);die("hash");}
  text("LAYER ");num(o[17]);text(" PASS\n");
 }
 det_fence();*(volatile uint32_t*)0x20000008u=0x8000fffdu;
 det_postprocess(h);det_fence();*(volatile uint32_t*)0x20000008u=0x0000fffdu;
 text("DETECTION GRAPH PASS\n");*(volatile uint32_t*)0x20000004u=1;for(;;){}
}
