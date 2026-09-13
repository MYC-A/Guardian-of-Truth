# Goal v3 isolation v2 — offline protocol draft, not frozen

**Status: design only. No v2 model request is authorized by this document.**
Goal v3 isolation v1 remains immutable: its S1 gate admitted S2, but S2 was
not run after a post-hoc, sealed 12/24 pair-score ceiling and unexpectedly
high provider-reported token usage. This draft is a separate hypothesis and
must not be described as preregistered until benchmark, implementation,
prompt/schema, scorer, gates and provider configuration are committed and
hashed before the first v2 request.
The standalone pure gate prototype is
`src/guardian_truth/vnext/goal_v3_isolation_stage_gates_v2.py`; it is tested
offline but **not wired to a v2 runner or frozen**. It checks pair-gate
reachability, stage usability and a fail-closed reported-token circuit after
each captured case; one oversized provider response can still overshoot the
ceiling, so this is not a hard billing cap.
The separate typed calculus prototype is
`src/guardian_truth/vnext/goal_v3_semantics_v2.py`. It keeps alignment
independent of explicit obligations, retains four-valued conflicts, allows
an independent violation to survive irrelevant UNKNOWN, and returns only a
**candidate**, never a certificate. It still needs a trusted USER-text
authority adapter and cannot justify any definitive Core result on its own.
The first source-replay prototype is
`src/guardian_truth/vnext/goal_v3_user_authority_v2.py`. It recognizes only
an exact, single trusted USER-message fragment that literally forbids a
named tool call, binds that name/entity to a versioned current assistant
tool call, and emits a replayable prohibition certificate. It abstains on
paraphrases, exceptions, quotes, multiple messages and mismatched actors.
This can certify a narrow independent ERROR witness, including a forbidden
attempt whose tool outcome is failure. It does **not** prove general goal
alignment, obligations, safe NO_ERROR, or arbitrary natural-language
entailment; those remain outstanding. The caller must supply the actual
trusted transcript/tool catalog, not model-supplied text masquerading as it.
`goal_v3_user_contract_v2.py` now parses a complete USER-contract fragment
with literal desired outcome, allowed tool sets, auxiliary permission,
forbidden attempts, required earlier attempts/true results, fresh-result
conditions and session-end effect obligations. Unknown suffixes, exceptions
and extra messages cause whole-message abstention.
`goal_v3_user_execution_v2.py` binds those rules to source-only event IDs,
entity/provider/version, actor/requestor, freshness and effect contracts.
It retains all eligible boolean results (TRUE/FALSE conflicts become BOTH),
does not make missing guards FALSE, and proves missing attempts only under
an explicitly complete trusted prefix. Alignment needs trusted catalog
`goal_fields` for direct support; USER tool permission alone cannot establish
that a tool produces the desired outcome. These fields are controlled-source
semantics, **not inferred from tool names**. Its results still remain local
candidates: an independent certificate checker and real trace adapter are
not implemented. The new full parser is separate from the first literal
prohibition certificate and does not silently broaden its authority scope.

## Target and failure hypothesis

V1's compact proposal got 12/12 source grounding and alignment in S1, but
only 9/12 scoped statuses, 4/12 exact obligation states, 6/12 exact temporal
states and zero independently certified USER-goal conclusions. Three
separable issues are visible, not merely a need for a longer prompt:

1. `obligation_status` mixed explicit prerequisites/deadlines with goal
   scope or prohibition. The scorer then compared ambiguous enums exactly.
2. Candidate aggregation turned every proposed unknown into global
   `UNRESOLVED`, even if a source-independent judgement about the current
   action did not depend on that unknown.
3. Cited source IDs alone did not prove the authority or meaning of a
   USER-goal rule, nor the actor of the *relevant* history event. Candidate
   definitive statuses were not certificates.

V2 should test whether a **typed, source-grounded Goal contract** can
separate these mechanisms and yield safe, nonzero certified coverage. It must
not ask a model to invent a mandatory plan or treat its own assertion of
necessity as a trusted premise. The proposal may identify candidate USER
spans and event IDs; a deterministic validator must bind any decisive rule
to exact text, tool version/arguments and history semantics. Unsupported
readings remain UNKNOWN. This is `implemented-from-spec`, not a claim that
the existing fixture-only kernel already handles arbitrary USER language.
Merely checking that a cited span exists is **not** proof that the span means
what the model claims. A certificate needs either a deterministic, tested
language fragment with explicit abstention outside it, or another genuinely
trusted source of semantic atoms. Its coverage must be reported as that
fragment's coverage, never as general natural-language proof.

## Proposed field ontology before gold is written

- `alignment`: relation of the **current** action to the desired outcome,
  independent of whether a separate requirement was violated.
- `scope_violation`: explicit USER restriction or independently grounded
  goal incompatibility, with a source span and action witness. It is not an
  `obligation_status` value.
