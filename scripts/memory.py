from pathlib import Path
import struct
class Image:
    def __init__(self):self.next=0x01010000;self.parts=[]
    def put(self,data,alignment=16):
        data=bytes(data);a=(self.next+alignment-1)&-alignment;self.parts.append((a,data));self.next=a+len(data)
        assert self.next<0x04f00000
        return a
    def words(self,words):return self.put(struct.pack('<'+'I'*len(words),*(int(x)&0xffffffff for x in words)))
    def write(self,path):
        with Path(path).open('wb') as f:
            f.write(struct.pack('<I',len(self.parts)))
            for a,data in self.parts:f.write(struct.pack('<II',a,len(data)));f.write(data)
