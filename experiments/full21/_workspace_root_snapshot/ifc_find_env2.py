
import subprocess, os, glob
hits = []
for root in ["/mnt/data/guardian", "/home/guardianagent", "/mnt/workspace"]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git","node_modules","__pycache__","hf_cache","hub",".venv","venv")]
        if dirpath.count(os.sep) - root.count(os.sep) > 5:
            dirnames[:] = []
            continue
        for fn in filenames:
            fl = fn.lower()
            if fl.endswith(".env") or "mistral" in fl or fl in ("secrets",".secrets"):
                hits.append(os.path.join(dirpath, fn))
        # limit walk time
print("HITS:")
for h in hits[:40]: print(" ", h)
# check contents presence of MISTRAL_API_KEY marker (no values)
for h in hits[:40]:
    try:
        if os.path.isfile(h) and os.path.getsize(h) < 100000:
            txt = open(h, errors="ignore").read()
            marks = [k for k in ("MISTRAL_API_KEY","MISTRAL_MODEL","API_KEY") if k in txt]
            if marks: print("  MARKS:", h, marks)
    except Exception as e:
        pass
# env of current process (names only)
print("PROC ENV KEYS sample:", [k for k in os.environ.keys() if "MISTRAL" in k.upper() or "API" in k.upper()][:10])
