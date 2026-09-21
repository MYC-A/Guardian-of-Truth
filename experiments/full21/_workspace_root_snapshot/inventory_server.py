
import os, subprocess, json

def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return (r.stdout + ("\n[stderr] " + r.stderr if r.stderr.strip() else "")).strip()
    except Exception as e:
        return f"ERR {e}"

out = {}
out["guardian_root"] = sh("ls -la /mnt/data/guardian/ | head -25")
out["workspaces"] = sh("ls /mnt/data/ | head -20")
repo = "/mnt/data/guardian/repo"
if os.path.isdir(repo):
    out["repo_git"] = sh(f"cd {repo} && git log --oneline -2 && git branch --show-current && git status -s | head -5")
    out["repo_worktrees"] = sh(f"cd {repo} && git worktree list")
else:
    # find repos
    out["find_repos"] = sh("find /mnt/data -maxdepth 3 -name .git -type d 2>/dev/null | head -10")
out["hf_cache"] = sh("ls /root/.cache/huggingface/hub 2>/dev/null | head -15; ls /mnt/data/hf_cache 2>/dev/null | head -15; ls ~/.cache/huggingface/hub 2>/dev/null | head -15")
out["disk"] = sh("df -h /mnt/data | tail -1")
out["agent_workspace"] = sh("ls -la /mnt/data/guardian/agent-workspace/ | head -20")
print(json.dumps(out, indent=1))
