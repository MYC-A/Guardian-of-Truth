
import subprocess
def run(cmd, cwd=None, timeout=120):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    return (r.stdout + r.stderr).strip()[:1200]

W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
print(run(f"cat /mnt/data/guardian/agent-workspace/superz_worklog_add_e4.md >> {W}/docs/research/WORKLOG_SUPERZ_20260920.md"))
print(run(f"rm /mnt/data/guardian/agent-workspace/superz_worklog_add_e4.md"))

# 2. git add + commit
files = [
    "docs/research/WORKLOG_SUPERZ_20260920.md",
    "experiments/superz_fullcycle/a4_analysis.py",
    "experiments/superz_fullcycle/e3b_verify.py",
    "experiments/superz_fullcycle/g_graph.py",
    "experiments/superz_fullcycle/p_precond.py",
    "experiments/superz_fullcycle/a4_pg.py",
    "outputs/superz_fullcycle/e4_a34_verify/a4_pollinations/verifications.jsonl",
    "outputs/superz_fullcycle/e4_a34_verify/a4_pollinations/summary.json",
    "outputs/superz_fullcycle/e4_a34_verify/a4_pollinations/case_labels.json",
    "outputs/superz_fullcycle/e4_a34_verify/a4_analysis.json",
]
print(run(f"cd {W} && git add " + " ".join(files)))
print(run(f'cd {W} && git commit -m "superz E4/A4 COMPLETED: full-context cross-model verification — 33C/52R/9tech, F1 .6222 (P .6364 R .6087); delta vs E3a: -11 FP, -6 TP, 0 new FP; per-suspicion analysis (60 correct, 10 wrongly-confirmed, 15 refuted-in-error-case); 10 mixed-verdict cases prove per-suspicion discrimination; control architectures fixed; G/P experiment scripts staged (g_graph, p_precond, a4_pg, e3b_verify)"'))
print(run(f"cd {W} && git log --oneline -3"))
print(run(f"cd {W} && git status --short | grep -v cache | head -10"))
