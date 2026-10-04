# Reproduction

Use an isolated research environment with Python3.13.7, BM25S0.3.12,
NumPy2.4.4 and Pydantic2.13.5; remaining preparation versions are in protocol.
No production dependency was added. Set PYTHONPATH to repository root plus src.

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
