"""Fixed rank blend. Missing auxiliary scores never become a model NO."""
import json
import math
from pathlib import Path

BASE_ID='Qwen/Qwen3-4B-Instruct-2507'
BASE_REVISION='cdbee75f17c01a7cc42f958dc650907174af0554'
ADAPTER_SHA256='4b06ca6a09894b965a32bd7d3646bc559c88b1591a49ffe5d8213a05e0b14477'
PRIMARY_ID='cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit'
PRIMARY_REVISION='00fcea2d3bcf5389b518d4fc082e5590e0ba4844'


def validate(cfg):
    e=cfg.get('ensemble')
    if not isinstance(e,dict) or e.get('mode')!='rank_50_50':raise ValueError('INVALID_ENSEMBLE_MODE')
    if e.get('base_id')!=BASE_ID or e.get('base_revision')!=BASE_REVISION or e.get('adapter_sha256')!=ADAPTER_SHA256:
        raise ValueError('ENSEMBLE_MODEL_PIN_MISMATCH')
    if cfg.get('require_exact_scores') is not True or cfg.get('review_ranking')!='max_exact':
        raise ValueError('ENSEMBLE_REQUIRES_EXACT_PRIMARY_MAX')
    for key in ('model_dir','adapter_dir'):
        if not isinstance(e.get(key),str) or not e[key]:raise ValueError('ENSEMBLE_PATH_REQUIRED')
    seconds=float(e['seconds'])
    if not math.isfinite(seconds) or not 30<=seconds<float(cfg['judge_stop_seconds'])-60:
        raise ValueError('INVALID_SECONDARY_BUDGET')
    return e


def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def percentiles(scores,n):
    """Ascending midranks / N, matching scipy.stats.rankdata(method='average')."""
    order=sorted(range(n),key=lambda i:scores[i]);out={};lo=0
    while lo<n:
        hi=lo+1
        while hi<n and scores[order[hi]]==scores[order[lo]]:hi+=1
        rank=(lo+1+hi)/(2*n)
        for j in order[lo:hi]:out[j]=rank
        lo=hi
    return out


def blend(primary,secondary,n):
    expected=set(range(n))
    p={i:v for i,v in primary.items() if i in expected and finite(v)}
    s={i:v for i,v in secondary.items() if i in expected and finite(v)}
    if n and set(p)==set(s)==expected:
        pp,ss=percentiles(p,n),percentiles(s,n)
        return {i:(pp[i]+ss[i])/2 for i in range(n)},'rank_50_50'
    return p,'global_primary_fallback'


def read_secondary(path,n):
    """Duplicate/invalid auxiliary receipts quarantine that position."""
    path=Path(path);out={};seen=set();invalid=set()
    if not path.is_file():return out
    with path.open(encoding='utf-8',newline='') as stream:
        for line in stream.read().split('\n'):
            if not line.strip():continue
            try:r=json.loads(line)
            except ValueError:break
            if 'event' in r:continue
            key=r.get('key')
            if not isinstance(key,int) or isinstance(key,bool) or not 0<=key<n:continue
            if key in seen:invalid.add(key)
            seen.add(key)
            if r.get('exact') is not True or not finite(r.get('score')):invalid.add(key)
            else:out[key]=float(r['score'])
    return {k:v for k,v in out.items() if k not in invalid}
