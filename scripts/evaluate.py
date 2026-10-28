"""Independent 100-image calibration / 500-image official COCOeval on host."""
import argparse,json,hashlib,time,contextlib
from pathlib import Path
import numpy as np
from model import ROOT,config,weights,preprocess,forward,maxpool,ratio,roundaway,decode,draw
from reference import conv,requant

def quant_graph(nodes,image,maxima):
    x=requant(roundaway(image*127).astype(np.int32),1,0);scale=1/127;out=[];scales=[]
    for i,n in enumerate(nodes):
        t=n['type']
        if t=='convolutional':
            if 'qweight' not in n:
                sw=np.maximum(np.max(np.abs(n['weight']),axis=(1,2,3))/127,1e-12);n['qweight']=np.clip(roundaway(n['weight']/sw[:,None,None,None]),-127,127).astype(np.int8)
                sy=max(maxima[i]/120,1e-8);co=n['weight'].shape[0];q=np.zeros((co,5),dtype=np.int64);q[:,0]=roundaway(n['bias']/(scale*sw)).astype(np.int64)
                for c in range(co):q[c,1],q[c,2]=ratio(scale*float(sw[c])/sy);q[c,3],q[c,4]=ratio(scale*float(sw[c])/sy*(.1 if n['activation']=='leaky' else 1))
                n['qparam']=q;n['qscale']=sy
            k=int(n['size']);p=k//2 if int(n.get('pad','0')) else 0;x=conv(x,n['qweight'],n['qparam'],int(n['stride']),(p,)*4);scale=n['qscale']
        elif t=='maxpool':x=maxpool(x,int(n['size']),int(n['stride']))
        elif t=='upsample':x=np.repeat(np.repeat(x,2,0),2,1)
        elif t=='route':
            ids=n['ids'];scale=max(scales[j] for j in ids);aa=[]
            for j in ids:
                m,s=ratio(scales[j]/scale);aa.append(requant(out[j],m,s))
            x=np.concatenate(aa,2) if len(aa)>1 else aa[0]
            if 'groups' in n:
                ch=x.shape[2]//int(n['groups']);start=int(n['group_id'])*ch;x=x[:,:,start:start+ch]
        elif t!='yolo':raise ValueError(t)
        out.append(x);scales.append(scale)
    return out,scales

def run(model,size=160,limit=500):
    base=ROOT/'data/coco';folder=ROOT/'results'/f'{model}_coco';folder.mkdir(parents=True,exist_ok=True)
    nodes=config(ROOT/f'data/{model}.cfg');whash=weights(ROOT/f'data/{model}.weights',nodes)
    calpaths=[Path(x) for x in (base/'train2017.txt').read_text().splitlines()];evalpaths=[Path(x) for x in (base/'val2017.txt').read_text().splitlines()][:limit]
    assert len(calpaths)==100 and len(evalpaths)==limit
    assert not {x.stem for x in calpaths}&{x.stem for x in evalpaths}
    cache=folder/'calibration.json';chash=hashlib.sha256('\n'.join(map(str,calpaths)).encode()).hexdigest()
    if cache.exists():
        info=json.loads(cache.read_text());assert info['weights_sha256']==whash and info['size']==size and info['list_sha256']==chash;maxima=info['maxima']
    else:
        maxima=[0.]*len(nodes)
        for i,path in enumerate(calpaths):
            outs=forward(nodes,preprocess(path,size)[0]);maxima=[max(m,float(np.max(np.abs(a)))) for m,a in zip(maxima,outs)]
            if i%10==9:print(model,'calibration',i+1,flush=True)
        cache.write_text(json.dumps({'size':size,'weights_sha256':whash,'list_sha256':chash,'images':list(map(str,calpaths)),'maxima':maxima},indent=2)+'\n')
    ann=json.loads((base/'instances_val2017_subset.json').read_text());catids=sorted(c['id'] for c in ann['categories']);pred={'float':[],'int8':[]};start=time.monotonic()
    for i,path in enumerate(evalpaths):
        x,meta=preprocess(path,size);fp=forward(nodes,x);qp,scales=quant_graph(nodes,x,maxima)
        for key,outputs in [('float',fp),('int8',[a.astype(np.float32)*s for a,s in zip(qp,scales)])]:
            # Low score threshold for AP; demo/CPU visualization uses .25 separately.
            boxes=decode([(outputs[j],n,size) for j,n in enumerate(nodes) if n['type']=='yolo'],threshold=.001)
            nw,nh=meta['resized'];ow,oh=meta['original'];ox,oy=meta['offset']
            for a,b,c,d,score,cls in boxes:
                xx0=max(0.,min(float(ow),(a*size-ox)*ow/nw));yy0=max(0.,min(float(oh),(b*size-oy)*oh/nh));xx1=max(0.,min(float(ow),(c*size-ox)*ow/nw));yy1=max(0.,min(float(oh),(d*size-oy)*oh/nh))
                if xx1>xx0 and yy1>yy0:pred[key].append({'image_id':int(path.stem),'category_id':catids[cls],'bbox':[xx0,yy0,xx1-xx0,yy1-yy0],'score':score})
            if i<10:draw(path,[b for b in boxes if b[4]>=.25],meta,folder/f'{key}_{path.stem}.png')
        if i%10==9:print(model,'evaluation',i+1,'/',limit,'elapsed_s',round(time.monotonic()-start),flush=True)
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
    results={}
    for key,rows in pred.items():
        path=folder/f'{key}_predictions.json';path.write_text(json.dumps(rows));gt=COCO(str(base/'instances_val2017_subset.json'));dt=gt.loadRes(str(path));ev=COCOeval(gt,dt,'bbox');ev.params.imgIds=[int(p.stem) for p in evalpaths];ev.evaluate();ev.accumulate();ev.summarize();results[key]={'AP':float(ev.stats[0]),'AP50':float(ev.stats[1]),'AP75':float(ev.stats[2])}
    results.update({'images':limit,'calibration_images':100,'size':size,'weights_sha256':whash,'calibration_list_sha256':chash,'evaluation_ids':[int(p.stem) for p in evalpaths],'score_threshold':.001,'decoder':'best-class-per-anchor + class-aware greedy NMS, max100','backend':'host NumPy integer reference + official pycocotools COCOeval; not RTL500','elapsed_seconds':time.monotonic()-start})
    results['AP_drop_points']=(results['float']['AP']-results['int8']['AP'])*100;results['target_within_3_points']=results['AP_drop_points']<=3
    (folder/'metrics.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',choices=['yolov3-tiny','yolov4-tiny'],required=True);p.add_argument('--limit',type=int,default=500);args=p.parse_args();run(args.model,limit=args.limit)
