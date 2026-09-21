
import subprocess, os, glob
def run(cmd, timeout=90):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:2500]
    except Exception as e:
        return f"ERR: {e}"

print("### ASTRA SEARCH /mnt/data/guardian:")
print(run("grep -ril astra /mnt/data/guardian --include='*.md' --include='*.txt' --include='*.json' 2>/dev/null | grep -v hf_cache | grep -v '.git/' | head -20"))
print()
W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print("### e4_a34_verify contents:")
print(run(f"find {W}/outputs/superz_fullcycle/e4_a34_verify -type f | head -30"))
print()
print("### a4_pollinations files:")
print(run(f"ls -la {W}/outputs/superz_fullcycle/e4_a34_verify/a4_pollinations/ 2>/dev/null"))
print()
print("### e6_agenthallu files:")
print(run(f"ls -la {W}/outputs/superz_fullcycle/e6_agenthallu/ 2>/dev/null"))
print()
print("### experiments/superz_fullcycle scripts:")
print(run(f"ls {W}/experiments/superz_fullcycle/"))
print()
print("### e4 script head:")
print(run(f"head -60 {W}/experiments/superz_fullcycle/e4_verify.py"))
