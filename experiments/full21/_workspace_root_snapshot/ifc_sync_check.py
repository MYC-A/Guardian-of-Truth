
import subprocess, os
os.chdir("/mnt/data/guardian/agent-workspace/guardian-repo")
def run(*a):
    return subprocess.run(a, capture_output=True, text=True)
print("BEFORE:", run("git","log","--oneline","-1").stdout.strip())
print(run("git","fetch","origin").stderr[:500])
print("branch:", run("git","rev-parse","--abbrev-ref","HEAD").stdout.strip())
r = run("git","reset","--hard","origin/research/independent-fullcycle-20260920")
print("reset:", r.stdout.strip(), r.stderr.strip()[:200])
print("AFTER:", run("git","log","--oneline","-1").stdout.strip())
print("clean:", run("git","status","--porcelain").stdout[:200])
r = run("/mnt/data/guardian/venv/bin/python","-c","import guardian_truth;print('guardian_truth OK', guardian_truth.__file__)")
print("import:", r.stdout.strip(), r.stderr.strip()[:300])
r = run("/mnt/data/guardian/venv/bin/python","-c","import clingo,pandas,pyarrow;print('clingo/pandas OK')")
print("deps:", r.stdout.strip(), r.stderr.strip()[:300])
