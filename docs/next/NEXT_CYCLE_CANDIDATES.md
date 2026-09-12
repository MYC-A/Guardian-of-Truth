# Next-cycle candidates

Priority is determined by the measured bottlenecks, not by architectural
novelty.

1. Typed-citation repair without semantic widening. Use a second constrained
   pass that may only select exact spans from an enumerated source table. Gate it
   on citation validity, not label accuracy. Expected value: convert current X3
   transport successes into auditable decisions.
2. Blind claim coverage benchmark. Freeze response-only span annotations across
   domains, then compare C0/C1/C2 on claim recall, type accuracy, and unsupported
   assertion precision. Do not evaluate only the nine patterns C0 already finds.
3. Policy IR v2 driven by the frozen 16-case benchmark. Typed IR v1 is rejected:
   P2 scored 0/16 exact versus P1 1/16 and P0 6/16. Add relation and feature
   fields only where the current projection is structurally unable to represent
   gold. Run P1/P2 with a provider that first passes a repeated reliability gate;
   only then consider P4 candidate generation or P5 judging.
4. Tool-effect ceiling test. Expand T1 with independent documentation/tests for
   the tools appearing in audited false negatives, then measure conditional
   downstream gain. Build T2/T3 only if T1 moves end-to-end recall.
5. Create a turn-localized external set. Sample assistant turns before labels,
   annotate policy violation and responsible source span with two annotators and
   adjudication, group by trajectory/policy/tool/domain, and never tune on the
   test partition.
6. Provider reliability pre-gate. Require repeated schema-valid success and a
   latency ceiling before spending benchmark labels. Groq remains the first
   candidate; NVIDIA may be evaluated only as a slow path. Rotate the exposed
   NVIDIA GPT key before any use.

RLM-style recursive context is not the next bottleneck. L2 exhaustive
compile-once already preserves long-policy evidence; the current problem is
semantic correctness and typed citation reliability. A future RLM layer should
operate over immutable policy/evidence IDs, emit only new evidence queries, and
stop when no new ledger fact is added.

Promotion gate for any next-cycle arm:

- frozen predictions before labels;
- no loss of incumbent exact positives;
- zero hard metamorphic regressions;
- positive paired recall/F1 delta with confidence interval;
- acceptable FP/confident-wrong tail on independent compatible labels;
- reported coverage, abstention, latency, errors, tokens, and cost.
