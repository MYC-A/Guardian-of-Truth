# Universal repair — repository audit (Phase 0)

Branch `research/guardian-universal-repair-20261006`, created from
`research/independent-architecture-audit-20261006` @ `197af74c92bdcf036e0de791ade89015de8c83b8`
(contains V4 final `32ede180` + audit commits `1ef2dd31`, `9f2d5d40`, `197af74c`). tau2-bench pinned at `5bfa7e37`.

Environment: Python 3.13.14, Linux x86_64 (glibc 2.34), pydantic 2.13.5, pandas 3.0.6, pyarrow 25.0.1,
litellm 1.104.0, httpx 0.28.1, pytest 8.4.2. File fingerprints (71 files: verification/integrated/source_search
code, scorer, runner, gold builders, every V4 run record, lockbox/external inputs and gold):
`outputs/universal_repair/phase0/fingerprints.json`.

## Frozen raw replay (no network)

`python -X utf8 scripts/independent_architecture_replay.py --output docs/universal_repair/phase0_raw_replay.json`
(network sockets patched to raise; refuses to overwrite). Result: **PASS, 472 rows, 903 exact request-hash
replays** (valid46 57, LB1 144, LB2 107, LB3 r1 101, LB3 r2 108, ext r1 123, r2 127, r3 136), zero decision or
accusation differences vs stored records. Arm metrics are identical to the audit's `raw_replay.json`.

The only differing field is `input_records_sha256` for all 8 record files. Converting LF→CRLF reproduces the
audit's hashes exactly (e.g. LB2 `785c3c…` → `7cfe93…`), so the audit ran on a CRLF checkout:
`outputs/verification_v2/**` had no `eol=lf` attribute. Fixed in `.gitattributes` (this phase). Semantic
content is identical; byte hashes are now checkout-independent.

## What was NOT run in P0
The old score report, `rescore_v2`, gold builders and freeze scripts were not re-run over frozen outputs
(they overwrite/derive artifacts); scores are recomputed only by the new P2 scorer into new paths.

## Code map of the defects addressed (file:line at base 197af74c)
| Layer | Defect | Location |
|---|---|---|
| I/O | locale-dependent `read_text()` for inputs/records | `experiments/verification_v2/run.py:33-37,52-58` |
| I/O | scorer silently last-wins on duplicate record ids (ext rep3: 92 lines / 70 ids) | `run.py:load`, `score.py` |
| Proof | eager `{ADD,SUB,MUL,DIV}` dict evaluates `a/b` for every op → `ZeroDivisionError` → UNRESOLVED for ADD/SUB/MUL with right=0 | `proof.py:203` |
| Proof | `DT_RE` drops seconds, ignores timezone | `proof.py:37,72-77` |
| Proof | operand dedup by (source, quote, value) string, not atomic leaf identity | `proof.py:139` |
| Numeric | `num_equal` tolerance `max(0.006, 1e-4·|b|)`: 100000 == 100009 | `derived.py:184` |
| Evidence | Q2 fuzzy match admits a quote with a deleted NOT (9/10 words) | `common.py:_fuzzy_in` via `leaf_quote_ok` |
| Evidence | JSON pairs grounded independently anywhere in source (not same object) | `proof.py:json_leaves_ok` |
| Evidence | NOT_MEMBER_OF over model-chosen members without a complete set | `proof.py:_run` |
| DF | global copy suppression: value present in ANY tool result skips the claim | `df4.py:200-217,360` |
| DF | no assertion scope: rejected/quoted claims are checked as the move's assertions | `df4.py:extract/self_checks` |
| DF | silent `claims[:10]` slice | `df4.py:334` |
| Confirm | last-user-turn only (a later "Thank you" erases consent), no proposal scope | `confirm.py:binding` |
| Confirm | id substring matching `BK-1` ⊂ `BK-10` | `confirm.py:147,153` |
| Confirm | "yes, but…?" counted as affirmation; "does not require confirmation" triggers | `confirm.py:17,33` |
| Closure | `(not )?` optional: "never call a tool that is on the list" = closed | `v3.py:17-23` |
| Pool | first admitted candidate only (AT by move order, Ems proofs[0]/sems[0], DF first mismatch) | `alltarget.py:61-69`, `ems.py:212,219`, `df4.py:319,369` |
| Verifier | witness = cited + recent-4 history: counter-evidence older than 4 events is invisible | `verifier.py:narrow` |
| Verifier | technical failure (INVALID_JSON twice) → candidate silently dropped | `v4.py:_verify`, `comp` |
| Decision | `code_proven` boolean lets mechanical arms bypass the verifier | `v4.py:decide_v4` |
