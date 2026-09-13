# Goal v3 isolation experiment v3: full-schema extraction intervention

User authorized this separate experiment after v2 stopped. Historical Goal/Plan
v2 (22/22 UNRESOLVED), isolation v1 and isolation v2 code, inputs, predictions,
gold, freezes, scores and terminal accounting stop remain immutable.

## Hypothesis and scope

Test whether including the FULL existing JSON schema and explicit distinctions
between Boolean flags, Truth strings, arrays and maps makes the external
extractor usable. The exact v2 60-case corpus and behavioral gold are reused
deliberately for a format intervention, not advertised as a new blind holdout.
Gold is not in requests. No semantic correction, new Goal rule, new parser,
confidence selection, top-k, judge or challenger is added. Frozen v2 calculus,
source replay, independent receipt issuer and behavioral scorer are reused.
Policy does not participate. Certificates retain their exact controlled USER
fragment/trusted adapter/local scope; they are not arbitrary-NL or Core proofs.

Multiple material readings remain unranked. UNKNOWN is not FALSE. An independent
violation may be decisive despite unrelated UNKNOWN. Future obligations and
optional helpers must not be promoted to current violations or required plans.

## Changes relative to v2, fixed before any inference

- System prefix embeds the exact full v2 schema (schema hash unchanged), and
  explicitly describes JSON types. A new version/prompt hash identifies it.
- Invalid proposals retain ONLY completion hash and value-free code/path/type
  diagnostics. No raw invalid values, model-created keys or provider error body
  are logged. Diagnostics never repair the proposal or trigger semantic retry.
- Known timeout/429/5xx/connection failures without usage no longer abort the
  stage. Capture UNKNOWN, report unknown billing, and move to the next case
  after at most one identical-payload retry. Missing successful usage or an
  abandoned result still stops as USAGE_UNVERIFIABLE, with no automatic resend.
- Retry backoff is 60 seconds, compared to v2's 2 seconds. This is a transport
  intervention, separately declared, not evidence of better Goal semantics.
- Output allowance is 4096, previously 2048; no CoT/explanation requested.
  Total-token ceilings are NOT enforced per user instruction. Available usage
  is not represented as complete billing when failed requests omit usage.

## Fixed inference and admission rules

Groq qwen/qwen3.8-27b; OpenAI-compatible /openai/v1; JSON Object Mode auto,
temperature 0; 180-second timeout; no explicit reasoning parameter; client
retries disabled. Serial one-case requests, concurrency 1, 30-second interval.
One semantic inference/case, maximum one identical request retry on the four
transport categories above. No retry for invalid JSON/schema/semantic output.
Repair only exact JSON or exact JSON/plain fence, value-preserving.
No experimental calls before source/input/gold/prompt/config/gate freeze.
Stable prefix, no caching guarantee. Key is loaded from an explicit env file;
never written to experiment artifacts.

S1 uses the same preregistered 12 distinct minimal-pair representatives as v2.
Admission requires schema-valid >=10/12, scoped status-correct >=6/12, zero
incorrect definitive proposals and an optimistic maximum >=22/24 correct
core pairs. Evaluate only after the complete S1 seal and before S2. Accounting
integrity stops remain BUDGET_STOP/INCOMPLETE, not semantic REJECT_EARLY.
S2 is the remaining 36 cases; all unchanged v2 CORE_GATES must pass on the
complete 48-case/24-pair core for S3. S3 is 12 composition/NL stress cases;
behavioral >=80% is the readiness signal, not rewriting the core verdict.
Maximum 60 semantic cases/120 physical requests. No further cases after a
frozen rejection. No prompt/gold/scorer/gate changes during inference.

Physical admission precedes transport. Exclusive PID locks protect live runs.
Missing result on resume is UNKNOWN_NO_AUTOMATIC_RETRY. Seal the exact attempted
prefix before gold. Verify physical request/result lineage, all current/prior
seals and input/source hashes before offline scoring and admission. Do not
resume solely because an observation timeout expired. One runner batch, no
per-request agent polling. Use waiting time for offline work only.

## Commands and final evidence

With PYTHONPATH=src: scripts/evaluate_goal_v3_isolation_v3.py accepts freeze,
verify, batch --stage S1|S2|S3 --env-file <explicit path>, and score --stage.
Commit all sources first; commit complete freeze before the first request.
Output namespace goal_v3_isolation_v3_ is disjoint from v2.
Report exact evaluated commit/version/hashes, all 14 requested report items
and Q1–Q8, safety AND certified coverage, per-family/pair/behavioral metrics,
attempted/NOT_RUN cases, physical requests/retries/deliveries and available
tokens vs missing usage/cost. Do not claim a competition score gain, general
USER language or whole-Core readiness from controlled fixtures.
If KEEP, move to composition testing, not another local Goal optimization.
