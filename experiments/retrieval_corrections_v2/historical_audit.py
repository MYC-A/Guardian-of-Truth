"""Recompute compact historical costs/rejections, preserving original artifacts."""
from collections import defaultdict
import json
from pathlib import Path
from experiments.hybrid_mechanisms.transport import save
from .offline import ROOT, OUT


def main():
    u2=[json.loads(l) for l in (ROOT/'outputs/evidence_packer_v2/llm/decisions.jsonl').read_text(encoding='utf-8').splitlines()]
    grouped=defaultdict(list)
    for r in u2:grouped[(r['arm'],r['run'])].append(r)
    costs=[]
    for (arm,run),rs in sorted(grouped.items()):
        costs.append(dict(arm=arm,run=run,n=len(rs),
            paid_prompt_tokens=sum(r.get('prompt_tokens',0) for r in rs),
            rejected_prompt_tokens=sum(r.get('prompt_tokens',0) for r in rs if r.get('admission')!='ADMITTED'),
            transport_attempts=sum(r.get('transport_attempts',1) for r in rs),
            repeated_transports=sum(r.get('transport_attempts',1)>1 for r in rs),
            reason_counts={match:sum(r.get('judge')==match for r in rs if r.get('decision')=='ERROR')
                          for match in ('SAME','PARTIAL','DIFFERENT')},
            limitation='Compact artifact lacks retry statuses, full raw replies and judge source context; paid completion/judge/retry-failed usage cannot be reconstructed.'))
    mp=[]
    for run in (1,2,3):
        path=ROOT/f'outputs/multipacket_v1/runs/syn_m1/run{run}/C1.jsonl'
        rs=[json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()]
        stages=[s for r in rs for s in r.get('steps',[])]
        mp.append(dict(run=run,n=len(rs),terminal_nulls=sum(r.get('decision') is None for r in rs),
            recorded_steps=len(stages),stage_rejections=sum(s.get('admission')!='ADMITTED' for s in stages),
            norm_reference_invalid=sum('NORM_REFERENCE_INVALID' in str(s.get('admission')) for s in stages),
            known_prompt_tokens=sum((s.get('usage') or {}).get('prompt_tokens',0) for s in stages),
            limitation='Compact steps omit calls discarded before result construction; hidden CTRL FULL second-pass calls need code audit, not fabrication of HTTP totals.'))
    save(OUT/'historical_audit.json',dict(u2_costs=costs,c1_rejections=mp,
        interpretation='Corrected diagnostic sidecar. No original gold, reports, requests or historical outcomes modified. SAME/PARTIAL judge matches are not source-supported causes.'))
    print(json.dumps(dict(u2_rows=len(u2),repeated_transports=sum(r.get('transport_attempts',1)>1 for r in u2),
        transport_attempts=sum(r.get('transport_attempts',1) for r in u2),c1_rejections=mp),indent=2))


if __name__=='__main__':main()
