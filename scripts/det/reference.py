"""Independent NHWC/OHWI integer reference; no RTL scheduling logic."""
import numpy as np

def requant(x,m,s):
    x=np.asarray(x,dtype=np.int64);m=np.asarray(m,dtype=np.int64);s=np.asarray(s,dtype=np.int64)
    product=x*m;mag=np.abs(product)
    rounded=(mag+np.where(s>0,np.left_shift(np.int64(1),np.maximum(s-1,0)),0))>>s
    return np.clip(np.where(product<0,-rounded,rounded),-127,127).astype(np.int8)

def materialize(low,high,m0,s0,m1,s1,order=0):
    lo=np.repeat(np.repeat(requant(low,m0,s0),2,axis=0),2,axis=1)
    hi=requant(high,m1,s1)
    assert lo.shape[:2]==hi.shape[:2]
    return np.concatenate([lo,hi] if order==0 else [hi,lo],axis=2)

def conv(x,w,q,stride=1,padding=(0,0,0,0)):
    pt,pb,pl,pr=padding;h,ww,ci=x.shape;co,kh,kw,wci=w.shape
    assert ci==wci
    ho=(h+pt+pb-kh)//stride+1;wo=(ww+pl+pr-kw)//stride+1
    xp=np.pad(x.astype(np.int64),((pt,pb),(pl,pr),(0,0)))
    acc=np.zeros((ho,wo,co),dtype=np.int64)
    # Independent dense dot products, never use hardware tile loops.
    for ky in range(kh):
        for kx in range(kw):
            acc+=xp[ky:ky+ho*stride:stride,kx:kx+wo*stride:stride] @ w[:,ky,kx,:].astype(np.int64).T
    z=acc+q[:,0].astype(np.int64)
    assert np.all(z>=-2**31) and np.all(z<2**31)
    m=np.where(z<0,q[:,3],q[:,1]);s=np.where(z<0,q[:,4],q[:,2])
    return requant(z,m,s)
