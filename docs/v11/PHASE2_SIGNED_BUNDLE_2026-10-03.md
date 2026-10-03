# Phase 2: offline-compiled signed policy bundle, LLM-free runtime

## What runs where
| Stage | Where | LLM | Artifact |
|---|---|---|---|
| Proposer replies | research runs (frozen) | yes, once | `outputs/searh_23/v11/pilot_*_audit.zip` |
| Table assembly (3-proposer agreement) | CI, `scripts/build_policy_bundle.py` | **no** | `build/policy_bundle.json` |
| Signature | CI | no | `HMAC-SHA256` with secret `GUARDIAN_BUNDLE_KEY`, else `SHA256` digest |
| Gate | runtime, `guardian-gate` / `python -m guardian_truth.policy_table_v11.service` | **no** | `predictions.csv`, `audit.jsonl`, `metrics.json` |

`load_bundle` re-checks the signature, each table digest and the agreement of every table
(`verify_table` re-assembles atoms from stored proposals). A tampered or wrongly keyed bundle is
refused at startup; a table for a different policy hash is never applied. `--require-hmac`
refuses unsigned (digest-only) bundles in production.

Policies without exactly three proposers are listed under `coverage` with the reason and are
not compiled. Proposals are never padded or fabricated.

## Current coverage (honest)
| Policy | Proposers stored | Compiled |
|---|---|---|
| `da31c80e…` | 2 (gpt-oss-120b, nemotron-3-ultra) | no: `needs_3_proposers_have_2` |
| `3dc4a44d…`, `78d0b5ce…`, `c39cd882…` | 0 | no |

So the bundle currently carries 0 tables and the gate runs on Phase 1 invariants only.
Filling coverage needs one more proposer sample for `da31c80e…` and three for the others;
that is a one-off offline compile, after which the bundle is rebuilt and re-signed in CI.

## Domain-agnostic call invariants (`invariants.py`)
No policy table and no LLM; patterns are generic, no dataset IDs or tool names:
* `PLACEHOLDER_ARGUMENT`: template/placeholder value (also inside JSON-string wrapped arguments).
* `NOOP_REPLACEMENT`: `x` and `new_x` equal (same array position) - an item replaced by itself.
* `REPEATED_FAILED_CALL`: identical tool + arguments already returned `[ERROR]` in visible history.

Caveat: these three patterns were chosen after reading FN explanations of valid.parquet,
so the gain below is a development-set result, not hidden-test evidence.

## valid.parquet (46 rows, LLM calls: 0)
| Version | TP | FP | FN | TN | P | R | F1 |
|---|---|---|---|---|---|---|---|
| Phase 1 invariants | 8 | 0 | 15 | 23 | 1.000 | 0.348 | 0.516 |
| + call invariants | 11 | 0 | 12 | 23 | 1.000 | 0.478 | **0.647** |

Verdicts: ADMISSIBLE 12, VIOLATION 11, UNKNOWN 23 (all prose). Latency median 0.26 ms, max 5 ms.
CI fails if F1 drops below 0.60 (`--min-f1`).

Remaining FN (12): policy-semantic (dates vs current time, verification 2-of-N, premature
escalation, one-shot return/exchange, expired contract) need compiled atoms; 2 prose errors need the prose channel (Phase 3).

## Run
```bash
PYTHONPATH=src python scripts/build_policy_bundle.py --output build/policy_bundle.json
PYTHONPATH=src python -m guardian_truth.policy_table_v11.service --input valid.parquet \
  --bundle build/policy_bundle.json --output build/predictions.csv \
  --audit build/audit.jsonl --metrics build/metrics.json
```
CI workflow: `.github/workflows/guardian-gate.yml` (if the push token lacks `workflow` scope, a copy lives in `ci/guardian-gate.yml`; move it in place).
Docker: `docker build -f Dockerfile.gate -t guardian-gate .` (after building the bundle).
