
import subprocess
def run(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:6000]
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print("### __main__ block:")
print(run(f"grep -n '__main__' {W}/experiments/superz_fullcycle/e4_verify.py; tail -30 {W}/experiments/superz_fullcycle/e4_verify.py"))
print()
print("### help:")
print(run(f"cd {W} && /mnt/data/guardian/venv/bin/python experiments/superz_fullcycle/e4_verify.py --help 2>&1 | head -20"))
