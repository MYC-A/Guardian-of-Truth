
import subprocess
def run(cmd, cwd=None, timeout=180):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:6000]
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"

for br in ["origin/E2E-agent-1", "origin/E2E-agent-2", "origin/full-architecture-v1",
           "origin/research/superz-20260920", "origin/semantic-pipeline-v1"]:
    print(f"===== {br} =====")
    print("FactNode:", run(f"git -C {W} grep -l 'FactNode' {br} -- '*.py' | head -5", timeout=60))
    print("ArgumentTrace:", run(f"git -C {W} grep -l 'ArgumentTrace' {br} -- '*.py' | head -5", timeout=60))
    print("AnalysisContext:", run(f"git -C {W} grep -l 'AnalysisContext' {br} -- '*.py' | head -5", timeout=60))
    print()
