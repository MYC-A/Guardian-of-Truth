# Architecture decision

Keep the existing source store, finite evidence graph, exact native fact checker,
typed joins, three-valued logic and durable cache infrastructure. Retain a
source-addressed contextual baseline as the comparison floor for future research.
Reject promotion of the implemented A2/A3 local compiler, the blanket temporal
guard and any claim that code-owned IDs certify semantic correctness. No new
production decision path is installed.

This research produced reproducible negative results and isolated failure classes.
It did **not** demonstrate the requested general improvement in understanding
arbitrary policy. Gemma's contextual arm is more useful than the failed formal
arms, but still gives false ERROR for unresolved entity checks and NO_ERROR for
unknown effects. Its better score is also not an isolated architecture comparison
against Mistral formal arms.

## Mechanism decisions

| Idea | Decision | Measured basis |
|---|---|---|
| Original-source access and exact-hash cache | KEEP | Seven offline phases reproduce saved predictions and ledgers; no rewritten sources or retry masking |
| Code-owned source IDs and schema visibility | KEEP for address/transport plumbing | Provider adaptation admits A0; addresses are verifiable, meaning is not |
| Contextual A0 as research baseline | KEEP, shadow only | Gemma 25/32 and new families 11/16; fewer calls than layered pipeline; six false ERROR across these 48 cases |
| This delayed local formula contract (A2) | REJECT for promotion | 14 received Mistral cases all abstain at admission; two Gemma capability cases fail the same source-role rule |
| Reverse-source discovery (A3) as default extra pass | REJECT in this pilot | Zero new required source IDs in received paired discovery; no verdict gain; common-subset tokens 74,912 vs A2 48,749 |
| Late formalization as a general research hypothesis | NEEDS_MORE_EVIDENCE | Timing, contract shape and ID wire are confounded; no successfully admitted heldout local programs |
| Source-ID early graph | NEEDS_MORE_EVIDENCE | Address admission succeeds in initial inventory, but 429 prevents any complete control pipeline |
| Joint policy/tool interpretation without generated dictionary | NEEDS_MORE_EVIDENCE | Full packet reduces neither all role errors nor opaque-effect errors; no isolated A4 ablation |
| Set-sufficiency search beyond existing WITNESS | NEEDS_MORE_EVIDENCE | No successful local extraction to test retrieval; structural relevance audit alone cannot establish benefit |
| Blanket post-target native-source veto | REJECT | Prospective 11/16 → 10/16, one true ERROR lost on explicitly immutable state |
| Violation-query relevance pruning | NEEDS_MORE_EVIDENCE | Six of 54 supplied assignments over-abstain; semantic extraction and whole-policy coverage not solved |
| Automatic semantic repair or model voting | REJECT as untested substitution | No experiment establishes faithful repairs; correlated candidate agreement is not evidence of truth |

## Answers to the twelve research questions

1. **Is early full formalization an architectural bottleneck rather than one
   model's problem?** Not established. Historical System V2 gold S1 increases
   exact correctness from 10/20 to 17/20, localizing Step 1 for that protocol.
   Current A1 and A2 both abstain; A2 fails mostly on the new contract. The early
   source-ID control is interrupted, and Gemma local lowering fails the same
   role rule on two cases. More than one model can fail a difficult contract;
   that does not prove all early formalization inferior.

2. **Why did action inventories and bidirectional attempts get worse?** The
   historical audit identifies lost shared predicates, dependencies and formula
   scope from action-local decomposition. Two invented programs agreeing does
   not recover meaning. In V4 the forward list is not the reverse input: reverse
   rereads full original sources. Yet its source selections add no required IDs
   and its lowerer retains the same failures. Extra inference adds cost without
   a new successful evidence mechanism.

3. **How does lazy formalization fix these errors, or why does it not?** A2
   discovers policy sections before generating target-specific trees and retains
   original context. This prevents early source exclusion in the measured
   discovery receipts. It does not eliminate tree/policy-role or witness-path
   mistakes: every received primary lowering fails. A semantic hypothesis still
   must be lowered consistently; postponing that obligation is insufficient.

4. **Can an independent Target→Policy pass recover an omitted norm?** Possible
   but unproven here. Thirteen received reverse discoveries add no gold-required
   IDs. Forward already selected required source groups in these receipts; this
   is not a hard missing-norm challenge. Any future claim needs cases where a
   forward omission is observed and reverse recovers its actual meaning.

