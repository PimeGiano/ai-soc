#include "driver.h"
typedef struct {float x0,y0,x1,y1,score;uint32_t label;} Box;
static Box candidates[512];
static float fp(uint32_t x){union{uint32_t u;float f;}v;v.u=x;return v.f;}
static float ex(float x){
 if(x>16)x=16;
 if(x< -16)x=-16;
 int n=(int)(x*1.44269504089f+(x>=0?.5f:-.5f));float r=x-(float)n*.69314718056f,p=1,term=1;
 for(int k=1;k<=8;k++){term*=r/(float)k;p+=term;}
 union{uint32_t u;float f;}v;v.u=(uint32_t)(n+127)<<23;return p*v.f;
}
static float sigmoid(float x){return 1.f/(1.f+ex(-x));}
static float fmax2(float a,float b){return a>b?a:b;}
static float fmin2(float a,float b){return a<b?a:b;}
void det_postprocess(const uint32_t*h){
 uint32_t nh=h[4],count=0;const uint32_t*heads=(const uint32_t*)h[5];
 for(uint32_t j=0;j<nh;j++){
  const uint32_t*d=heads+j*16;const int8_t*x=(const int8_t*)d[0];uint32_t hh=d[1],ww=d[2],cc=d[3],classes=d[12],size=d[13];float scale=fp(d[4]),sxy=fp(d[5]);
  if(classes+5!=cc/3)die("head format");
  for(uint32_t y=0;y<hh;y++)for(uint32_t z=0;z<ww;z++)for(uint32_t a=0;a<3;a++){
   const int8_t*v=x+(y*ww+z)*cc+a*(classes+5);uint32_t label=0;
   for(uint32_t c=1;c<classes;c++)if(v[5+c]>v[5+label])label=c;
   float score=sigmoid(v[4]*scale)*sigmoid(v[5+label]*scale);if(score<.25f)continue;
   if(count==512)die("candidate overflow");
   float cx=(sigmoid(v[0]*scale)*sxy-(sxy-1.f)*.5f+(float)z)/(float)ww;
   float cy=(sigmoid(v[1]*scale)*sxy-(sxy-1.f)*.5f+(float)y)/(float)hh;
   float bw=ex(v[2]*scale)*(float)d[6+a*2]/(float)size,bh=ex(v[3]*scale)*(float)d[7+a*2]/(float)size;
   candidates[count++]=(Box){cx-bw*.5f,cy-bh*.5f,cx+bw*.5f,cy+bh*.5f,score,label};
  }
 }
 // Stable selection sort: equal scores preserve initial source order.
 for(uint32_t i=1;i<count;i++){Box v=candidates[i];uint32_t k=i;while(k && candidates[k-1].score<v.score){candidates[k]=candidates[k-1];k--;}candidates[k]=v;}
 uint32_t*out=(uint32_t*)h[6];Box*boxes=(Box*)(out+1);uint32_t kept=0;
 for(uint32_t i=0;i<count && kept<100;i++){
  Box b=candidates[i];int accept=1;
  for(uint32_t k=0;k<kept;k++){
   Box a=boxes[k];if(a.label!=b.label)continue;
   float inter=fmax2(0,fmin2(a.x1,b.x1)-fmax2(a.x0,b.x0))*fmax2(0,fmin2(a.y1,b.y1)-fmax2(a.y0,b.y0));
   float un=(a.x1-a.x0)*(a.y1-a.y0)+(b.x1-b.x0)*(b.y1-b.y0)-inter;
   if(un>0 && inter/un>.45f){accept=0;break;}
  }
  if(accept)boxes[kept++]=b;
 }
 *out=kept;
}
