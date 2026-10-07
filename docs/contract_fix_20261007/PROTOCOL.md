# Contract fix: offline acceptance — 2026-10-07

Branch: `fix/guardian-contract-safety-20261007`; baseline: `9794f50d`.
No production merge/default change. Historical data/gold/output/cache are read-only.

1. Reproduce the audit boundaries through production parser and public wiring.
   Add lawful/violation contrasts and preserve genuine earlier DF/Ems regressions.
2. Keep changes separate: arithmetic/token/schema/queue fixes vs semantic authority,
   closure and new blind input. No IDs/domain/tool-name business rules.
3. Full valid46 (all available repetitions), LB1/2/3, external and saved holdouts:
   exact-request raw replay of baseline and candidate, identical inputs and gold.
   New request hashes or absent verifier replies -> NOT_EXECUTED, not invented predictions.
4. Re-admission of legacy F proposals under the new binding is a separate diagnostic.
   Full-policy F extraction and neutral CB change the wire and require fresh replies.
   Never count old prepass/extraction replies as inference on their new inputs.
5. Measure TP/FP/FN/TN/F1 and per-case gains/losses, technical failures, coverage,
   reason/target changes and cache misses. Existing post-hoc gold remains diagnostic.
6. Accept pure fixes as nonregressing only if full matched replay has no new FP or
   lost TP on each comparable set/repetition. Report every exception. Safety repairs
   that lose unsupported historical TP must not be described as quality improvements.
7. No new live budget in this phase. New-wire quality remains NOT_EXECUTED until a
   separately frozen full-model phase; no claim of live F1 or independent transfer.
8. Independent subagent code and logic review after wiring; meaningful test suite,
   fresh-install/import smoke, durable receipts, regular commits and verified push.
