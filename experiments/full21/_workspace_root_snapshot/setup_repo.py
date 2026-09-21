
import subprocess, os, json

def sh(cmd, timeout=300):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return {"code": r.returncode, "out": r.stdout.strip()[:3000], "err": r.stderr.strip()[:1500]}

# check anonymous github access + clone
res = {}
res["anon_probe"] = sh("git ls-remote https://github.com/MYC-A/Guardian-of-Truth HEAD", timeout=60)
if res["anon_probe"]["code"] == 0:
    target = os.path.expanduser("~/agent-workspace/guardian-repo")
    if not os.path.isdir(target + "/.git"):
        res["clone"] = sh(f"git clone --no-checkout https://github.com/MYC-A/Guardian-of-Truth {target}", timeout=600)
    else:
        res["clone"] = {"code": 0, "out": "already cloned"}
    if os.path.isdir(target + "/.git"):
        res["fetch_branch"] = sh(f"cd {target} && git fetch origin research/independent-fullcycle-20260920 2>&1 | tail -2", timeout=120)
        res["checkout"] = sh(f"cd {target} && git checkout -b research/independent-fullcycle-20260920 origin/research/independent-fullcycle-20260920 2>&1 | tail -2 && git log --oneline -1")
        res["status"] = sh(f"cd {target} && git status -s | head -3 && git config user.name; git config user.email")
else:
    res["note"] = "ANONYMOUS FAIL: token needed for clone"
print(json.dumps(res, indent=1))
