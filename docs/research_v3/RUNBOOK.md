# Reproduction without credentials or new inference

Use the published branch and keep its existing historical runtimes intact. The
V4 server protocol was generated with Pydantic 2.13.5; replay verifies that exact
version and normalized source hashes. The historical graph protocol uses 2.10.3
and must be replayed in a separate environment.

```powershell
python -m venv .venv-v4
.venv-v4/Scripts/python -m pip install pydantic==2.13.5 pytest pytest-asyncio
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
.venv-v4/Scripts/python -m pytest -q tests/test_semantic_hybrid_v4.py tests/test_evidence_graph.py tests/test_evidence_graph_quote_adapter.py tests/test_evidence_graph_ranked_search.py tests/test_evidence_graph_api_worker_v2.py tests/test_system_proof_engine.py
.venv-v4/Scripts/python experiments/research_v3/pilot.py replay
.venv-v4/Scripts/python experiments/research_v3/score.py
.venv-v4/Scripts/python experiments/research_v3/diagnostics/audit_results.py --out outputs/searh_23/semantic_hybrid_v4_20261004
```

`replay` has no HTTP path. It validates protocol/model request identity, parses raw
receipts and re-evaluates original programs. Missing receipts stay UNKNOWN; use
the complete saved output archive for full reproduction. `score` opens immutable
gold only after predictions exist. Never run `prepare` against an existing seal.
The .venv paths are ignored by Git; credentials are neither needed nor copied.

For source-ID development controls:

```powershell
.venv-v4/Scripts/python experiments/research_v3/diagnostics/id_controls.py replay --control graph_ids --out outputs/searh_23/semantic_hybrid_v4_graph_ids_dev_20261004
.venv-v4/Scripts/python experiments/research_v3/diagnostics/id_controls.py replay --control context_enums --out outputs/searh_23/semantic_hybrid_v4_context_enums_dev_20261004
.venv-v4/Scripts/python experiments/research_v3/diagnostics/gemma_contract.py replay --out outputs/searh_23/semantic_hybrid_v4_gemma_contract_20261004
```

These adapters have separate hashes and cannot replace the primary results. The
original strict-wire Gemma phase records a provider contract failure, not a model
semantic score. The new adapter makes the reply schema model-visible and permits
only one outer JSON fence to be removed. No aliases, altered values, trailing
comma fixes or formula repairs are allowed.

Live `run` is a distinct explicit mode. On the current server, credentials are
loaded only in memory from existing secret files. Finite workers are managed by
supervisor with no automatic restart and no exposed port. Snapshot ZIPs preserve
request bodies, raw replies, ledgers and predictions off-box; no model weights
are downloaded. Archive reconstruction normalizes CRLF for code/manifest hashes,
while SourceStore retains original source characters.
