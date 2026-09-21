
import subprocess
def run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:4000]
    except Exception as e:
        return f"ERR: {e}"

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print("### build_graph callers:")
print(run(f"grep -rn 'build_graph' {W}/src/guardian_truth/*.py | grep -v pycache"))
print()
print("### cli.py main flow (graph usage):")
print(run(f"grep -n 'graph\|Graph' {W}/src/guardian_truth/cli.py | head -20"))
print()
print("### runtime.py graph:")
print(run(f"grep -n 'build_graph\|EvidenceGraph' {W}/src/guardian_truth/runtime.py | head"))
print()
print("### how history events are parsed (parsing.py?):")
print(run(f"grep -n 'def ' {W}/src/guardian_truth/parsing.py | head -20"))
print()
print("### semantic.py: AnalysisContext build:")
print(run(f"grep -n 'AnalysisContext\|build_graph' {W}/src/guardian_truth/semantic.py | head"))
