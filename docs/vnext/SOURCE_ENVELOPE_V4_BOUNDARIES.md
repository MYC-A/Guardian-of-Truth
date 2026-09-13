# Source envelope v4: explicit role boundaries and runnable field integration

Status: IMPLEMENTED_CONTROLLED_CHECKS_ONLY; not a frozen model evaluation or
the whole-Core candidate. Frozen older implementations remain unchanged.

`source_envelope_v4.SourceEnvelope` contains original prompt/target text and
application-adapter-owned source frames. Each frame has explicit actor/kind,
source/body offsets, tool identity/provider/version/schema hash, caller/correlation
ID and optional source time. These attributes are not parsed from body text.
The application must authenticate this metadata at the source adapter boundary;
the DTO and its checksum do not establish authorship or external state truth.

The normalizer validates span containment/order, document bounds, immutable
metadata, target ASSISTANT provenance and nonoverlapping frames. Unframed
non-whitespace source or unknown actors block declared history completeness.
Malformed/duplicate-key/nonfinite JSON supplies no observed values. Embedded
SYSTEM/USER/TOOL markers stay body data even in a malformed result. Source hashes
bind the original text, all metadata and completeness premises without pretending
to authenticate them.

Call/result correlation uses indexed full tool identity, requesting actor and
transport ID. All ambiguous candidates remain; an explicit unknown ID is not
repaired by FIFO. No tool name/schema becomes a business effect. Target calls
are attempts only; target results/privileged actors cannot be source frames.
Confirmed effects require a separate versioned trusted T1 contract. Compatibility
with the actual T1 evaluator and scoped record-field prover is exercised directly.

## Runnable path and independent receipt

`factual_envelope_v4.analyze_envelope_factual_fields` accepts the original envelope,
source-owned identity declarations and an explicitly supplied semantic backend.
It runs C2's ten narrow tasks, indexes the source records, preserves all field-
meaning/binding alternatives and requests an independently checked v4 receipt.
No credentials are read and no implicit network client is created.

The independent checker rebuilds the envelope ledger, deterministic response
span/literal inventory and source-record lookup tables. It rechecks every mapping,
binding, typed field primitive and completeness claim. It rejects dropped spans,
omitted duplicate-name bindings, changed source values/metadata/complete-history
premises, changed proof scope and old receipt versions. It does not call the LLM,
binder or solver. v4 receipt hashes include the actual envelope, identity declarations
and graph. A receipt certifies conditional exact-result-field evidence only, not
unrestricted NL meaning, current state, completed action, causality or Core safety.

Thirty-two controlled tests cover source/T1/scoped-field/runtime/receipt
integration. `source_delimiter_envelope_v4_audit_v1.json` replays the preserved
public v3 counterexample: both inputs now have zero SYSTEM events under explicit
one-result source metadata; malformed input creates no observations. The older
counterexample and implementations remain preserved, not relabelled as repaired.
These checks are not competition performance or a universal security guarantee.

Remaining: source-specific competition/external adapters that supply authentic
frame metadata; single Core world/problem/certificate integration; state/time/
causal primitives; Goal v3 after the planned Policy stage audit; remaining stage,
regression/ablation and fresh-gated blind evaluation. Do not automatically guess
trusted frames from arbitrary unescaped plain transcripts to enable a verdict.
