"""Synthetic controlled experiment: equal-scale vs unequal-scale M/F."""
from pathlib import Path
import struct,json
import numpy as np
from memory import Image
from reference import materialize,conv,requant
from export_model import fnv
ROOT=Path(__file__).resolve().parents[1];r=np.random.default_rng(91)
lo=r.integers(-127,128,(5,5,7),dtype=np.int8);hi=r.integers(-127,128,(10,10,19),dtype=np.int8)
w=r.integers(-5,6,(17,3,3,26),dtype=np.int8);q=np.tile(np.array([0,3,6,3,6]),(17,1))
for label,ms in [('equal',(1,0,1,0)),('unequal',(3,2,5,3))]:
 for mode in ['M','F']:
  folder=ROOT/f'build/probe_{label}_{mode}';folder.mkdir(parents=True,exist_ok=True)
  image=Image();la=image.put(lo.tobytes());ha=image.put(hi.tobytes());wa=image.put(w.tobytes());qa=image.put(q.astype('<i4').tobytes())
  x=materialize(lo,hi,*ms);y=conv(x,w,q,1,(1,1,1,1));ya=image.put(bytes(y.size+4));ops=[]
  def op(t,a,b,d,shape,c1=0,ratio=1,params=(1,0,1,0),desc=0,expected=None,start=0,end=0,layer=0):
   ops.append([t,a,b,d,*shape,c1,ratio,0,*params,desc,fnv(expected),expected.size,layer,0,0,start,end,0,0])
  if mode=='M':
   up=np.repeat(np.repeat(requant(lo,*ms[:2]),2,0),2,1);ua=image.put(bytes(up.size+4));xa=image.put(bytes(x.size+4))
   op(5,la,0,ua,up.shape,ratio=2,params=(*ms[:2],1,0),expected=up,start=7)
   op(3,ua,ha,xa,(10,10,7),c1=19,params=(1,0,*ms[2:]),expected=x,layer=1);fa=0
  else:xa=0;fa=image.words([la,*lo.shape,ha,*hi.shape,2,1,*ms,0,0])
  d=[xa,wa,ya,qa,10,10,26,17,3,3,1,1,1,1,1,1,10,10,4,4,16,16,0,1 if mode=='M' else 5,fa]+[0]*7
  da=image.words(d);op(1,xa,0,ya,y.shape,desc=da,expected=y,start=7 if mode=='F' else 0,end=7,layer=2)
  oa=image.words([v for a in ops for v in a]);ba=image.put(bytes(2404));header=[0x44455431,len(ops),oa,0,0,0,ba,0]+[0]*8
  image.parts.append((0x01008000,struct.pack('<16I',*header)));image.write(folder/'model.mem');(folder/'expected.bin').write_bytes(y.tobytes());(folder/'checks.txt').write_text(f'{ya} {y.size} {folder/"expected.bin"}\n')
