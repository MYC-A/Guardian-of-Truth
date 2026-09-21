
import subprocess, json, os
def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
E4 = f"{W}/outputs/superz_fullcycle/e4_a34_verify"

# 1. a4 verifications анализ
vp = f"{E4}/a4_pollinations/verifications.jsonl"
print("### A4 verifications.jsonl analysis:")
try:
    with open(vp) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    print(f"records: {len(lines)}")
    verdicts = {}
    for l in lines:
        v = l.get("verdict", "?")
        verdicts[v] = verdicts.get(v, 0) + 1
    print("verdicts:", json.dumps(verdicts))
    print("keys:", list(lines[0].keys()) if lines else "none")
    print("sample[0]:", json.dumps(lines[0], ensure_ascii=False)[:600])
    # по кейсам
    cases = {}
    for l in lines:
        cid = l.get("case_id", "?")
        cases.setdefault(cid, []).append(l.get("verdict"))
    conf_cases = [cid for cid, vs in cases.items() if any(v == "CONFIRMED" for v in vs)]
    print(f"cases covered: {len(cases)}, cases with >=1 CONFIRMED: {len(conf_cases)}")
except Exception as e:
    print("ERR reading:", e)

print()
print("### a3 verifications.jsonl verdicts:")
try:
    with open(f"{E4}/a3_pollinations/verifications.jsonl") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    verdicts = {}
    for l in lines:
        v = l.get("verdict", "?")
        verdicts[v] = verdicts.get(v, 0) + 1
    print(f"records: {len(lines)}, verdicts:", json.dumps(verdicts))
except Exception as e:
    print("ERR:", e)

print()
print("### e6_agenthallu blockrun state:")
print(run(f"find {W}/outputs/superz_fullcycle/e6_agenthallu -type f -name '*.jsonl' -o -type f -name '*.json' -o -type f -name '*.log' | head; wc -l {W}/outputs/superz_fullcycle/e6_agenthallu/blockrun/*.jsonl 2>/dev/null"))

print()
print("### SEARCH Astra (targeted, fast):")
for d in ["/mnt/data/guardian/agent-workspace/guardian-repo/docs",
          "/mnt/data/guardian/agent-workspace/guardian-repo/manual",
          "/mnt/data/guardian/agent-workspace/tmp_superz",
          "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle",
          "/mnt/data/guardian/results"]:
    out = run(f"grep -ril astra {d} 2>/dev/null | head -5", timeout=30)
    if out:
        print(f"[{d}]:")
        print(out)

print()
print("### guardian-repo top-level:")
print(run("ls /mnt/data/guardian/agent-workspace/guardian-repo/ 2>/dev/null | head -30"))
print()
print("### /mnt/data/guardian/ top:")
print(run("ls /mnt/data/guardian/ 2>/dev/null"))
print()
print("### tmp_superz:")
print(run("ls /mnt/data/guardian/agent-workspace/tmp_superz/ 2>/dev/null | head"))
print()
print("### e4_verify.py tail:")
print(run(f"sed -n '60,200p' {W}/experiments/superz_fullcycle/e4_verify.py"))
