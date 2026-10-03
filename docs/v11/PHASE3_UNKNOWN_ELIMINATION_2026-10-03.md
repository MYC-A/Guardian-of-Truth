# Phase 3: no more UNKNOWN on prose, policy-quoted temporal / quorum rules

## Result on valid.parquet (46 rows, LLM calls: 0)
| Version | TP | FP | FN | TN | P | R | F1 | UNKNOWN |
|---|---|---|---|---|---|---|---|---|
| Phase 2 (call invariants) | 11 | 0 | 12 | 23 | 1.000 | 0.478 | 0.647 | 23 |
| Phase 3 (1/n) turn shape, contact provenance | 15 | 0 | 8 | 23 | 1.000 | 0.652 | 0.790 | 23 |
| **Phase 3 (2/n) this change** | **19** | **0** | **4** | **23** | **1.000** | **0.826** | **0.905** | **0** |

Latency median 0.55 ms, max 32 ms.

## What changed
* **Prose channel is no longer UNKNOWN by construction.** Prose steps go through bounded
  prose invariants (`prose.py`). If none fires the step is `ADMISSIBLE` with a
  `PROSE_RESIDUAL_RISK` note listing what was checked (same bounded-admissibility contract as
  tool calls). UNKNOWN now means only: empty step, missing catalog, rejected policy table.
* `REDUNDANT_INFO_REQUEST` (prose): the agent asks for a personal field (DOB, e-mail, phone,
  address, zip) of a *named* person while an observed tool record for that person already
  carries it. EN/RU request cues; name binding is exact (first + last name).
* `ARITHMETIC_CLAIM_ERROR` (prose): explicit `a + b - c = r` chains are recomputed exactly.
* `TEMPORAL_PROHIBITION` (`temporal.py`): compiled from policy wording
  "not allowed / must not / cannot <action> if <entity>'s <date field> is in the past / has
  expired". Action -> tool by verb class + object stem in the tool declaration; field -> key
  by snake-casing; record bound through the call's own `<entity>_id`; "now" from the policy
  current time or the latest current-time tool result. Any unresolved link -> silent.
* `AGGREGATE_INCLUDES_PAST`: the user's last message restricts to upcoming/future items and a
  summed operand belongs only to records whose every event date is already past.
* `VERIFICATION_QUORUM_NOT_MET` (`verification.py`): policy "any K out of: f1, ..., fN";
  for a tool declared as logging a verification, at least K listed values must appear in the
  user's own messages (format-tolerant). Values the user only acknowledged do not count.
* `records.py`: shared source-bound helpers (observed tool records, user texts, reference
  date, EN/RU date parser).

## Generality checks (not tuned on labels)
* **History replay** (`403` earlier assistant steps of valid, replayed as pseudo-targets;
  unlabeled but mostly correct behaviour): the five new rules fire **0** times.
  4 historical verification calls pass the quorum check; the 1 target call that logs a
  verification with only one user-provided value fails it.
* **Synthetic sealed sets** (modular_steps dev/sealed, fresh_v1 dev/sealed, 496 rows): FP stays 0.
  Recall there is still 0: those sets test boolean gate expressions that need the compiled
  policy table (Phase 2 bundle has 0 tables until three proposers are stored).
* Unit tests on out-of-domain dialogues (ticket warranty, bookings, member verification):
  `tests/test_policy_table_v11_phase3_semantics.py`. V11 suite: 276/276.

## Remaining FN (4) and why they are not forced
| Row | Needed reasoning |
|---|---|
| banking 003, banking 018 | "premature transfer": whether search options were *really* exhausted. A deterministic proxy (unused read tool / single failed lookup) also matches the negative banking 063, so it is not shipped. |
| banking 051 | KB criteria (utilisation threshold) must be read from retrieved documents and applied before unlocking a tool. |
| retail 29 | false refusal: needs understanding that the requested hose is a variant of the same product. |

These need the semantic (LLM) channel; no model endpoint/key is configured in this runtime.

## Known risk
`MULTIPLE_TOOL_CALLS_IN_STEP` is policy-quoted but fires on 35 of 403 history steps; in valid
no negative target has parallel calls, so it costs no FP here, but on other data it may.
