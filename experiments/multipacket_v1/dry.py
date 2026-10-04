"""Pre-inference dry run: executes every pipeline up to its first uncached call (no network)."""
import os, sys, traceback
os.environ['MP_DRY'] = '1'
from collections import Counter
from experiments.multipacket_v1.arms import ARMS
from experiments.multipacket_v1.common import valid_rows
from experiments.multipacket_v1.llm import DryRun
calls, sizes, errs = Counter(), Counter(), []
for row in valid_rows():
    for name, fn in ARMS.items():
        try:
            fn(row)
        except DryRun as e:
            calls[name] += 1; sizes[name] += e.args[0]
        except Exception:
            errs.append((name, row['id'], traceback.format_exc(limit=3)[-400:]))
for n in ARMS:
    print(f"{n:6s} first-new-call rows {calls[n]:3d}  mean request bytes {sizes[n] // max(1, calls[n])}")
print('errors', len(errs)); [print(e) for e in errs[:3]]
