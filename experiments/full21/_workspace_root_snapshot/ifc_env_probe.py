
import os, subprocess
print("JOB ENV: mistral-ish keys:", sorted([k for k in os.environ if "MISTRAL" in k.upper()]))
print("JOB ENV: all key names:", sorted(os.environ.keys()))
r = subprocess.run(["bash","-c","grep -l MISTRAL ~/.bashrc ~/.profile ~/.bash_profile 2>/dev/null; echo rc=$?"], capture_output=True, text=True)
print("shell profiles:", r.stdout)
r = subprocess.run(["bash","-lc","env | grep -i mistral | cut -d= -f1; echo rc=$?"], capture_output=True, text=True)
print("login-shell mistral keys:", r.stdout)
