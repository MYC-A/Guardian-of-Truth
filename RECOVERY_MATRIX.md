# Recovery matrix — modular hybrid followup, 2026-10-01

All counts here refer to **completed dev jobs**. Controlled upstream faults
are separated from natural model errors. Sealed scores are pending the full
completion gate. Exact IDs, votes and costs are retained in the linked journals.

## Natural first-judge errors

| Helper after Gemma | Recovered | Harmed | Still wrong | Scope |
|---|---:|---:|---:|---|
| GE / GP surface / both / evidence prose | 0 | 0 | 14 | Each presentation variant alone |
| Phi, without graph | 0 | 0 | 14 | Same unverified translations supplied as advisory |
| Phi, with graph | 0 | 0 | 14 | No matrix interaction |
| Independent B, positive routing | 11 | 0 | 3 | Raw original sources |
| Independent B, positive routing + GE/GP | 12 | 0 | 2 | Exact observation graph + source clauses |
| B, all targets | 11 | 0 | 3 | No incremental labels over adaptive B |
| B, all targets + GE/GP | 12 | 0 | 2 | More calls, same labels as adaptive B |
| Granite advisory to B | 10 | 0 | 4 | No extra gain over B alone |
| Granite advisory to B + GE/GP | 12 | 0 | 2 | Same labels as B+GE/GP without Granite |

Source runs: `20912812e42d502de1f3`, `436ba4b3c7bb178336ca`,
`f949f802a239f2c3cdce`, under `outputs/hybrid_*`.
There were **no natural Gemma FN in this 80-case dev**, so these jobs do
not establish recovery of missed upstream violations.

## Explicit upstream fault injections (12 cases)

Inputs (policy/history/target) stay unchanged; only the hypothetical
upstream verdict/findings are replaced. No fault tag or gold label enters B.
The finding module is explicitly `controlled_upstream`, not attributed
to an actual model. Every injected upstream decision was wrong, so this
bank cannot measure harming a correct upstream decision.

| Injected fault | B v1 | Source interface v2 |
|---|---|---|
| Action scope attached to a check | Corrected | Corrected |
| Check mistaken for execute | Corrected | Corrected |
| Correct matching ID declared wrong | Corrected | Still wrong: invents same-turn prerequisite |
| Old observation used against current answer | Invalid quote, preserves FP | Corrected |
| Computable bound declared unobserved | Corrected after technical re-ask | Corrected |
| Failed attempt mistaken for successful prerequisite | Finds error but invalid event refs; preserves FN | Corrected |
| Factual claim entirely missed | Finds error but invalid event refs; preserves FN | Invalid response; preserves FN |
| Current action omitted from inventory | Finds error but invalid event refs; preserves FN | Corrected |
| Fabricated quote in upstream accusation | Corrected | Corrected |
| Uncertainty mistaken for unsupported world claim | Still wrong: blames history action | Still wrong |
| False upstream counterproof of an over-limit action | Invalid event refs; preserves FN | Corrected |
| OR alternative ignored | Invalid response; preserves FP | Corrected |

V1 recovered **5/12**, with six invalid reviews; v2 recovered **9/12**,
with one invalid review. V2 recovered 3/4 hidden violations. It also
failed one case that v1 repaired. This is a useful **interface repair
diagnostic**, not a new end-to-end quality result or a held-out validation.

V2 exposes the actual event-ID namespace and checks every nonempty
additional-error quote. It does not silently map source bucket names to
event IDs, repair the semantic verdict, or remove the quote checks.
The prior frozen natural/sealed arms retain v1 unchanged.

Full table: `outputs/hybrid_fault_recovery/matrix.json`; raw jobs
`e356a21c9a43c924410a` and `d7a555727460095b8e64`.

## Coverage that is still missing

The fresh bank has OR alternatives, **not a genuine exception-scope
policy**. Exception recovery cannot be inferred from its gate cases.
These diagnostics do not establish completeness of policy extraction,
goal reachability, arbitrary omitted multi-action inventories or faithful
NL→logic. They also do not establish UNKNOWN→certified truth: B still
produces a model interpretation with mechanically validated provenance.
