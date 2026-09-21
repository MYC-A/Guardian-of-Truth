
import subprocess
def run(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:5000]
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
BR = "origin/research/independent-fullcycle-20260920"
print("### ifc branch full log:")
print(run(f"git -C {W} log --oneline {BR} | head -40"))
print()
print("### ifc branch tree (docs + experiments):")
print(run(f"git -C {W} ls-tree --name-only {BR}:docs/research/ 2>/dev/null"))
print(run(f"git -C {W} ls-tree --name-only {BR}:experiments/ 2>/dev/null"))
print(run(f"git -C {W} ls-tree --name-only {BR} 2>/dev/null"))
print()
print("### search A4/E4 in ifc research docs:")
print(run(f"git -C {W} grep -l 'A4' {BR} -- 'docs/' 2>/dev/null | head"))
print(run(f"git -C {W} grep -l 'E4' {BR} -- 'docs/' 2>/dev/null | head"))
print()
print("### ifc WORKLOG-like files:")
print(run(f"git -C {W} ls-tree -r --name-only {BR} | grep -iE 'worklog|log|report|handoff' | head -20"))
