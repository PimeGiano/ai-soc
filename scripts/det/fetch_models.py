"""Download missing public assets, verify content hashes even for existing files."""
from pathlib import Path
import json,hashlib,urllib.request
ROOT=Path(__file__).resolve().parents[2];base=ROOT/'data/det'
for name,info in json.loads((base/'sources.json').read_text()).items():
    p=base/name
    if not p.exists():
        with urllib.request.urlopen(info['url'],timeout=180) as r:p.with_suffix(p.suffix+'.part').write_bytes(r.read())
        p.with_suffix(p.suffix+'.part').replace(p)
    if hashlib.sha256(p.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('asset hash mismatch: '+name)
    print(name,'SHA256 verified')
