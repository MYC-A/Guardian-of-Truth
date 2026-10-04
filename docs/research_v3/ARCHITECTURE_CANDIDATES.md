# Pilot mechanisms and boundaries

| Arm | Mechanism | Main failure expected | Runtime |
|---|---|---|---|
| A0 | One full-context source-ID judgement | Incorrect semantic interpretation despite valid IDs | Model verdict, no formula |
| A1 | Original INVENTORY/EFFECT/LINK/WITNESS | Early invalid or missing program; original offsets/arity | Unchanged EvidenceGraph |
| A2 | Source candidate discovery, then target-specific local lowering | Lost dependency, wrong scope or native join | Existing formula and native fact evaluator |
| A3 | Independent target-to-original-policy discovery, source union, same lowering | Extra false source candidates or correlated semantics | Same evaluator as A2 |

A2 differs from System V2 action inventory: its discovery sees the whole policy
and full catalogue, does not split into one program per tool, and postpones trees
until the current target is known. Its lowerer still receives all original
sources, including remote exceptions and definitions. The candidate list cannot
prevent the lowerer from revisiting original policy. A3's reverse pass receives
no forward list or explanation, but uses the same model; this is independent input
discovery, not statistically independent evidence or a proof by two model votes.

Code-issued policy/declaration/evidence/literal IDs are resolved to original
SourceStore spans. Native facts use `evidence_graph.facts.compare`: exact typed
comparisons, parent identity, valid receipts, chronology and stale-observation
checks. Missing facts remain UNKNOWN. Native evidence cannot bypass these checks
through a null check. An actual native call can witness an attempted occurrence,
not a successful effect. Local formulas are validated by the original Formula
contract, then evaluated by the original three-valued logic.

This pilot combines late formalization with a different ID wire representation.
An A2/A1 gain alone therefore does not isolate lateness from addressing or prompt
complexity. A0 shares ID addressing, so A2/A0 directly tests the added candidate /
formula mechanism. A3/A2 uses the same wire, runtime, sources and model; it tests
extra original-source discovery at higher call cost. A future equal-budget ID-only
A1 control is needed if early-versus-late claims remain promising.

NO_ERROR in A0/A2/A3 is a model coverage opinion. Neither empty candidates nor
visited sections mathematically prove completeness. All outputs remain research
shadow decisions; no production entrypoint or solver is modified.