- `obligation`: only an explicit USER prerequisite, guard or deadline;
  `NOT_APPLICABLE` means no such rule applies to the current action.
- `temporal`: whether that obligation is due at the current step; a future
  obligation is not an already violated one.
- `effect`: `CONFIRMED`, `NOT_CONFIRMED` or `UNKNOWN_EFFECT` relative to a
  versioned tool-effect contract. An attempt, free-text intention and failed
  call never imply confirmed effect.
- `unknown`: typed premise ID plus whether that premise is **decisive** for
  the proposed status. An unrelated unknown is retained in evidence but
  does not erase an independent error witness.

The final behavioral scorer should check these *claims* and their supported
action-level consequence, not demand identical internal JSON where two
representations have the same meaning. Every accepted equivalence must be
documented and tested **before** inference. A model's `PROVED_*` string is
always a candidate; only replayable source-and-tool certificates count as
certified resolution. If no general USER-goal certificate path exists at
freeze, the experiment is an extraction diagnostic, not a Goal v3 KEEP test.

## Benchmark and provenance

Use a new 24-pair/12-stress Goal-only corpus across F1–F16, with v1 S1 cases
excluded from evaluation. Keep source inputs, gold, pair mutations, stage
inventory and provenance separately frozen. Record that v1's observed cases
are development data; avoid treating lexical variants of those cases as a
blind holdout. Include ambiguous goals and negative controls where decisive
facts are truly unknown. No Policy field/parser/verdict may enter inference,
gold generation, scoring or Goal certificates.

Each candidate inference is one case/request; no samples, challenger, critic,
LLM judge or error-analysis calls. At most one identical-payload retry on
timeout/429/5xx/connection break. Keep durable request/result capture and
seal all predictions before gold join. Do not send raw secrets into artifacts.

## Predeclared stage and cost decisions to implement before freeze

S1 should again sample one member of 12 different pairs. In addition to the
old transport/schema, scoped-status and unsafe-definitive checks, calculate
the **optimistic frozen core pair bound** at S1: if already failed observed
pair members leave fewer than 22 possible fully correct pairs out of 24,
stop with `REJECT_EARLY` by a genuinely preregistered futility rule. The
behavioral scorer used for this calculation must itself be frozen and
audited for field-equivalence ambiguity first.

Add an ex-ante provider-usage gate at S1: require reported usage to be
present and total reported tokens < 24,000 for the 12 cases; otherwise stop
as `BUDGET_STOP`, distinct from a semantic REJECT. The specific ceiling is a
cost-control assumption, not a measured quality threshold. Pin a maximum
per-request output setting and verify the client serializes it for the
chosen provider, but do **not** assume that setting caps reported reasoning
tokens: v1 reported 58,542 output tokens over 12 calls despite `max_tokens`
512. No cost extrapolation should be called a measured charge.

S2 may run only after S1 passes all frozen gates. S3 only after the 48-case
core passes the original safety and correctness gates **and** a frozen,
nonzero certified-resolution floor. Keep safety and coverage separate;
`KEEP` requires both, plus no dominant architectural failure. Each stage
runs as one batch with no per-request agent polling. If the chosen provider
cannot expose reliable usage or enforce an acceptable budget, select a
different provider **before** freeze or keep the run offline; do not change
provider mid-experiment.

## Provider candidate, not yet frozen or called

The current candidate is Groq's `qwen/qwen3.8-27b` in JSON Object Mode,
using the existing `GROQ_API_KEY` transport path, one request at a time and
`max_completion_tokens` capped in the request. The [official Groq reasoning
reference](https://console.groq.com/docs/reasoning) says this model supports
`reasoning_effort=none`, and the [API reference](https://console.groq.com/docs/api-reference)
currently says `none` is its default. The [official rate-limit page](https://console.groq.com/docs/rate-limits)
lists free-plan limits for the model, but the organization's actual limits
can differ. None of this proves the user's key has access or that reported
usage will be small. V2 must freeze the exact payload and retain the
after-each-case usage circuit; no exploratory model call is allowed before
the complete v2 freeze.

## Outstanding items before v2 can be frozen

Independent certificate replay for the exact USER fragment is implemented
and tested; see [scope and limitations](GOAL_V3_USER_CERTIFICATES_V2.md).
It does not establish arbitrary USER-language authority or real trace
authentication, and cannot by itself qualify v2 for a general Goal-layer KEEP.

The fresh 60-case corpus, authored gold, and tested behavioral scorer are
implemented as drafts; see [benchmark and scoring](GOAL_V3_ISOLATION_V2_BENCHMARK_AND_SCORING.md).
They remain development-aware mechanism tests, not a blind holdout.

Final validator semantics, serialized receipt integration,
provider/model/configuration, full
numeric S2 gates, and token-accounting check are **not yet implemented**.
No v2 API calls should be made until those items are committed, tested and
sealed. The v1 result remains the only measured external Goal-only candidate
evidence so far.
