from pathlib import Path
import json
import numpy as np
from memory import Image
from reference import conv,materialize
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'build/det';OUT.mkdir(parents=True,exist_ok=True)
r=np.random.default_rng(20261028);image=Image();jobs=[]
def case(x,w,q,stride,pads,fusion=None,expected_error=0,change=None):
    ho=(x.shape[0]+pads[0]+pads[1]-w.shape[1])//stride+1;wo=(x.shape[1]+pads[2]+pads[3]-w.shape[2])//stride+1
    expected=conv(x,w,q,stride,pads)
    if fusion:
        low,high,m0,s0,m1,s1,order=fusion
        f=[image.put(low.tobytes()),*low.shape,image.put(high.tobytes()),*high.shape,2,1,m0,s0,m1,s1,order,0]
        fa=image.words(f);src=0
    else:fa=0;src=image.put(x.tobytes())
    dst=image.put(bytes([0x55])*(expected.size+4));wa=image.put(w.tobytes());qa=image.put(q.astype('<i4').tobytes())
    act=int(r.integers(0,3));q[:,3]=q[:,1] if act==0 else (0 if act==1 else 1);q[:,4]=q[:,2] if act==0 else 9
    # Rebuild both q block and expected after selecting activation.
    qa=image.put(q.astype('<i4').tobytes());expected=conv(x,w,q,stride,pads)
    tic=int(r.choice([4,8,16]));toc=int(r.choice([4,8,16]))
    d=[src,wa,dst,qa,*x.shape,w.shape[0],w.shape[1],w.shape[2],stride,stride,*pads,ho,wo,int(r.integers(1,5)),int(r.integers(1,5)),tic,toc,act,5 if fusion else 1,fa]+[0]*7
    assert len(d)==32
    if change:change(d)
    da=image.words(d);name=f'case_{len(jobs):03d}';ref=OUT/(name+'.bin');ref.write_bytes(expected.tobytes())
    jobs.append((da,dst,expected.size,str(ref),expected_error))
for i in range(100):
    h,ww=int(r.integers(3,9)),int(r.integers(3,9));ci=int(r.choice([1,3,7,17,19]));co=int(r.choice([1,3,5,17]))
    kh=int(r.choice([1,3]));st=int(r.choice([1,2]));pads=tuple(int(x) for x in r.integers(0,2,4))
    x=r.integers(-127,128,(h,ww,ci),dtype=np.int8);w=r.integers(-8,9,(co,kh,kh,ci),dtype=np.int8)
    q=np.tile(np.array([0,3,6,1,9]),(co,1));q[:,0]=r.integers(-1000,1001,co)
    case(x,w,q,st,pads)
for i in range(50):
    h,ww=int(r.integers(1,5)),int(r.integers(1,5));c0,c1=int(r.choice([1,3,7,17])),int(r.choice([1,5,19]));co=int(r.choice([1,5,17]))
    lo=r.integers(-127,128,(h,ww,c0),dtype=np.int8);hi=r.integers(-127,128,(h*2,ww*2,c1),dtype=np.int8)
    m0,s0,m1,s1=3,int(r.choice([0,1,3,62])),5,int(r.choice([0,2,4,62]));order=i%2
    x=materialize(lo,hi,m0,s0,m1,s1,order);kh=1 if h==1 else 3
    w=r.integers(-8,9,(co,kh,kh,c0+c1),dtype=np.int8);q=np.tile(np.array([0,3,6,1,9]),(co,1))
    case(x,w,q,1,(1,1,1,1) if kh==3 else (0,0,0,0),(lo,hi,m0,s0,m1,s1,order))
x=np.ones((3,3,3),dtype=np.int8);w=np.ones((5,1,1,3),dtype=np.int8);q=np.tile(np.array([0,1,0,1,0]),(5,1))
for change in [lambda d:d.__setitem__(21,32),lambda d:d.__setitem__(6,0),lambda d:d.__setitem__(23,3),lambda d:d.__setitem__(25,1)]:case(x,w,q,1,(0,0,0,0),expected_error=2,change=change)
case(x,w,q,1,(0,0,0,0),expected_error=4,change=lambda d:d.__setitem__(2,d[0]))
# Maximum supported reduction length and saturation/negative rounding.
large_x=r.integers(-127,128,(3,3,1024),dtype=np.int8)
large_w=r.integers(-127,128,(1,3,3,1024),dtype=np.int8)
case(large_x,large_w,np.array([[0,1,20,1,20]]),1,(0,0,0,0))
def bad_q(d):
    import struct
    blob=dict(image.parts)[d[3]];a=list(struct.unpack('<'+'I'*(len(blob)//4),blob));a[2]=63;d[3]=image.words(a)
case(x,w,q,1,(0,0,0,0),expected_error=5,change=bad_q)
def bad_f(d):
    import struct
    a=list(struct.unpack('<16I',dict(image.parts)[d[24]]));a[8]=3;d[24]=image.words(a)
lo=np.ones((2,2,1),dtype=np.int8);hi=np.ones((4,4,2),dtype=np.int8);xx=materialize(lo,hi,1,0,1,0)
case(xx,np.ones((1,1,1,3),dtype=np.int8),np.array([[0,1,0,1,0]]),1,(0,0,0,0),(lo,hi,1,0,1,0,0),expected_error=2,change=bad_f)
image.write(OUT/'vectors.mem')
(OUT/'jobs.txt').write_text(''.join(f'{a} {b} {c} {path} {err}\n' for a,b,c,path,err in jobs))
(ROOT/'results/det/vectors.json').write_text(json.dumps({'seed':20261028,'ordinary':101,'fused':50,'invalid':7,'image_bytes':image.next-0x01010000},indent=2)+'\n')
print('Generated',len(jobs),'jobs')
