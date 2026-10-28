from pathlib import Path
import json,struct,argparse
import numpy as np
p=argparse.ArgumentParser();p.add_argument('folder',type=Path);args=p.parse_args();folder=args.folder
ref=json.loads((folder/'reference.json').read_text());raw=(folder/'boxes.bin').read_bytes();n=struct.unpack_from('<I',raw)[0]
assert n==len(ref['boxes']),(n,len(ref['boxes']))
actual=[]
for i,b in enumerate(ref['boxes']):
    vals=struct.unpack_from('<5fI',raw,4+i*24);assert np.isfinite(vals[:5]).all(),vals
    assert vals[5]==b[5],(i,vals,b);np.testing.assert_allclose(vals[:5],b[:5],rtol=3e-4,atol=3e-4);actual.append(list(vals))
(folder/'cpu_boxes.json').write_text(json.dumps({'boxes':actual,'matches_independent_numpy':True,'tolerance':.0003},indent=2)+'\n')
print('CPU decode/NMS matches NumPy:',n,'boxes')
