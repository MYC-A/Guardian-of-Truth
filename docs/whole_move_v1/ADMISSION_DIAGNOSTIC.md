# Phase-v1 admission diagnostic

Read-only analysis of all 36 completed paired stages: 6 previously examined real
rows and 12 authored contrasts, each with BASELINE and WHOLE_MOVE. No API calls,
repairs, relaxed admission, or reassigned source IDs were used. Frozen source,
requests, raw replies and decisions remain unchanged.

Protocol SHA256:
`517edb91a9928cb61f5f07951d81c6d87f5aa7be27f65fe71294f3fd40b94266`.
The exact-byte SHA256 of `model/decisions.json` inspected here is
`0be526582bbc354d04aac694ebec7fe3b7ab839b3063514c2dfd9797e4cb46db`.

## What actually failed

All six real WHOLE_MOVE stages are technical failures: four reject a literal
quote and two end at the 3,600-token output cap. The authored stages have eight
admitted replies (4 ERROR, 2 NO_ERROR, 2 UNKNOWN) and four technical failures.
These counts are admission outcomes, not evidence of semantic correctness.

The 16 fully parsed WHOLE_MOVE replies contain 22 norm assessments, 22 policy
quotes and 143 evidence quotes. An exhaustive check of every quote, including
entries after the first rejection, found **8 invalid policy quotes, 14 invalid
evidence quotes, and 13 invalid native-actor labels**. The two unfinished replies
are excluded from these quote totals; their prefixes visibly contain further
altered quotes, but do not form complete admissible assessment objects.

There are 22 bad quote occurrences, including repetitions. They consist of one
pure whitespace-only mismatch, one exact quote assigned to the wrong source ID,
and 20 edits or reconstructions. No translation-only quote mismatch was found
among the complete replies. Actor mismatches are additional failures; two retail
evidence entries fail both their quote and actor checks.

| WHOLE_MOVE row | First recorded failure | Invalid policy quotes | Invalid evidence quotes | Wrong actors |
|---|---|---:|---:|---:|
| `airline__9::t6` | EVIDENCE_LITERAL_QUOTE_INVALID | 1 | 2 | 0 |
| telecom network-preference row ending `::t7` | POLICY_LITERAL_QUOTE_INVALID | 2 | 5 | 0 |
| telecom permissions row ending `::t15` | POLICY_LITERAL_QUOTE_INVALID | 1 | 2 | 0 |
| `airline__23::t10` | INVALID_OR_UNFINISHED_JSON | not fully parseable | not fully parseable | not fully parseable |
| `retail__27::t10` | POLICY_LITERAL_QUOTE_INVALID | 2 | 4 | 9 |
| `banking_knowledge__task_057::t2` | INVALID_OR_UNFINISHED_JSON | not fully parseable | not fully parseable | not fully parseable |
| `wm_03_ae` | POLICY_LITERAL_QUOTE_INVALID | 1 | 0 | 0 |
| `wm_04_c6` | EVIDENCE_LITERAL_QUOTE_INVALID | 0 | 1 | 0 |
| `wm_05_2a` | POLICY_LITERAL_QUOTE_INVALID | 1 | 0 | 0 |
| `wm_06_82` | EVIDENCE_REFERENCE_OR_ACTOR_INVALID | 0 | 0 | 4 |

All other complete WHOLE_MOVE replies have zero mismatches in these three checks.

## Exact mismatch inventory

Paths below use zero-based `r` (target review), `n` (norm), and evidence index.
`support`, `app`, `exception`, `conditionN`, and `prerequisiteN` identify the
corresponding evidence arrays. The saved decisions retain the original strings.

* Airline 9: `r0.n0.support[0]` and `r0.n0.condition0[0]` insert an ellipsis into
  the policy sentence. `r1.n0.policy` joins two original sentences in reversed
  order and adds punctuation. These are reconstructed quotes, not whitespace.
* Telecom `::t7`: both `r0.n0.policy` and `r0.n1.policy` combine selected policy
  sections with intervening material removed. `r0.n0.support[0]` changes quoting
  around 2G and removes the example tail; `support[2]` changes double quotes to
  single quotes around the Wi-Fi status; `support[3]` rewrites the permissions
  instruction and tool arguments. `condition0[0]` synthesizes a tool description;
  `condition1[0]` rewrites the simultaneous response/tool-call prohibition.
* Telecom `::t15`: `r0.n0.policy` splices headings and nonadjacent paragraphs.
  `condition1[0]` deletes material inside the user's Russian sentence.
  `prerequisite0[1]` assigns the exact result quote to **h72**, the call; the
  original quote belongs to **h73**, its result. Admission did not remap it.
* Retail: `r0.n0.policy` and `r1.n0.policy` replace original `##` headings with
  bold headings and colons, while also changing whitespace. `r0.n0.support[0]`
  is the sole pure whitespace mismatch: the original declaration wraps its lines.
  `r1.n0.support[0]` reconstructs the exchange tool description.
  `r1.n0.app[3]` and `condition1[0]` invent a shortened JSON object by deleting
  fields and neighboring variants; that serialized object is not an original
  substring. Actors are `system` instead of native `assistant` at
  `r0.n0.app[0]`, `app[3]`, `condition0[0]`, `condition2[0]`, and
  `r1.n0.app[0]`, `app[3]`, `condition0[0]`, `condition1[0]`, `condition3[0]`.
