
import os, subprocess, json

def sh(cmd, timeout=90):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + ("\n[stderr] " + r.stderr if r.stderr.strip() else "")).strip()
    except Exception as e:
        return f"ERR {e}"

out = {}
repo = "/mnt/data/guardian/Guardian-of-Truth-Offline-20260919"
out["main_repo"] = sh(f"cd {repo} && git log --oneline -1 && git branch --show-current")
# worktrees: each Guardian-* dir may have .git file
wt = []
for d in sorted(os.listdir("/mnt/data/guardian")):
    p = f"/mnt/data/guardian/{d}"
    if d.startswith("Guardian") and os.path.isdir(p):
        gitf = os.path.join(p, ".git")
        if os.path.isfile(gitf) or os.path.isdir(gitf):
            branch = sh(f"cd {p} && git branch --show-current 2>/dev/null; git log --oneline -1 2>/dev/null")
            wt.append(f"{d}: {branch}")
out["worktree_map"] = "\n".join(wt)
out["models"] = sh("du -sh /mnt/data/guardian/models/* 2>/dev/null; ls /mnt/data/guardian/models/ 2>/dev/null")
out["hf_cache_sizes"] = sh("du -sh /mnt/data/guardian/hf_cache/* 2>/dev/null | head -12")
out["results"] = sh("ls /mnt/data/guardian/results/ 2>/dev/null; du -sh /mnt/data/guardian/results/* 2>/dev/null | head -15")
out["venv_pkgs"] = sh("/mnt/data/guardian/venv/bin/pip list 2>/dev/null | grep -iE 'torch|clingo|transformers|langextract|gliner|nuextract|mistral|sentence|flag|mini|lettuce|deberta' | head -25")
out["env_file"] = sh("cat /mnt/data/guardian/ENVIRONMENT.txt 2>/dev/null")
print(json.dumps(out, indent=1))
