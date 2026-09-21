
import subprocess, json, os
os.chdir("/mnt/data/guardian/agent-workspace/guardian-repo")
print("HEAD:", subprocess.run(["git","log","--oneline","-1"],capture_output=True,text=True).stdout.strip())
lines = [json.loads(l) for l in open("outputs/ifc/dual_theory_v1_p/records.jsonl")]
print("lines:", len(lines), "| ok:", sum(1 for r in lines if not r.get("error")), "| err:", sum(1 for r in lines if r.get("error")))
print("manifest:", json.load(open("outputs/ifc/dual_theory_v1_p/manifest.json")).get("finished_utc"))
