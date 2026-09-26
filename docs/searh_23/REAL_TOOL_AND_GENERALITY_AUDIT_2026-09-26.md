# Real tool trace and generality audit — 2026-09-26

## Scope and reproducibility

This is a component audit, not a new Guardian competition run. It reads the
already inspected 46-case `valid.parquet` (SHA-256
`8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`)
and the existing `contracts/tool_effects_v1.json` (SHA-256
`a58aacb52ada327767fb524500e88ea846917c340a658e12d72366ba4485601a`).
The exact source catalog text must match a pinned hash. There are no LLM calls,
new labels, or changes to the frozen C1 candidate.

Reproduce from this repository root:

```powershell
$env:PYTHONPATH = 'src'
python experiments/searh_23/real_bound_contract_audit.py
python -m pytest -q tests/test_vnext_echo_pairing_v1.py tests/test_real_bound_contract_audit.py tests/test_vnext_ordered_effects_v1.py
```

Detailed per-case evidence is in
`outputs/searh_23/real_bound_contract_audit_v1.json`.

## What the real trace confirms

The `bound_tool_effects_v2` contract now confirms **three observed results**,
each for the exact requested entity and with an explicit result postcondition:

| Tool | Confirmed result | Bound effect | Important limit |
|---|---:|---|---|
| `cancel_reservation` | 1 | reservation cancelled | Does not establish every policy prerequisite |
| `exchange_delivered_order_items` | 1 | exchange **requested** | Does not establish completed exchange |
| `resume_line` | 1 | line active and suspension cleared | Does not establish policy compliance by itself |

The relevant action tools had 9 calls and only 3 results in the case history.
All three confirmed results occur in positive-labelled cases, but they do not
prove those violations. Binary predictions were not changed.

For reviewed **read-only** tools with no result transport ID, an exact ID echo
can recover source pairing when exactly one pending call matches. The result
field must be reviewed as an echo of the requested entity; similarity or FIFO
position is insufficient. This repair is limited to the pinned catalog
versions and leaves explicit transport IDs authoritative.

| Reader | Paired before | Paired after | Newly paired |
|---|---:|---:|---:|
| `get_order_details` | 4/14 | 14/14 | 10 |
| `get_reservation_details` | 8/39 | 39/39 | 31 |
| `get_user_details` | 15/15 | 15/15 | 0 |

Among the 41 new pairs, only one call and result were adjacent. 40 agree with
naive FIFO, but FIFO picks a different call for `retail__47::t12`: two earlier
lookup attempts used other IDs, while the result echoes the later valid order
ID. Thus the pairing rule has a concrete reason beyond recovering convenient
counts. It has not been shown to improve Guardian's labels; the current C1
does not consume this pairing layer.

## Independent generality branch audit

Fetched `codex/generality-research-20260926` at
`529b338dfb46fad9ce591d39c33a8279f673b25a` into a separate, detached
worktree. Its reported service-desk renamed result, TP16/FP7/FN0, is a
**post-hoc replay of sealed model answers**. It is useful diagnostic evidence,
not a fresh validated score. Its 39/39 claim-effect and 31/31 tool-type probes
use authored pairs with insufficient cross-action and cross-entity negatives.

The read-only counterexample script reproduces six unsound positives from
that exact commit:

1. Successful fee refund is accepted as proof of completed device replacement.
2. Replacement result for case `SD-9999` is accepted for a claim about `SD-5101`.
3. A verification call for case A with a result naming case B is accepted as
   verification of A.
4. Authorization for another case is accepted when its amount matches.
5. Successful fee refund is accepted as prior replacement success.
6. An authorization without an amount is accepted as an exact authorization
   for amount 250.

Evidence is in `outputs/searh_23/generality_counterexamples_529b338.json`.
Reproduce after fetching that commit into a separate worktree:

```powershell
python experiments/searh_23/audit_generality_counterexamples.py --branch-root '../Guardian-of-Truth-generality-audit' --output outputs/searh_23/generality_counterexamples_529b338.json
```

Its useful idea is kind-aware policy direction and value-based joins across
renamed tools. The current implementation cannot be promoted until it also
requires a matching action type, result entity, amount, and ordered successful
prerequisite for every positive proof. A fresh seal and an untouched domain
are still needed after those corrections. Merging the whole branch would also
remove current files, so this audit only transfers the supported mechanisms.

## Server check

The ModelScope machine was accessed through the existing HTTPS Guardian
Gateway API. GPU and CUDA checks succeeded. A targeted Linux test in the
remote repository failed because it expects a separate pinned incumbent
checkout at the sibling path `Guardian of Truth`, which is absent there. The
failure says nothing about these new components; their targeted local tests
pass. No full benchmark, GPU model run, Mistral call, or dependency install
was performed for this audit.

## Decision

Keep the bound action-result check and exact reader-echo pairing as narrow,
reviewed components. Keep all unsupported tools and propositions `UNKNOWN`.
Do not claim a score gain or deploy the generality v3 replay as an automatic
veto. The next score-bearing comparison needs an integrated, frozen candidate
and new adversarial cases that vary action, entity, amount, missing fields,
result order, and policy direction independently.
