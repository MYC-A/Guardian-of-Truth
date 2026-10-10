# Contract lint (L0) — pre-registered protocol

Written and committed BEFORE any evaluation of the checks below.

## Goal
Domain-independent checks derived only from the *format contract* of the input
(tool catalog in `[AVAILABLE TOOLS]` + structured trace), never from the text of a
policy and never from observed errors. Each check either fires with evidence or abstains.
Code never sets label 0.

## Contamination disclosure
The author inspected valid46 false negatives before proposing this direction.
Therefore valid46 is reported but **excluded from every decision below**.
A domain-specific check suggested by a valid46 error (`item_ids == new_item_ids`) is
deliberately NOT implemented.

## Checks (current assistant turn only)
- `UNKNOWN_TOOL`  called name not in the parsed catalog (exact match, whitespace-trimmed).
- `INVALID_ARGS_JSON`  call arguments are not a JSON object.
- `SCHEMA`  vs the parsed catalog entry: missing required parameter, unknown parameter,
  JSON-type mismatch (string/integer/number/boolean/array/object), value outside a listed enum.
- `REPEAT_FAILED`  identical (name, canonical JSON args) to an earlier call in the history
  whose response was marked `[ERROR]`, with no other tool call in between
  (deterministic environment: same call on unchanged state gives the same error).
Abstain (no finding) whenever the catalog or the call cannot be parsed.

## Arms (offline, on stored B2 Q8 rep1 binaries; no new model calls)
`B2`, `B2|UNKNOWN_TOOL`, `B2|SCHEMA+INVALID_ARGS_JSON`, `B2|REPEAT_FAILED`, `B2|ALL_L0`.
Rows are de-duplicated by (prompt, response) hash across pools; rows with no B2 binary
are reported as gaps and use B2 = missing (not scored for the arm delta).

## Decision pools
ext_tau2, hold_tau2h, hold_holdout2, lb_long, lb2_long, lb3_long, contrast, dev, devT, frozen.

## Pre-registered decision rule (per check)
- **HARD** (may set label 1 directly): new FP vs B2 = 0 on decision pools, and the check
  fires on ≥ 3 decision-pool rows overall.
- **EVIDENCE only** (may be passed to the reviewer, never sets a label): new FP 1–2.
- **REJECT**: new FP ≥ 3, or precision of raw fires on decision pools < 0.8.
Reported for each check: raw fires on gold-positive / gold-negative rows, new TP / new FP
vs B2, per pool. No threshold or rule is changed after seeing these numbers; any change
requires a new protocol version and a fresh pool.

## Amendment 1 (parser bug, before re-evaluation)
First evaluation (`outputs/contract_lint_20261010/result_0a9ebb09.json`, kept) produced 0 fires
on decision pools. Structural diagnostics (no labels viewed) showed the catalog parser
anchored on the first textual mention of `[AVAILABLE TOOLS]`; several policies mention it
inline ("never call a tool that is not listed there"), so 10–14 rows per lb pool abstained.
Fix: the catalog header must be a line of its own and occur exactly once; otherwise abstain.
After the fix every row parses except 2 contrast rows with a duplicated tool declaration
(correct abstention). Checks, arms and the decision rule are unchanged.
