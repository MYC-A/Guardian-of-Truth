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

## Result (evaluator at 2a45dfe0, `outputs/contract_lint_20261010/result_2a45dfe0.json`)
Decision pools (397 de-duplicated labelled rows, 10 pools; B2 F1 .9211):
- `UNKNOWN_TOOL`: 3 fires, all gold-positive, 0 new FP, 0 new TP (B2 already caught them) → **HARD** by the rule.
- `SCHEMA`/`INVALID_ARGS_JSON`: 0 fires → INSUFFICIENT_FIRES (not adopted).
- `REPEAT_FAILED`: 0 fires → INSUFFICIENT_FIRES (not adopted).
valid46 (report only, contaminated): UNKNOWN_TOOL 5 fires / 5 positive, +3 TP vs stored B2 Q8 rep1;
REPEAT_FAILED 1/1 positive. Adoption is limited to UNKNOWN_TOOL; evidence for it outside valid46 is thin (3 rows).

## Amendment 2 (logic review; checks re-specified before re-evaluation)
Review of the code against the input format found one bug and three universality gaps:
1. **Call→response pairing (bug).** In a turn all `→ TOOL_CALL` lines precede all `← TOOL_RESPONSE`
   lines, in the same (FIFO) order; the old code paired a call only with the line right after it, so
   only ~53% of history calls were paired. Now history is split into `⟦ROLE …⟧` blocks and the i-th
   response of a block is paired with its i-th call; if counts or names disagree the outcome is unknown
   (abstain). On all pools every block matched (2023/2023).
2. **REPEAT_FAILED** now fires only if the *last history event* is the failed call (no USER turn in
   between): a user message may change external state (e.g. device actions), so a retry can be legitimate.
3. **SCHEMA:** a parameter-like line in an unknown notation (`    name: <not a known JSON type>`) marks
   the tool's parameter list incomplete → the "unknown parameter" check is skipped for that tool.
4. **Catalog robustness:** a catalog that is not terminated by a following section (possibly truncated)
   → abstain; an "unknown" tool whose name is mentioned inside the catalog text (alias/note) → abstain.
Decision rule and pools unchanged. Result (`outputs/contract_lint_20261010/result_amend2.json`):
decision pools identical — UNKNOWN_TOOL 3 fires / 3 positive, 0 new FP → **HARD**; SCHEMA 0 fires,
REPEAT_FAILED 0 fires (also 0 without the USER-turn restriction, diagnostic) → not adopted.
valid46 (report only): UNKNOWN_TOOL 5/5 positive, +3 TP; REPEAT_FAILED 0 (the earlier 1 fire had a USER
turn in between). Note: valid46 comparison is against stored B2 **Q8 rep1** (F1 .7027 → .80), not the
production run (.789); for vLLM graph16 (.8205) UNKNOWN_TOOL would add banking_083 → est. TP17/FP0/FN6, F1 ≈ .85.
