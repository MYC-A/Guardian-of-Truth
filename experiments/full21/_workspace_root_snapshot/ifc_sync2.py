
import subprocess
def run(*a): return subprocess.run(a, capture_output=True, text=True, cwd="/mnt/data/guardian/agent-workspace/guardian-repo")
print("pull:", run("git","pull","--ff-only","origin","research/independent-fullcycle-20260920").stdout.strip()[:200])
print("HEAD:", run("git","log","--oneline","-1").stdout.strip())
