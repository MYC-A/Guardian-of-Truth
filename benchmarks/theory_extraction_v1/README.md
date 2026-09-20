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
