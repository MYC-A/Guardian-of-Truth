"""Prepare a pinned external, human-annotated factual-grounding transfer set."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from guardian_truth.external_data import RAGTRUTH_REVISION, adapt_ragtruth


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--download',action='store_true',help='Explicitly fetch ~37 MB from the official public repository')
    parser.add_argument('--max-groups-per-split',type=int,default=100)
    args=parser.parse_args()
    filenames={'source_info.jsonl':'dataset/source_info.jsonl','response.jsonl':'dataset/response.jsonl','LICENSE':'LICENSE'}
    paths=[args.raw_dir/name for name in filenames]
    if len({p.resolve() for p in paths+[args.output,args.manifest]}) != 5:
        parser.error('Raw, output and manifest paths must differ')
    if args.output.exists() or args.manifest.exists(): parser.error('Refusing to overwrite a prepared reserve')
    if args.download:
        args.raw_dir.mkdir(parents=True,exist_ok=True)
        for name,remote in filenames.items():
            destination=args.raw_dir/name
            if destination.exists(): parser.error('Raw destination already exists; use a fresh directory or omit --download')
            url=f'https://raw.githubusercontent.com/ParticleMedia/RAGTruth/{RAGTRUTH_REVISION}/{remote}'
            with urlopen(url,timeout=30) as response:
                body=response.read(64*1024*1024+1)
            if len(body)>64*1024*1024: parser.error('Source exceeds download limit')
            destination.write_bytes(body)
            print(json.dumps({'downloaded':name,'bytes':len(body)}),flush=True)
    sources=[json.loads(line) for line in paths[0].read_text(encoding='utf-8').splitlines() if line.strip()]
    responses=[json.loads(line) for line in paths[1].read_text(encoding='utf-8').splitlines() if line.strip()]
    examples,manifest=adapt_ragtruth(sources,responses,max_groups_per_split=args.max_groups_per_split)
    manifest['input_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manifest['repository']='https://github.com/ParticleMedia/RAGTruth'
    manifest['license_file']=str(paths[2])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('w',encoding='utf-8') as stream:
        for example in examples: stream.write(json.dumps(asdict(example),ensure_ascii=False)+'\n')
    manifest['prepared_sha256']=hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.manifest.parent.mkdir(parents=True,exist_ok=True)
    args.manifest.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest),flush=True)


if __name__=='__main__': main()