* `wm_03_ae`: `r0.n0.policy` inserts Markdown emphasis around `requires`.
* `wm_04_c6`: `r0.n0.condition0[1]` quotes `sealed=true`, whereas the result
  literally contains JSON `"sealed":true`. This is value reformatting.
* `wm_05_2a`: `r0.n0.policy` inserts Markdown emphasis around the restriction.
* `wm_06_82`: `r0.n0.support[1]`, `app[0]`, `condition0[0]`, and
  `prerequisite0[0]` label h2 `system`; its native actor is `assistant`.

## Truncation is separate from citation failure

Both unfinished real responses have provider `finish_reason=length` and exactly
3,600 completion tokens. Airline 23 produces 16,990 raw characters; target review
IDs t0, t1 and t2 appear, but native t3 never appears before the stream stops
inside t2's payment assessment. Banking 057 produces 17,409 raw characters and
starts its sole native target t0, but stops inside another exception assessment.
One native target can therefore exceed the cap too; target count alone is not a
sufficient output-size estimate. Neither response was repaired or partially
aggregated. This is output truncation, not omitted input context.

## Raw semantic hypotheses do not become admitted scores

The rejected replies are useful for diagnosing reasoning, but remain rejected.
The following observations compare original sources and the evaluation-only cause
sidecar; they do not recompute decisions under weaker admission.

* Airline 9 accuses cancellation t0 of lacking confirmation despite prior user
  confirmation. Its later-target transfer accusation approaches the annotated
  premature-escalation issue, but frames the need as confirmation that a flight
  was flown instead of establishing the available-check versus human-only claim.
  A positive-looking conclusion contains both relevant and irrelevant causes.
* Telecom `::t7` calls the current diagnostic tool valid and instead accuses it of
  failing to perform the entire troubleshooting procedure. The annotated issue
  is actor/capability scope: the action is described as one the user performs.
  Repairing quotations would not recover that missing distinction.
* Telecom `::t15` describes the permission advice as compliant, consistent with
  the negative label; its quotations and source binding still fail independently.
* Airline 23's unfinished prefix accuses missing immediate/per-action
  confirmations despite a prior confirmed plan, and sequential calls without
  intervening interaction. It does not establish the annotated nested required
  payment-field omissions. Mechanical detection remains a separately disclosed
  source-declaration cause; it does not validate these model accusations.
* Retail declares each operation individually satisfied, missing the quoted
  once-only return-or-exchange constraint across both targets on the same order.
  Reviewing all target IDs is necessary but does not prove interaction analysis.
* Banking 057's unfinished prefix mostly treats the verification proposal as
  compliant, consistent with the negative label. It also invents a quoted
  Russian sentence and adds explanatory wrappers inside its supposed policy
  quote. Its final whole-move assessment does not exist.
* `wm_04_c6` invents same-turn re-verification and marks a violation despite
  historical authoritative sealing confirmation. Its own open questions admit
  unresolved scope. Citation repair alone could expose an erroneous accusation.
* `wm_05_e7` similarly invents real-time/session re-verification. The admitted
  result is UNKNOWN because its accusatory assessment is typed PERMIT.
* `wm_05_2a` recognizes the credential/node mismatch but also types a restrictive
  "may ... only with" norm as PERMIT. Fixing only Markdown copying would leave
  this typed assessment unable to ground ERROR under the unchanged aggregator.

## Generic next-phase design hypotheses

Keep phase-v1 artifacts and its strict failures intact. A new frozen contract can
test whether **code-owned source references and literal rendering** reduce this
avoidable copying burden:

1. Give the model stable, validated source/span or atom IDs. Code renders literal
   quotes and native actors from the original SourceStore after the model selects
   IDs. Do not ask it to reproduce actor labels and long original strings already
   held by code. Invalid IDs remain failures; never silently remap h72 to h73.
2. Preserve heading scope, surrounding qualifiers and exceptions when supplying
   policy atoms. Splitting into sentence IDs must not imply each sentence is an
   independent complete norm. Exact span selection and code-owned quotations
   still prove addressing only, not applicability or interpretation.
3. Reuse a cited-fact table across conditions instead of duplicating the same
   quote in support, applicability and prerequisite arrays. Distinguish a model
   fact from the original literal text; JSON value renderings must not masquerade
   as literal source quotations. This may reduce output size but needs measurement.
4. Retain one whole-move inventory and explicit cross-target interaction checks.
   Do not fit the output limit by dropping later targets or silently accepting a
   complete prefix. Freeze an output allowance and compact schema before spending
   a new budget; the current cap also fails on a single prose target.
5. Independently test semantic contrasts for prior versus fresh confirmation,
   user versus assistant actions, proposal versus execution, compound operations,
   and restrictive "may only if" versus unconditional permission. Better citation
   transport does not solve these interpretation errors.

These are prospective general mechanisms, with no row, tool-name, string, or
domain exceptions. They require a new protocol and separate evaluation. Neither
literal reference validity nor a repaired formatting surface establishes that an
underlying rejected semantic assessment was correct.
