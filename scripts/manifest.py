#!/usr/bin/env python3
"""Hash maintained project sources; exclude downloaded/generated artifacts."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
files=[]
for directory in ['rtl','firmware','tb','sim','spec','scripts','third_party','docs']:
    files.extend(p for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
files.extend((root/'data').glob('*.cfg'))
files.extend(root/p for p in ['README.md','CONTRIBUTING.md','requirements-detection.txt','data/sources.json','.gitignore'])
result={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}
(root/'results/source_manifest.json').write_text(json.dumps(result,indent=2)+'\n')
print('Manifest:',len(result),'source/config files')
