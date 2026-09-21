
import os, json
paths = [
 "/mnt/data/guardian/Guardian-research-d4baa86/outputs/research_mistral_base_20260920/full46_direct/run_manifest.json",
]
for p in paths:
    print(p, "exists:", os.path.exists(p), "readable:", os.access(p, os.R_OK))
    if os.access(p, os.R_OK):
        try:
            d = json.load(open(p))
            # print without secrets: only command/config keys
            def scrub(o):
                if isinstance(o, dict):
                    return {k: ("<REDACTED>" if any(s in k.lower() for s in ("key","token","secret")) else scrub(v)) for k,v in o.items()}
                if isinstance(o, list): return [scrub(x) for x in o]
                return o
            print(json.dumps(scrub(d), indent=1)[:2500])
        except Exception as e:
            print("json fail:", str(e)[:200])
