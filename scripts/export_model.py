from pathlib import Path
import argparse,json,struct,hashlib
import numpy as np
from model import ROOT,config,weights,preprocess,forward,maxpool,ratio,roundaway,decode,draw
from reference import requant,conv,materialize
from memory import Image

def fnv(x):
    h=2166136261
    for v in x.tobytes():h=((h^v)*16777619)&0xffffffff
    return h

def export(model,mode,photo,size=160,calibration=None):
    out=ROOT/f'build/{model}_{mode}';out.mkdir(parents=True,exist_ok=True)
    result=ROOT/'results'/f'{model}_{mode}';result.mkdir(parents=True,exist_ok=True)
    nodes=config(ROOT/f'data/{model}.cfg');whash=weights(ROOT/f'data/{model}.weights',nodes)
    inputf,meta=preprocess(photo,size);fp=forward(nodes,inputf)
    # Calibration may be an independent image list. Demo default is explicitly tagged.
    calfiles=calibration or [photo];maxima=[0.]*len(nodes)
    for path in calfiles:
        cal=forward(nodes,preprocess(path,size)[0])
        maxima=[max(m,float(np.max(np.abs(a)))) for m,a in zip(maxima,cal)]
    image=Image();ops=[];manifest=[];arrays=[];scales=[];addrs=[];fusion={};heads=[]
    xin=requant(roundaway(inputf*127).astype(np.int32),1,0);prev=xin;prevscale=1/127;prevaddr=image.put(xin.tobytes())
    def alloc(a):return image.put(a.tobytes())
    def op(t,src0,src1,dst,shape,c1=0,r0=1,order=0,ms=(1,0,1,0),desc=0,expected=None,layer=0,pool=(0,0),roi=0,end=0):
        a=[t,src0,src1,dst,*shape,c1,r0,order,*ms,desc,fnv(expected),expected.size,layer,*pool,roi,end,0,0]
        assert len(a)==24,len(a);ops.append(a)
    for i,n in enumerate(nodes):
        t=n['type'];outscale=prevscale;addr=prevaddr
        if t=='convolutional':
            ci=prev.shape[2];co,k,_,_=n['weight'].shape;st=int(n['stride']);pad=k//2 if int(n.get('pad','0')) else 0
            sw=np.maximum(np.max(np.abs(n['weight']),axis=(1,2,3))/127,1e-12)
            qw=np.clip(roundaway(n['weight']/sw[:,None,None,None]),-127,127).astype(np.int8)
            outscale=max(maxima[i]/120,1e-8)
            bias=roundaway(n['bias']/(prevscale*sw)).astype(np.int64);assert np.max(np.abs(bias))<2**31-151000000
            q=np.zeros((co,5),dtype=np.int64);q[:,0]=bias
            act=2 if n['activation']=='leaky' else 0
            for c in range(co):
                q[c,1],q[c,2]=ratio(prevscale*float(sw[c])/outscale);q[c,3],q[c,4]=ratio(prevscale*float(sw[c])/outscale*(.1 if act==2 else 1))
            y=conv(prev,qw,q,st,(pad,)*4);addr=image.put(bytes(y.size+4));wa=alloc(qw);qa=alloc(q.astype('<i4'));src=prevaddr;fa=0;fused=False
            if i-1 in fusion and mode=='F':
                info=fusion[i-1];fa=image.words(info['words']);src=0;fused=True
            th,tw=8,8;tic,toc=16,16
            d=[src,wa,addr,qa,*prev.shape,co,k,k,st,st,pad,pad,pad,pad,*y.shape[:2],th,tw,tic,toc,act,5 if fused else 1,fa]+[0]*7
            da=image.words(d)
            op(1,src,0,addr,y.shape,desc=da,expected=y,layer=i,roi=(i+1 if fused else 0),end=(i+1 if i-1 in fusion else 0))
            ref=out/f'layer_{i}.bin';ref.write_bytes(y.tobytes())
            manifest.append({'layer':i,'type':t,'shape':list(y.shape),'address':addr,'descriptor':da,'fused':fused,'reference':str(ref),'hash':fnv(y),'scale':outscale})
            prev=y
        elif t=='maxpool':
            y=maxpool(prev,int(n['size']),int(n['stride']));addr=image.put(bytes(y.size+4));op(2,prevaddr,0,addr,prev.shape,expected=y,layer=i,pool=(int(n['size']),int(n['stride'])));prev=y
        elif t=='upsample':
            assert int(n['stride'])==2
            prev=np.repeat(np.repeat(prev,2,0),2,1);addr=0 # Deferred to consumer route; no standalone materialization yet.
        elif t=='route':
            ids=n['ids'];aa=[arrays[j] for j in ids]
            if len(ids)==1:
                prev=aa[0];outscale=scales[ids[0]];addr=addrs[ids[0]]
                if 'groups' in n:
                    ch=prev.shape[2]//int(n['groups']);start=int(n['group_id'])*ch;y=prev[:,:,start:start+ch].copy();addr=image.put(bytes(y.size+4))
                    op(4,addrs[ids[0]],0,addr,prev.shape,c1=ch,r0=start,expected=y,layer=i);prev=y
            else:
                assert len(ids)==2
                ups=[j for j in ids if nodes[j]['type']=='upsample']
                outscale=max(scales[j] for j in ids)
                if ups:
                    assert len(ups)==1 and i+1<len(nodes) and nodes[i+1]['type']=='convolutional'
                    ui=ups[0];li=ui-1;hi=ids[1] if ids[0]==ui else ids[0];order=0 if ids[0]==ui else 1
                    lo,high=arrays[li],arrays[hi];m0,s0=ratio(scales[li]/outscale);m1,s1=ratio(scales[hi]/outscale)
                    y=materialize(lo,high,m0,s0,m1,s1,order)
                    fusion[i]={'words':[addrs[li],*lo.shape,addrs[hi],*high.shape,2,1,m0,s0,m1,s1,order,0]}
                    if mode!='F':
                        up=np.repeat(np.repeat(requant(lo,m0,s0),2,0),2,1);ua=image.put(bytes(up.size+4));roi=i+2
                        op(5,addrs[li],0,ua,up.shape,r0=2,ms=(m0,s0,1,0),expected=up,layer=ui,roi=roi)
                        addr=image.put(bytes(y.size+4));op(3,ua,addrs[hi],addr,(*y.shape[:2],lo.shape[2]),c1=high.shape[2],order=order,ms=(1,0,m1,s1),expected=y,layer=i)
                    else:addr=0
                else:
                    m0,s0=ratio(scales[ids[0]]/outscale);m1,s1=ratio(scales[ids[1]]/outscale)
                    y=np.concatenate([requant(aa[0],m0,s0),requant(aa[1],m1,s1)],2);addr=image.put(bytes(y.size+4))
                    op(3,addrs[ids[0]],addrs[ids[1]],addr,aa[0].shape,c1=aa[1].shape[2],ms=(m0,s0,m1,s1),expected=y,layer=i)
                prev=y
        elif t=='yolo':heads.append((prev.astype(np.float32)*prevscale,n,size,prevaddr,prevscale))
        else:raise ValueError(t)
        arrays.append(prev);scales.append(outscale);addrs.append(addr);prevscale=outscale;prevaddr=addr
    # CPU decoder metadata: raw NHWC addr,H,W,C,scale,float scale_xy,3 anchor pairs,classes,size.
    hd=[]
    for raw,n,sz,a,sc in heads:
        anchors=[int(v) for v in n['anchors'].split(',')];mask=[int(v) for v in n['mask'].split(',')]
        fl=lambda v:struct.unpack('<I',struct.pack('<f',v))[0]
        hd += [a,*raw.shape,fl(sc),fl(float(n.get('scale_x_y','1'))),*[anchors[2*j+k] for j in mask for k in (0,1)],int(n['classes']),sz,0,0]
    ha=image.words(hd);oa=image.words([v for a in ops for v in a]);boxesaddr=image.put(bytes(4+100*24))
    header=[0x44455431,len(ops),oa,2 if mode=='B0' else 0,len(heads),ha,boxesaddr]+[0]*9
    image.parts.append((0x01008000,struct.pack('<16I',*header)))
    image.write(out/'model.mem');(out/'checks.txt').write_text(''.join(f'{m["address"]} {np.prod(m["shape"])} {m["reference"]}\n' for m in manifest))
    boxes=decode([(a,n,z) for a,n,z,_,_ in heads]);floatboxes=decode([(fp[i],n,size) for i,n in enumerate(nodes) if n['type']=='yolo'])
    if mode=='F':
        draw(photo,boxes,meta,result/'detections.png');draw(photo,floatboxes,meta,result/'float_detections.png')
    summary={'model':model,'mode':mode,'input':str(photo),'size':size,'weights_sha256':whash,'cfg_sha256':hashlib.sha256((ROOT/f'data/{model}.cfg').read_bytes()).hexdigest(),'calibration':list(map(str,calfiles)),'calibration_demo_only':calibration is None,'ops':len(ops),'fusions':len(fusion),'allocated_bytes':image.next-0x01010000,'layers':manifest,'boxes_address':boxesaddr,'boxes':boxes,'float_boxes':floatboxes,'preprocess':meta}
    (out/'manifest.json').write_text(json.dumps(summary,indent=2)+'\n');(result/'reference.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(model,mode,'ops',len(ops),'fusions',len(fusion),'boxes',len(boxes),'allocated',summary['allocated_bytes'])
    return out
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--model',choices=['yolov3-tiny','yolov4-tiny'],default='yolov3-tiny');a.add_argument('--mode',choices=['M','F','B0'],default='F');a.add_argument('--image',type=Path,default=ROOT/'data/dog.jpg');a.add_argument('--size',type=int,default=160);a.add_argument('--calibration-list',type=Path);args=a.parse_args()
    export(args.model,args.mode,args.image,args.size,[Path(x) for x in args.calibration_list.read_text().splitlines()] if args.calibration_list else None)
