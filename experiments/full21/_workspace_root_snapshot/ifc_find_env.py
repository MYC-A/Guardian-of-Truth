
import subprocess
r = subprocess.run(["bash","-lc","find /mnt/data/guardian -maxdepth 3 -name '*.env' -o -maxdepth 3 -name '*mistral*' -o -maxdepth 3 -name '*secret*' 2>/dev/null | head -30"], capture_output=True, text=True)
print(r.stdout)
print(r.stderr[:300])
