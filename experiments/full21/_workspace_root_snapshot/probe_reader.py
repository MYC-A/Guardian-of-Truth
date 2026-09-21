
import subprocess
def run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:5000]
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print("### src/guardian_truth/:")
print(run(f"ls {W}/src/guardian_truth/"))
print()
print("### reader.py head (parse entry):")
print(run(f"sed -n '1,60p' {W}/src/guardian_truth/reader.py"))
print()
print("### pipeline.py: где вызывается build_graph:")
print(run(f"grep -n 'build_graph\|EvidenceGraph\|provenance' {W}/src/guardian_truth/pipeline.py | head"))
print()
print("### CLI entry (competition):")
print(run(f"grep -rn 'build_graph' {W}/src/ | head"))