5. **Can coverage improve without a complete formula?** Source coverage can be
   represented that way: 16 received forward discoveries select all required
   source groups. That is weaker than norm coverage; selection cannot establish
   Boolean structure, exception scope or unstated completeness. Semantic
   NormRecall has not been independently measured in this pilot.

6. **Does joint policy/tool grounding beat independent dictionaries?** Insufficient
   evidence. A0 and the A2 lowerer see the policy and full tool descriptions
   together; no A4-vs-dictionary isolated trial was completed. Gemma matches
   broad effect labels 30/32 but infers an opaque publication effect and later
   fabricates disposal under an opaque declaration. A readable tool name still
   biases interpretation despite explicit description authority.

7. **Can subjects, objects, parameters and results be bound for unknown tools?**
   Native source IDs, typed JSON comparisons and parent joins work in targeted
   tests, including mismatch/absence/chronology rejection. End-to-end general
   semantic binding is not established: original and prospective contextual
   entity swaps cause five false ERROR decisions. A2 never reaches successful
   full-auto binding evaluation. Exact equality does not choose the right role.

8. **Does set-sufficiency retrieval help beyond WITNESS?** No measured gain.
   Original A1 admits 21 unique witnesses, yet lacks usable decisions. The
   54-assignment diagnostic exposes six irrelevant-gap abstentions after an
   interpretation is supplied; it is not a retrieval experiment or evidence of
   missing-norm recovery. Do not add a new search engine before fixing extraction.

9. **Can contextual baseline win on quality and cost?** On the 13 common executed
   Mistral cases, A0 is 4/13 vs A2/A3 2/13 at 16,939 vs 48,749/74,912 tokens;
   A0 also produces eight false ERRORs. Adapted Gemma A0 is 25/32 and prospectively
   11/16 for 31+16 requests. These support retaining A0 as a floor, not declaring
   safe automatic enforcement or a universal architecture winner.

10. **Which inputs cannot be resolved without another source?** Opaque effect
    declarations, missing observations for the target entity, missing prior
    authorization and claims without matching successful receipts. Wrong-entity
    observations cannot be rebound by guesswork; a late approval cannot authorize
    an earlier event. A later immutable-state observation is different because
    the policy explicitly supplies the temporal relation.

11. **How can uncertainty avoid becoming false NO_ERROR or ERROR?** Preserve
    UNKNOWN on unavailable/irrelevant witnesses; require explicit negative
    evidence to establish FALSE; separate applicability/effect uncertainty from
    evidence absence. Source admission and typed joins enforce part of this in
    code. They do not yet enforce model meaning. The failed blanket temporal
    guard shows why syntax-only vetoes cannot cover every semantic relation.

12. **What is the smallest architecture preserving the measured advantages?**
    For further shadow research: original sources + full catalogue, code-issued
    addresses, one contextual source-referenced hypothesis, and existing exact
    native checks only for explicitly supplied typed relations. Durable cache
    and UNKNOWN are mandatory. Do not require a full early inventory, add reverse
    passes by default, or install a blanket temporal cutoff. This is a research
    direction, not a newly validated production composition; the existing
    production system is unchanged.

## Next experiments for unresolved questions

1. Replace generated tree paths with code-owned atomic relation slots in a
   separately sealed development experiment. Compare the identical model,
   original sources and token ceiling against A0 and an early source-ID graph.
   Include same-role entity swaps, opaque tool names, missing observations,
   explicit negatives and two temporal semantics (authorization vs immutable
   state). Require admitted native relations and fewer false ERRORs before
   allocating a new family holdout. This addresses the observed lowering
   failures without another solver or a repair-voting loop.

2. Only after successful grounding, test independent reverse recovery on
   deliberately observed forward omissions and annotate actual norm/exception
   meaning, not just selected sections. Compare its marginal recovered facts
   and cost against one richer contextual pass. Stop if extra calls merely
   repeat selected sources or worsen false accusations.

3. If correctly grounded programs still over-abstain, separately validate
   violation-query relevance on existing REQUIRE/FORBID/PERMIT, OR/NOT, scoped
   exceptions and ordering contracts. The six structural differences are a
   hypothesis to investigate, not authorization to reinterpret satisfied policy
   as a complete NO_ERROR certificate.

Each requires a fresh protocol and untouched holdout. The current work ends with
the negative evidence archived and replayable; it does not restart failed quota
requests, retune the disclosed reserve or claim a general solution.
