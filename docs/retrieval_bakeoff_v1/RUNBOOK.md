# Reproduction

Use an isolated research environment with Python3.13.7, BM25S0.3.12,
NumPy2.4.4 and Pydantic2.13.5; remaining preparation versions are in protocol.
No production dependency was added. Set PYTHONPATH to repository root plus src.

The original local venv is `%TEMP%\guardian-retrieval-bakeoff-v1`.
The isolated server venv is `/workspace/guardian/retrieval_bakeoff_venv`,
Python3.12.3, with the same five sealed package versions. This interpreter
difference is disclosed in VALIDATION; original requests and controller replay
agree across the environments.

```powershell
$env:PYTHONPATH="$PWD;$PWD\src"
$env:PYTHONIOENCODING='utf-8'
python -m experiments.retrieval_bakeoff_v1.runner prepare
# Commit/push preparation before evaluation.
python -m experiments.retrieval_bakeoff_v1.runner offline
python -m experiments.retrieval_bakeoff_v1.runner prepare_models
# Commit/push exact model inputs before inference.
python -m experiments.retrieval_bakeoff_v1.runner impact --live
python -m experiments.retrieval_bakeoff_v1.runner s2g --live
python -m experiments.retrieval_bakeoff_v1.runner replay
```

The final two live commands run only once in a finite managed server job, using
existing credential discovery. No keys are printed, copied into requests, or
committed. Supplying --out selects a dedicated output directory. Cached replay
does not call preflight or inference. Preserve raw requests/replies, ledger and
dynamic gap packets together. Never rerun preparation over a different frozen
protocol or change a selector to match evaluation mistakes.

Tests: `pytest -q tests/test_retrieval_bakeoff_adapters.py
tests/test_retrieval_bakeoff_scoring.py tests/test_retrieval_bakeoff_gaps.py
tests/test_retrieval_bakeoff_runner.py tests/test_hybrid_transport.py
tests/test_evidence_graph_ranked_search.py tests/test_provenance.py`.

Models get the whole current parsed assistant move and exact selected sources,
not official gold/reference descriptions. Search is read-only; no examined
business tools execute. Exceptions and absent history remain unresolved unless
the actual relevant sources/semantics support a claim. Outputs are diagnostic
research artifacts, not production compliance certificates.

Finite server model jobs use the detached pre-inference worktree
`/workspace/guardian/repos/retrieval-bakeoff-v1-20261004` at `0c5c7b19`
and output `/workspace/guardian/results/retrieval-bakeoff-v1-20261004`.
Supervisor programs `guardian_retrieval_bakeoff_impact` and
`guardian_retrieval_bakeoff_s2g` are explicit-start, no-restart finite jobs.
Both exited 0; their complete execution logs are retained. Each wrapper sets
PYTHONPATH to the worktree and its src, then invokes the corresponding live
command above with `--out` pointing to that dedicated result directory.
No unrelated service or external port was changed.

For zero-network final diagnostics, run `scripts/retrieval_bakeoff_metrics.py`
with the same PYTHONPATH. It verifies all 610 sealed input bytes and exact S2G
catalog records, source-read/token bounds and actual ledger totals, then writes
`s2g_source_metrics.json`. It does not change runtime selectors/references or
send API calls. Preserve the separately recorded semantic reference and
receipt-classification defects rather than rerunning the frozen protocol.
