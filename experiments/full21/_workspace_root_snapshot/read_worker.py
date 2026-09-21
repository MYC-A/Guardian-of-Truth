
import subprocess
p = subprocess.run('cat /mnt/data/guardian/gateway-system/worker.py', shell=True, capture_output=True, text=True)
print(p.stdout[:13000])
