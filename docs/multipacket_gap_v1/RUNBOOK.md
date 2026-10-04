# Runbook — multipacket / gap controller v1

## Setup
```bash
pip install pyarrow bm25s "pytest<9" pydantic
export PYTHONPATH=$PWD:$PWD/src
set -a; . <keys.env>; set +a      # MISTRAL_API_KEY (reviewer), OLLAMA_API_KEY (reason judge only)
python -m pytest -q tests/test_multipacket.py tests/test_evidence_packer*.py   # 31 tests, no network
```

## Zero-inference steps
| Step | Command | Output |
|---|---|---|
| Offline packet coverage / overlap (valid46, ref15) | `python -m experiments.multipacket_v1.offline` | `outputs/multipacket_v1/offline/rows.json` |
| Dry run (request building, no calls) | `python -m experiments.multipacket_v1.dry` | stdout |
| Build SYN-M1 (deterministic) | `python -m experiments.multipacket_v1.suite.build_syn` | `outputs/multipacket_v1/suite_syn_m1/` |
| Freeze manifest | `python -m experiments.multipacket_v1.freeze` | `FREEZE_v1.json` |
| 20k vs 48k diagnosis (frozen cache) | `python -m experiments.multipacket_v1.diag_20k_48k` | `reports/diag_20k_48k.json` |
| R1 programmatic reason checks (frozen cache) | `python -m experiments.multipacket_v1.r1_offline` | `reports/r1_offline.json` |
| Controller / cost stats | `python -m experiments.multipacket_v1.stats outputs/multipacket_v1/runs/<suite>/run<k> outputs/multipacket_v1/reports/stats_<suite>_run<k>.json` | same |

## Inference
```bash
# valid46 pilot (A/B/FULL replies come from the frozen U2 cache)
python -m experiments.multipacket_v1.run --suite valid46 --run 1 --workers 7 --arms CTRL,C1,C2,D1,D2,D3,G2_S,G2_L,G3B,G3V,G4_S,G4_L,ORACLE_E,ORACLE_R
# SYN-M1 final, 3 repetitions (run each twice: the second pass only retries transport failures)
for k in 1 2 3; do for t in 1 2; do
  python -m experiments.multipacket_v1.run --suite syn_m1 --run $k --workers 7 --arms A,B,FULL,CTRL,C1,D1,D2,G2_L,G4_S
done; done
# reports (+ gpt-oss:120b reason judge on TPs)
python -m experiments.multipacket_v1.report --suite syn_m1 --runs 1,2,3 --judge --arms A,B,FULL,CTRL,C1,D1,D2,G2_L,G4_S
```
- The cache lives in `outputs/multipacket_v1/cache` (key = sha256(request) + attempt). Re-running is free. Repetition k uses attempt k-1.
- Mistral sustains ≈9 calls/min with 7 workers; 429s are retried and never cached.
- Run outputs: `outputs/multipacket_v1/runs/<suite>/run<k>/<arm>.jsonl`. Reports: `outputs/multipacket_v1/reports/`.

## Using the components in production code
- `guardian_truth.evidence_packer.pack(row, PackerConfig(budget_bytes=20000))` stays the default. The new hooks (`extra_queries`, `exclude_uids`, `shared_anchors`) are opt-in. With their defaults, output is byte-identical to U2.
- `guardian_truth.multipacket.controller.Controller(row, read_units, order='PRIORITY', max_hops=4, max_chars=8000, max_depth=2).explore(questions)` is deterministic and makes no LLM calls. `.summary()` returns the hops, chars, stop reason and loops prevented.
- `guardian_truth.multipacket.ledger`: typed claims. Model output is never promoted to EXACT.
