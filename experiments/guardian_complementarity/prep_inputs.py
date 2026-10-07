"""Write label-free id,prompt,response CSVs for valid46 + held-out sets (same rows run_local uses)."""
import csv, sys, hashlib, json
from pathlib import Path
from experiments.guardian_local_a100.run_local import rows
SETS = ['valid46', 'lb_long', 'lb2_long', 'lb3_long', 'ext_tau2', 'hold_tau2h', 'hold_holdout2']
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
man = {}
for s in SETS:
    rs = rows(s); p = out / f'{s}.csv'
    with open(p, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['id', 'prompt', 'response']); w.writeheader()
        for r in rs: w.writerow({k: r[k] for k in ('id', 'prompt', 'response')})
    man[s] = dict(rows=len(rs), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
(out / 'MANIFEST.json').write_text(json.dumps(man, indent=1))
print(json.dumps(man))
