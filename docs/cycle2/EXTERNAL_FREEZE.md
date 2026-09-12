# External freeze

Before any prediction, Cycle 2 froze 100 cases from the pinned public source:
20 per drift category, selected from `tier=gold` by deterministic seed `260912`.
Selection uses tier, category, and stable sample ID only; it does not use the
ground-truth decision or rationale. The frozen set contains 85 `ERROR` and 15
`NO_ERROR` target steps, 16 IAA-subset records, and all five source categories.

The machine-readable manifest records:

- exact source commit and sample IDs;
- source file hashes and source JSON field paths used for localization;
- selection strategy and seed;
- adapter hash and Guardian selection commit;
- policy/goal context, history prefix, target assistant turn, and derived tool
  signatures for each case;
- fixed `ERROR=1`, `NO_ERROR=0` mapping;
- admitted model ID and known provenance limitations;
- immutable cases hash `d1863e7651c81afb73550b6ee2c984435aacda76d1a96e1b5c4dd5b380b0fedd`.

The candidate-arm prompt/threshold contract and implementation hashes are frozen
in a separate pre-prediction commit. After first predictions are joined to these
labels, no system or threshold change belongs to Cycle 2.
