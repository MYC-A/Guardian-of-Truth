
import os, subprocess
print("whoami:", subprocess.run(["whoami"],capture_output=True,text=True).stdout.strip())
p = "/mnt/data/guardian/secrets"
print("secrets dir stat:", os.stat(p) if os.path.exists(p) else "NOT VISIBLE (exists=False)")
try:
    print("ls secrets:", subprocess.run(["ls","-la",p],capture_output=True,text=True).stdout)
except Exception as e:
    print("ls fail:", e)
f = os.path.join(p, "mistral.env")
print("file exists:", os.path.exists(f))
if os.path.exists(f):
    st = os.stat(f)
    print("file mode:", oct(st.st_mode), "size:", st.st_size)
    keys = []
    for line in open(f, errors="ignore"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.append(line.split("=",1)[0])
    print("KEY NAMES ONLY:", keys)
