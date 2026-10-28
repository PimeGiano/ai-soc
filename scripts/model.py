"""Minimal explicit Darknet tiny inference/import, no opaque framework runtime."""
from pathlib import Path
import sys,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python'))
from PIL import Image,ImageDraw

def config(path):
    nodes=[]
    for line in Path(path).read_text().splitlines():
        line=line.split('#')[0].strip()
        if not line:continue
        if line.startswith('['):nodes.append({'type':line[1:-1]})
        else:
            k,v=line.split('=',1);nodes[-1][k.strip()]=v.strip()
    return nodes[1:]

def weights(path,nodes):
    raw=Path(path).read_bytes();major,minor,_=np.frombuffer(raw[:12],dtype='<i4')
    pos=20 if major*10+minor>=2 and major<1000 and minor<1000 else 16
    def get(n):
        nonlocal pos
        a=np.frombuffer(raw,dtype='<f4',count=n,offset=pos).copy();pos+=n*4;return a
    shapes=[];ci=3
    for i,node in enumerate(nodes):
        t=node['type']
        if t=='convolutional':
            co=int(node['filters']);k=int(node['size']);bias=get(co)
            if int(node.get('batch_normalize','0')):
                scale,mean,var=get(co),get(co),get(co);factor=scale/np.sqrt(var+1e-5)
                bias=bias-mean*factor
            else:factor=np.ones(co,dtype=np.float32)
            w=get(co*ci*k*k).reshape(co,ci,k,k).transpose(0,2,3,1)*factor[:,None,None,None]
            node['weight']=w.copy();node['bias']=bias;ci=co
        elif t=='route':
            ids=[int(v) for v in node['layers'].split(',')];ids=[i+j if j<0 else j for j in ids];node['ids']=ids
            ci=sum(shapes[j] for j in ids)//int(node.get('groups','1'))
        shapes.append(ci)
    assert pos==len(raw),(pos,len(raw))
    return hashlib.sha256(raw).hexdigest()

def preprocess(path,size=160):
    im=Image.open(path).convert('RGB');w,h=im.size;r=min(size/w,size/h);nw,nh=int(w*r),int(h*r)
    resized=im.resize((nw,nh),Image.Resampling.BILINEAR);canvas=Image.new('RGB',(size,size),(128,128,128));canvas.paste(resized,((size-nw)//2,(size-nh)//2))
    return np.asarray(canvas,dtype=np.float32)/255.,{'original':[w,h],'resized':[nw,nh],'offset':[(size-nw)//2,(size-nh)//2],'size':size}

def float_conv(x,w,b,stride,pad):
    co,k,_,ci=w.shape;h,ww,_=x.shape;ho=(h+2*pad-k)//stride+1;wo=(ww+2*pad-k)//stride+1
    xp=np.pad(x,((pad,pad),(pad,pad),(0,0)));y=np.broadcast_to(b,(ho,wo,co)).copy()
    for ky in range(k):
        for kx in range(k):y+=xp[ky:ky+ho*stride:stride,kx:kx+wo*stride:stride]@w[:,ky,kx,:].T
    return y

def maxpool(x,k,st):
    h,w,c=x.shape;ho=(h+1-k)//st+1;wo=(w+1-k)//st+1
    xp=np.pad(x,((0,1),(0,1),(0,0)),constant_values=-127 if x.dtype==np.int8 else -np.inf)
    return np.maximum.reduce([xp[y:y+ho*st:st,z:z+wo*st:st] for y in range(k) for z in range(k)])

def forward(nodes,x):
    outputs=[]
    for n in nodes:
        t=n['type']
        if t=='convolutional':
            x=float_conv(x,n['weight'],n['bias'],int(n['stride']),int(n['size'])//2 if int(n.get('pad','0')) else 0)
            if n['activation']=='leaky':x=np.where(x<0,x*.1,x)
            elif n['activation']!='linear':raise ValueError(n['activation'])
        elif t=='maxpool':x=maxpool(x,int(n['size']),int(n['stride']))
        elif t=='upsample':x=np.repeat(np.repeat(x,int(n['stride']),0),int(n['stride']),1)
        elif t=='route':
            a=[outputs[j] for j in n['ids']];x=np.concatenate(a,2) if len(a)>1 else a[0]
            if 'groups' in n:
                group=int(n['groups']);gid=int(n['group_id']);ch=x.shape[2]//group;x=x[:,:,gid*ch:(gid+1)*ch]
        elif t!='yolo':raise ValueError(t)
        outputs.append(x)
    return outputs

def ratio(v):
    s=30
    while v*(1<<s)>0x7fffffff:s-=1
    if s<0:raise ValueError('scale ratio too large')
    return int(np.floor(v*(1<<s)+.5)),s

def roundaway(x):return np.copysign(np.floor(np.abs(x)+.5),x)

def decode(heads,threshold=.25,iou=.45,max_boxes=100):
    boxes=[]
    for raw,n,size in heads:
        h,w,channels=raw.shape;classes=int(n['classes']);masks=[int(a) for a in n['mask'].split(',')];anchors=[float(a) for a in n['anchors'].split(',')];sxy=float(n.get('scale_x_y','1'))
        raw=raw.reshape(h,w,len(masks),classes+5).astype(np.float64)
        prob=1/(1+np.exp(-np.clip(raw,-80,80)))
        for y in range(h):
            for x in range(w):
                for a,mask in enumerate(masks):
                    cls=int(np.argmax(prob[y,x,a,5:]));score=float(prob[y,x,a,4]*prob[y,x,a,5+cls])
                    if score<threshold:continue
                    cx=(prob[y,x,a,0]*sxy-(sxy-1)/2+x)/w;cy=(prob[y,x,a,1]*sxy-(sxy-1)/2+y)/h
                    bw=np.exp(np.clip(raw[y,x,a,2],-16,16))*anchors[mask*2]/size;bh=np.exp(np.clip(raw[y,x,a,3],-16,16))*anchors[mask*2+1]/size
                    boxes.append([float(cx-bw/2),float(cy-bh/2),float(cx+bw/2),float(cy+bh/2),score,cls])
    boxes=sorted(boxes,key=lambda b:-b[4]);kept=[]
    for b in boxes:
        ok=True
        for a in kept:
            if a[5]!=b[5]:continue
            inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
            if union>0 and inter/union>iou:ok=False;break
        if ok:kept.append(b)
        if len(kept)>=max_boxes:break
    return kept

def draw(path,boxes,meta,out):
    im=Image.open(path).convert('RGB');d=ImageDraw.Draw(im);nw,nh=meta['resized'];ox,oy=meta['offset'];size=meta['size'];ow,oh=meta['original']
    for x0,y0,x1,y1,score,cls in boxes:
        coords=[(x0*size-ox)*ow/nw,(y0*size-oy)*oh/nh,(x1*size-ox)*ow/nw,(y1*size-oy)*oh/nh]
        d.rectangle(coords,outline='red',width=3);d.text((coords[0],max(0,coords[1]-12)),f'class {cls} {score:.2f}',fill='red')
    im.save(out)
