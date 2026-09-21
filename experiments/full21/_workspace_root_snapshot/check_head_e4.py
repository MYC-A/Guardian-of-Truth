
import subprocess
def run(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:4000]
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print("### my HEAD vs origin/independent-fullcycle:")
print(run(f"git -C {W} rev-parse HEAD"))
print(run(f"git -C {W} rev-parse origin/research/independent-fullcycle-20260920"))
print(run(f"git -C {W} log --oneline origin/research/independent-fullcycle-20260920 | head -5"))
print()
print("### e4_verify.py run_mode + main:")
print(run(f"sed -n '200,320p' {W}/experiments/superz_fullcycle/e4_verify.py"))
