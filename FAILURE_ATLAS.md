# Failure atlas — 2026-10-01

## 1. Correct quote, wrong governed action

Dev `textile_certification::order::04`: the policy requires a successful
inspection **before commit**. The target retries inspection after failure.
Gemma and the v1 independent reviewer both blame the retry, accurately
quoting a requirement that governs a different action. Quotes alone do
not certify applicability. GP surface and the observation graph do not
automatically solve this relation.

## 2. Permission turned into execution

Codestral `textile_certification::order::00`: the target query atom says
that commit was called. Successful inspection implies this atom in the
translation. Being allowed to perform an action does not establish that
the action was performed. A derived relation can therefore be about the
wrong proposition even when its mapped case label happens to be right.

## 3. OR strengthened into AND

Codestral `lighthouse_maintenance::gate::00` encodes a single
`clearance AND (supervisor OR waiver)` requirement as two ONLY_IF rules.
Together they require both supervisor **and** waiver. The original Horn
backend reports INSUFFICIENT, masking the translation error. Exhaustive
classical reasoning on the same validated IR derives CONTRADICTS for
this allowed case: a stronger backend makes the wrong translation more
confident. The replay is diagnostic, not a promotion to the service.

## 4. Rule text promoted to observed facts

Codestral `municipal_tree_survey::amount::05`: amount=1, observed limit=0.
The policy's conditional text is cited as facts that the bound and
signature conditions hold; the solver derives FOLLOWS. This is a covered
FN under the diagnostic mapping. Ministral also turns commands or
permissions into world facts in other cases.

## 5. Assertion used as its own evidence

Codestral `machine_parts_escrow::latest::05`: the answer's statement
of lacking a verified state is copied into a query fact from `target`.
The backend proves exactly this premise, rather than checking the
statement against independent observations. The runtime marks this
pattern as an unverified, self-sourced query warning; no corrected
translation is invented.

## 6. B notices an omitted error but cannot emit an accepted record

In fault v1, hidden true errors were found semantically, but B used
`policy/history` in `source_refs`. The reused original judge validator
expects actual event IDs. The original review prompt did not expose
that namespace. Invalid reviews conservatively preserved the synthetic
upstream NO_ERROR. V2 supplies the inventory and strict quote fields;
3/4 omitted violations are recovered. The remaining one has an invalid
extra disposition and then an empty technical re-ask response.

## 7. Correct interpretation rejected for non-verbatim emphasis

In fault `stale_state`, v1 quoted `**latest successful**` although the
source has no markdown. Both responses were rejected; the source check
was correct. Removing validation would also admit invented evidence.
V2 produces an accepted literal quote for this case.

## 8. Prior history action blamed as a new target error

Fault `uncertainty_as_claim`: the current answer explicitly says no
matching state is verified. B blames an earlier wrong-ID lookup instead
of identifying a new error in this answer. It remains an FP under the
frozen target-turn labels. B v2 also invents a fresh same-turn inspection
requirement on `wrong_id`, despite a valid matching successful history
result. ID inventories alone do not fix temporal applicability.

## 9. Native input adapter failures are not model failures

FactCG pair tokenization was unlike the authors' prompt; after correction
the same smoke moved 10/15→15/15. MiniCheck's migrated safetensors filename
actually pointed to a PyTorch zip. The corrected loader selects the
original bin and explicit existing cache. Native dev accuracy remains
limited afterward; those measured errors are distinct from load failure.

## 10. API metadata is not generation access

Kimi Code appears in `/models` but generation returned HTTP402. Mistral
Small2603 generation returned HTTP429. No model answer, zero measured
quality. Codestral did answer; an explicit-provider logging bug initially
lost responses after writing them to cache. The regression fix recovered
the identical responses without regenerating them. First erroneous
journals remain preserved.

## 11. Operational failures must stay visible

Oversized input returns UNKNOWN; audit failures are now surfaced. A timed
out HTTP request retains the running worker's slot until real completion.
Backend TimeoutError is not misreported as a still-running request.
The private supervised listener passed real HTTP ERROR/NO_ERROR and
UNKNOWN smoke checks. Cache-hit latency is not full end-to-end latency.

## Limits of these examples

Most are known dev cases or controlled upstream faults. The constructed
family-disjoint bank varies domain vocabulary but repeats four logic
templates. No example here proves arbitrary policy completeness, faithful
action effects, general exception logic, or competition performance.
