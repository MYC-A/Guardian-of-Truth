"""Finite authorized sequence; no polling, retries or large benchmark."""
import json
from pathlib import Path
import subprocess
import sys

here=Path(__file__).resolve().parent
commands=[['strict_move_micro.py','--run'],
          ['typed_scope_probe.py','--run','--authorized-total-tokens','1200000','--authorized-total-attempts','350'],
          ['api_remaining_screen.py','--run','--authorized-total-tokens','1200000','--authorized-total-attempts','350']]
breaker=Path('/workspace/guardian/results/source-search-api-phase-20261002/breaker.json')
for args in commands:
    if breaker.exists():
        print(json.dumps({'state':'PROVIDER_STOP','next_job':args[0]})); break
    print(json.dumps({'state':'STARTING','job':args[0]}),flush=True)
    subprocess.run([sys.executable,str(here/args[0]),*args[1:]],check=True)
print(json.dumps({'state':'FINITE_SEQUENCE_ENDED','breaker_open':breaker.exists()}),flush=True)
