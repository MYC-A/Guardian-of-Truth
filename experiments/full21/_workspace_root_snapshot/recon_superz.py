
import subprocess, os

def run(cmd, cwd=None, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
    except Exception as e:
        out = f"ERR: {e}"
    return out[:2200]

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print("### BRANCH:", run(f"git -C {W} branch --show-current"))
print("### STASH:", run(f"git -C {W} stash list"))
print("### REMOTE:", run(f"git -C {W} remote -v"))
print("### UNCOMMITTED (non-cache):", run(f"git -C {W} status --short | grep -v 'outputs/superz_fullcycle/e2_a0_cross' | head -20"))
print()
print("### RUNNING PROCESSES (python):")
print(run("ps aux | grep -E 'python|pytest' | grep -v grep | head -15"))
print()
print("### docs/research/:")
print(run(f"ls -la {W}/docs/research/ 2>/dev/null"))
print()
print("### root docs:")
print(run(f"ls {W}/*.md 2>/dev/null"))
print()
print("### SEARCH 'Astra' in my worktree:")
print(run(f"grep -ril astra {W}/docs {W}/manual 2>/dev/null | head -20"))
print()
print("### SEARCH A4 in docs/research:")
print(run(f"grep -rl 'A4' {W}/docs/research/ 2>/dev/null | head"))
print()
print("### OTHER WORKTREES:")
print(run("ls /mnt/data/guardian/agent-workspace/"))
print()
print("### my results dirs:")
print(run(f"ls {W}/outputs/superz_fullcycle/"))
print()
print("### git branches:")
print(run(f"git -C {W} branch -a | head -30"))
