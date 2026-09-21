
import os
ok = os.path.exists("/mnt/data/guardian/secrets/mistral.env")
print("mistral.env exists:", ok)
if ok:
    keys=[]
    for line in open("/mnt/data/guardian/secrets/mistral.env"):
        line=line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.append(line.split("=",1)[0])
    print("keys present:", keys)
