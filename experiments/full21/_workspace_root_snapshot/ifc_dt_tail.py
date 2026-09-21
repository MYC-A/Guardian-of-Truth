
import os, json, time
p = "/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc/dual_theory_v1_p"
for f in os.listdir(p):
    st = os.stat(os.path.join(p, f))
    print(f, "size:", st.st_size, "mtime:", time.strftime("%H:%M:%S", time.localtime(st.st_mtime)))
lines = open(os.path.join(p, "records.jsonl")).readlines()
print("lines:", len(lines))
for l in lines[-3:]:
    r = json.loads(l)
    print(r.get("case_id"), "| err:", str(r.get("error"))[:80], "| ok:", not r.get("error"))
