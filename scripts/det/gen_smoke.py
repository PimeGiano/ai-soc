"""Small real-CPU checks: hardware ordinary/fused jobs plus CPU baseline."""
from pathlib import Path
import struct,json
from memory import Image
ROOT=Path(__file__).resolve().parents[2];out=ROOT/'build/det';parts=[]
with (out/'vectors.mem').open('rb') as f:
    for _ in range(struct.unpack('<I',f.read(4))[0]):
        a,n=struct.unpack('<II',f.read(8));parts.append((a,f.read(n)))
lookup=dict(parts);jobs=(out/'jobs.txt').read_text().splitlines()
for label,index,mode in [('ordinary',0,0),('fused',100,0),('cpu',0,2)]:
    da,dst,n,ref,_=jobs[index].split();da,dst,n=int(da),int(dst),int(n);d=struct.unpack('<32I',lookup[da]);data=Path(ref).read_bytes();h=2166136261
    for v in data:h=((h^v)*16777619)&0xffffffff
    image=Image();image.parts=parts.copy();image.next=max(a+len(b) for a,b in parts)+16
    op=[1,d[0],0,dst,d[16],d[17],d[7],0,1,0,1,0,1,0,da,h,n,0,0,0,0,0,0,0]
    oa=image.words(op);ba=image.put(bytes(2404));head=[0x44455431,1,oa,mode,0,0,ba,1]+[0]*8
    image.parts.append((0x01008000,struct.pack('<16I',*head)));image.write(out/f'smoke_{label}.mem');(out/f'smoke_{label}.checks').write_text(f'{dst} {n} {ref}\n')
