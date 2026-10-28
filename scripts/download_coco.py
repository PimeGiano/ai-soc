"""Fetch only the fixed 100 train calibration + 500 validation images."""
from pathlib import Path
import argparse,json,urllib.request,zipfile,time
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1]
def fetch(url,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():return path
    for attempt in range(8):
        try:
            with urllib.request.urlopen(url if attempt==0 else url+"?retry="+str(attempt),timeout=60) as r:path.with_suffix(path.suffix+'.part').write_bytes(r.read())
            path.with_suffix(path.suffix+'.part').replace(path);return path
        except Exception:
            if attempt==7:raise
            time.sleep(1)
def main():
    a=argparse.ArgumentParser();a.add_argument('--annotations-zip',type=Path);args=a.parse_args();base=ROOT/'data/coco'
    if all((base/f'{split}.txt').exists() and (base/f'instances_{split}_subset.json').exists() and all(Path(x).exists() for x in (base/f'{split}.txt').read_text().splitlines()) for split in ['train2017','val2017']):
        print('COCO subsets already complete');return
    z=args.annotations_zip or fetch('https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip',base/'annotations.zip')
    tasks=[];ids={}
    with zipfile.ZipFile(z) as archive:
        for split,count in [('train2017',100),('val2017',500)]:
            data=json.loads(archive.read(f'annotations/instances_{split}.json'));selected=sorted(data['images'],key=lambda d:d['id'])[:count];ids[split]={d['id'] for d in selected}
            subset={'info':data.get('info',{}),'licenses':data.get('licenses',[]),'images':selected,'categories':data['categories'],'annotations':[d for d in data['annotations'] if d['image_id'] in ids[split]]}
            base.mkdir(parents=True,exist_ok=True);(base/f'instances_{split}_subset.json').write_text(json.dumps(subset))
            paths=[]
            for d in selected:
                path=base/split/d['file_name'];tasks.append((f'https://s3.amazonaws.com/images.cocodataset.org/{split}/{d["file_name"]}',path));paths.append(str(path))
            (base/f'{split}.txt').write_text('\n'.join(paths)+'\n')
    assert not ids['train2017']&ids['val2017']
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i,_ in enumerate(pool.map(lambda t:fetch(*t),tasks)):
            if i%50==49:print('Downloaded',i+1,'/',len(tasks),flush=True)
    print('COCO subset ready: calibration100 / evaluation500, disjoint IDs')
if __name__=='__main__':main()
