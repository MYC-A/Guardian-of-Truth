# T2 fixture stage v1 — pre-evaluation protocol

This is a separate model stage on the existing 18 frozen tool fixtures, not a
rerun or repair of T1 v1. The independent executable reference is the authority;
the LLM is never gold. Network phase is NOT_RUN until the active native Goal v2
process terminates. Never run the two API jobs concurrently.

Implementation: `stage_tool_t2_v1.predict_t2` and
`scripts/evaluate_vnext_tool_t2.py`. Freeze requires committed/tracked executable
sources, hashes all imported project source, benchmark inputs and reference,
and records provider/configuration/metric rules. B.AI qwen3.8-flash, temperature
0, 180-second timeout, requested output cap 2048, one request in flight with
at least ten seconds between starts, zero hidden retries. Each exact prompt,
schema and input hash is persisted before transport. Paused or interrupted
requests must follow the existing no-hidden-retry resume protocol.

The model receives only case input, real argument/result fields, schema and
the frozen reference as declared fixture documentation. The prior-state input
is preserved as source data, not fabricated by the model. Every raw valid
proposal remains available beside accepted candidates, exposing grounding
rejections. All accepted effects remain untrusted possibilities; causal action
confirmation and trusted contract hashes are prohibited.

The actual primitive prover is also exercised with T2 candidates supplied in
the effect collection and no T1 registry. State, completion and causal support
must remain UNKNOWN. This verifies a real proof boundary, not just an output
label. It does not measure beneficial whole-Core downstream value.

After all 18 predictions are sealed, scoring measures:

- Candidate recall for the four exact known-true archived-state reference rows,
  excluding transport/schema failures from conditional semantic denominators.
- Candidate precision restricted to those exact annotated known-true rows.
- Raw/accepted candidate counts and grounding rejections.
- Unsupported transfer of documentation to incompatible version/schema, kept
  separate from unsafe trust promotion.
- Unsafe trusted candidates, ledger pollution and false primitive support.
- Transport/schema reliability, per-request p50/p95, reported tokens; cost is
  NOT_AUDITED. Per-case failure taxonomy precedes any next-version fix.

Unknown reference state is not false: full candidate precision on those rows is
unadjudicated, rather than fabricated. Likewise, a POSSIBLE_EFFECT does not
claim that the current state is proved. This fixture does not supply a complete
effect ontology for real unseen tools. Full generalization and beneficial
downstream gain remain NOT_ESTABLISHED even if these controlled checks pass.

Twenty-four controlled tests pass, covering all fixtures, retained rejected
proposals, multiple possibilities, transport/schema exclusions, incompatible
documentation scope and tampered trust/ledger outputs. Model metrics are still
pending. The whole Guardian vNext goal remains incomplete.
