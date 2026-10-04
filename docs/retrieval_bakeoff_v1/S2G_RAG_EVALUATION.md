# S2G-inspired evidence-gap experiment

**OFFICIAL_S2G_NOT_EXECUTED.** The official pinned repository requires a local
sufficiency base model and LoRA even when its final answer uses an API. We did
not download weights or train. Its sentence selector also truncates to forty
sentences and six selected sentences, unlike this original-span contract. The
executed method is **S2G_INSPIRED_API_BASED**, not a reproduction of its trained
judge or published benchmark scores. See [upstream code audit](REPOSITORY_REUSE.md).

Three frozen development cases were chosen before any model outputs: missed
Silver and bank57 packets in different domains, and complete positive retail106
as a third-domain control. This small known set is not a holdout. S0 uses B1 at
twelve reads; S1 extends the eight-read seed through qualified deterministic
dependencies; S2 asks one API gap question and admits at most four new reads.
Every arm has the same twelve-read and 20,000 source-record UTF-8 bound. A cap
is an allowance, so unused reads are reported. Full current moves are mandatory.
The seed is retained, repeated reads are deduplicated, and invalid plans stop
before extra reads or final review. No retries or provider changes occurred.

| Case / arm | Reads | Source-record UTF-8 bound | Newly covered distinct required spans vs seed | Complete known alternative | Raw / admitted verdict |
|---|---:|---:|---:|---|---|
| Silver S0 | 12 | 17,693 | 1 | no | ERROR / null, actor invalid |
| Silver S1 | 8 | 12,646 | 0 | no | NO_ERROR / NO_ERROR, reused impact |
| Silver S2 | 12 | 16,100 | 2 | no | NO_ERROR / null, actor invalid |
| Bank57 S0 | 10 | 19,907 | 0 | no | NO_ERROR / null, actor invalid |
| Bank57 S1 | 11 | 19,311 | 0 | no | NO_ERROR / null, actor invalid |
| Bank57 S2 | 11 | 19,832 | 0 | no | UNKNOWN / UNKNOWN |
| Retail106 S0 | 12 | 19,725 | 0 | yes | UNKNOWN / UNKNOWN |
| Retail106 S1 | 8 | 16,043 | 0 | yes | ERROR / ERROR |
| Retail106 S2 | seed unchanged | no added packet | 0 executed | invalid plan | no final review / null |

Distinct necessary spans are deduplicated across reference categories. Silver
S2 adds the real reservation h7 and profile h8, each with its qualified native
call partner: four new full reads, two necessary factual spans. S0 adds only
one of these required spans. History recall rises from seed 1/5 to S0 2/5 and
S2 3/5; the known negative reference still remains incomplete. No controller
declared `sufficient=true`; observed false-sufficiency claims are 0/3, not proof
the controller can certify sufficiency. All two valid S2 plans retain the seed;
Retail's invalid plan adds zero reads. Candidate repeat proposals and excess
queries are retained in `s2g_source_metrics.json`; there are no repeated executed
full reads. Silver proposes no previously read candidate; bank proposes already
read q22 once, which is deduplicated. The invalid Retail plan's repeated seed
proposals are rejected before any execution.

The causal audit separates concrete gaps from false scope:

* Silver's two requested facts are concrete and actually missing. S2 recovers
  native Silver/economy/two-passenger evidence and the correct core arithmetic.
  The final model marks assistant receipts as system, so the useful retrieval
  result does not become an admitted operational decision.
* Bank's four questions focus on account classes and later opening/compliance
  procedures; current identification is not opening. It adds three windows but
  zero independently annotated necessary facts. Its final UNKNOWN is admitted;
  under UNKNOWN=0 the original negative binary label matches, but this is
  an internal abstention driven mostly by future/wrong-savings prerequisites,
  rather than an established NO_ERROR or a valid current-evidence gap.
* Retail's first gap proposes declaration `d4` in the readable-source catalog.
  Atomic namespace validation rejects the whole plan. The remaining questions
  concern later exchange/consent although the original user asks return and the
  current move is name/ZIP lookup. The controller misses ZIP fabrication.

Across ten raw gap questions, the independent audit grades only Silver's two
as materially necessary for the current target (2/10). Bank's four and Retail's
four introduce future-stage, wrong-subtype or unsupported prerequisite scope.
They are phrased concretely, but concreteness alone does not establish relevance.

Retail S1's apparently improved ERROR is **the correct binary label for the
wrong cause**: it accepts ZIP 3019 as supplied and changes the declared fallback
`email not found OR cannot remember email` into an extra obligation despite an
actual failed email lookup. Thus raw S1 labels matching all three original labels
do not establish a successful causal recovery. Its bank response also fails
actor admission. Retail S0 UNKNOWN creates a false negative when projected to 0
despite a complete known positive evidence alternative. Technical nulls are
never projected to negative labels or silently included in F1.

S2 consumes 3 gap calls totaling **24,451 tokens**, plus 2 final calls totaling
12,026 tokens: **36,477 tokens / 5 calls**. No final Retail call is spent. Relative
to the reused eight-read Silver review alone, the added gap+final costs 12,247
tokens and buys two required facts, but no admitted decision or binary repair.
Against S0 Silver, S2 costs 5,952 more tokens and still has actor non-admission.
These are narrow per-case observations, not a general cost-per-F1 estimate.

S0 uses 3 new calls / 19,595 tokens; S1 uses 2 new calls / 12,173 tokens because
Silver reuses impact. Total S2G phase: **10 new calls / 68,245 tokens**. Global
impact+S2G: **15 calls / 90,419 actual and charged tokens**, zero unknown usage,
below 18/130,000. Source byte bounds differ from complete API prompt/response
usage. The provider/model/settings remain fixed throughout.

Independent code/source audits and zero-HTTP replay reconstruct the two valid
plans, invalid Retail stop, original packets, raw replies, all wire hashes and
admission outcomes. The frozen native-receipt normative-candidate defect limits
the final-review evidence interface; it is preserved and disclosed separately.
No causal effect of fixing it has been measured. The observed targeted factual
recovery warrants a conditional future hypothesis, but these results do not
justify a mandatory S2G controller in Guardian.
