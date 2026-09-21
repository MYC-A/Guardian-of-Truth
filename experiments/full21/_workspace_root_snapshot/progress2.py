
import json
from collections import Counter
W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
with open(f"{W}/outputs/superz_fullcycle/e3b_a1r_live/blockrun/records.jsonl") as f:
    lines = [json.loads(l) for l in f if l.strip()]
ok = [l for l in lines if l.get("status") == "OK"]
print(f"E3b: {len(ok)}/46 OK")
try:
    with open(f"{W}/outputs/superz_fullcycle/p_precond/extract_llm7/cards.jsonl") as f:
        clines = [json.loads(l) for l in f if l.strip()]
    cok = [l for l in clines if l.get("status") == "OK"]
    print(f"Pextract: {len(cok)}/46 OK, cards: {sum(l.get('n_cards',0) for l in cok)}, grounded: {sum(l.get('n_grounded',0) for l in cok)}")
except Exception as e:
    print("Pextract:", e)
