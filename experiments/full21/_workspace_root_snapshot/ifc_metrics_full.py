
import json
m = json.load(open("/mnt/data/guardian/agent-workspace/guardian-repo/outputs/baseline_ifc/metrics.json"))
print("top keys:", list(m.keys()))
runs = m.get("runs", {})
print("run keys:", list(runs.keys()))
final = m.get("final") or m.get("combined") or m.get("overall")
print("final:", json.dumps(final, indent=1)[:1500] if final else None)
for k, v in runs.items():
    print(k, "tp/fp/fn/tn:", v.get("tp"), v.get("fp"), v.get("fn"), v.get("tn"), "f1:", round(v.get("f1", -1), 4))
