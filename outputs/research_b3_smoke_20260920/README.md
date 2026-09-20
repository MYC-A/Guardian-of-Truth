# Real five-case Architecture B pilot

All five rows are seen synthetic diagnostics from
`benchmarks/theory_extraction_v1/b3_smoke_input.jsonl`. Gold was read only
after model outputs were sealed. Remote namespace:
`/mnt/data/guardian/results/b3_smoke_0694c2d_20260920T1815Z/`.

- `export_3a073a5.tar.gz`: SHA-256
  `79e5c27aa1fe7d6fec109eed4f417f8c93ad78adc9c752f5c52bca7f18c14593`.
  Contains original provider responses, LangExtract fragments, first B3 model
  cycle, B0/B1/B2 and B3 records, N5 alternatives, status, and per-file hashes.
- `export_509c1c9.tar.gz`: SHA-256
  `93d74bedd4fdd96eea862d1b233a0faf5ecaee663a4d18a00d14b7f519375e33`.
  Contains the repeated real model cycle after Mistral multi-type critique
  parsing was fixed, plus B3 records and N5 alternatives. Original provider
  outputs were reused without new extraction calls.

`ca3a81f` later corrected the classification of an empty repair in response
to grounded issues. The archived `509c1c9` model cycle keeps its historical
`BIDIRECTIONAL_COMPLETE` text; all five actual NuExtract repair responses have
empty `changes` and `additions`. No semantic repair or formal proof occurred.
The full 17-case matched comparison is tracked separately.
