"""Verify and export only sources actually referenced by a comparison journal."""
import argparse
import json
from pathlib import Path
import zipfile
from acceptance import ROOT
from guardian_truth.source_search.store import digest


def export(directory,destination):
    directory=Path(directory);destination=Path(destination)
    rows=[json.loads(s) for s in (directory/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    files=set();checked=[]
    for row in rows:
        ref=row['source_archive'];sources=directory/'source_stores'
        for name in (ref['raw_file'],ref['index_file']):
            if Path(name).name!=name:raise ValueError('archive filename must be a basename')
        raw_path=sources/ref['raw_file'];index_path=sources/ref['index_file']
        raw=json.loads(raw_path.read_text(encoding='utf-8'))
        index=json.loads(index_path.read_text(encoding='utf-8'))
        if digest(raw)!=ref['source_sha256'] or digest(index)!=ref['index_sha256']:
            raise ValueError('source digest mismatch')
        if index['raw_ref']!=ref['raw_file']:raise ValueError('index/raw mismatch')
        for sid,span in {**index['sources'],**index['quotes']}.items():
            text=raw[span['document']]
            if not 0<=span['start']<span['end']<=len(text):raise ValueError('span outside original: '+sid)
        files.update((raw_path,index_path))
        checked.append({'case_id':row['case_id'],'arm':row['mode'],'raw_sha256':digest(raw),'index_sha256':digest(index)})
    for name in ('frozen.json','inputs.jsonl','predictions.jsonl','status.json','score.json',
                 'mechanism_audit.json','budget_approval.json','launch.json'):
        if (directory/name).exists():files.add(directory/name)
    report={'scope':'ARTIFACT_INTEGRITY_NOT_MODEL_SEMANTICS','records':len(rows),
            'unique_files':len(files),'validated_source_references':checked}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(files):bundle.write(path,path.relative_to(directory).as_posix())
        bundle.writestr('archive_verification.json',json.dumps(report,ensure_ascii=False,indent=2))
    return {'records':len(rows),'unique_files':len(files),'zip_bytes':destination.stat().st_size}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();print(json.dumps(export(args.directory,args.destination)))


if __name__=='__main__':main()
