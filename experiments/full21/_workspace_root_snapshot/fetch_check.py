
import subprocess
def run(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:3000]
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print("### git fetch:")
print(run(f"git -C {W} fetch origin 2>&1 | head -5", timeout=90))
print("### remote branches (new):")
print(run(f"git -C {W} branch -r"))
print("### new commits on origin branches vs my base:")
for br in ["origin/main", "origin/research/offline-20260919", "origin/research/agentz-c3-holdout-20260920",
           "origin/research/superz-20260920", "origin/full-architecture-v1", "origin/E2E-agent-1",
           "origin/E2E-agent-2", "origin/semantic-pipeline-v1", "origin/competition-real-valid-codex"]:
    print(f"[{br}]:", run(f"git -C {W} log --oneline -3 {br}", timeout=30))
print()
print("### search 'Astra' in all origin branches (commit messages):")
print(run(f"git -C {W} log --all --oneline --grep='astra' -i | head -10"))
print("### search 'Ast' agent names in branches:")
print(run(f"git -C {W} log --all --oneline --grep='Ast' | head -10"))
