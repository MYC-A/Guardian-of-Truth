# Theory extraction v1

This is the existing 17-case semantic synthetic set frozen into one common
input for Architecture B0/B1/B2/B3. It is a controlled, already seen diagnostic
and is not independent contest validation.

- `input.jsonl` contains exact policy sources and frozen clause offsets, with no
  labels or expected rules.
- `competition_input.csv` contains only `id,prompt,response` for the formal
  handoff.
- `gold.jsonl` is joined only after inference for semantic preservation and
  verdict metrics.
- `manifest.json` records hashes and the gold firewall.

Rebuild with `python benchmarks/theory_extraction_v1/build.py` from the
repository root. The sentence boundaries are benchmark data, not a production
policy parser.

## B3 smoke subset

`b3_smoke_input.jsonl` and `b3_smoke_competition_input.csv` freeze five rows
for the first real mutual-review chain. They cover an exception, a modality
inversion proxy, temporal order, a knowledge-base rule proxy, and source
provenance. They remain seen synthetic diagnostics. This benchmark has no gold
dimension for tool execution success or action authorship; the proxy rows must
not be reported as measuring those properties. Gold stays separate in
`b3_smoke_gold.jsonl`; exact hashes and the selection rationale are in
`b3_smoke_manifest.json`.
