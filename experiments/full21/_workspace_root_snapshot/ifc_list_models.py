
import os
base = "/mnt/data/guardian/models"
print(sorted(os.listdir(base)))
for d in os.listdir(base):
    if "granite" in d.lower():
        p = os.path.join(base, d)
        print(d, "->", os.path.exists(os.path.join(p, "config.json")), os.listdir(p)[:8])
