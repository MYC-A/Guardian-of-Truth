
import subprocess, os, shutil, json

def sh(cmd, timeout=300):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return {"code": r.returncode, "out": r.stdout.strip()[:2000], "err": r.stderr.strip()[:1000]}

res = {}
old = os.path.expanduser("~/agent-workspace/guardian-repo")
target = "/mnt/data/guardian/agent-workspace/guardian-repo"

# try plain move first (same NAS? no, /home is container disk) -> use shutil move across fs
if os.path.isdir(old) and not os.path.isdir(target + "/.git"):
    try:
        shutil.move(old, target)
        res["move"] = "moved"
    except Exception as e:
        res["move"] = f"MOVE FAIL {e}; re-clone"

if not os.path.isdir(target + "/.git"):
    res["clone"] = sh(f"git clone --no-checkout https://github.com/MYC-A/Guardian-of-Truth {target}", timeout=900)

if os.path.isdir(target + "/.git"):
    res["fetch"] = sh(f"cd {target} && git fetch origin research/independent-fullcycle-20260920 2>&1 | tail -1", timeout=300)
    res["checkout"] = sh(f"cd {target} && git checkout research/independent-fullcycle-20260920 2>&1 | tail -1")
    res["identity"] = sh(f'cd {target} && git config user.name "Super Z Agent" && git config user.email "agent@guardian.local" && git config user.name')
    res["head"] = sh(f"cd {target} && git log --oneline -1 && git status -s | head -3")
    res["checkout_files"] = sh(f"cd {target} && git checkout -- . 2>&1 | tail -1; git status -s | head -3; ls | head -8")
print(json.dumps(res, indent=1))
