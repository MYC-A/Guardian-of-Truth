
import subprocess
def run(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:6000]
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print("### e4_verify.py lines 320-end:")
print(run(f"sed -n '320,420p' {W}/experiments/superz_fullcycle/e4_verify.py"))
print()
print("### run_mode loop (140-200):")
print(run(f"sed -n '140,200p' {W}/experiments/superz_fullcycle/e4_verify.py"))
