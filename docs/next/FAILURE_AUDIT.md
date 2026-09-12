# Failure audit

## Internal development sample

V5.3, X4, and X5 all produce TP=12, FP=0, FN=11, TN=23. The principal failure
is therefore missed positives, not observed false accusation. The 11 FN were
audited into:

- false refusal / premature escalation: 3;
- authorization or precondition semantics: 2;
- fabricated or ungrounded argument: 2;
- temporal or derived value: 1;
- already available fact falsely requested: 1;
- invalid state-transition arguments: 1;
- repeated failed action without new evidence: 1.

This distribution explains why schema regexes alone cannot close the gap. The
missing information lies mostly in policy meaning, effects, entity/freshness,
and claim-to-evidence relations.

## Representation failures

- P0 recognizes only 5/523 unique policy segments. UNKNOWN is preserved rather
  than widened into a rule.
- C0 covers only 5.33% of audited spans. A negative decision from uncovered
  response text would be unsound.
- T0 exposes schemas but zero trusted effects. A tool name or parameter shape
  cannot prove a state transition.
- T1 has useful evidence for seven tools, but no confirmed-no-effect records;
  a failed call remains symmetric unless a contract proves otherwise.
- Typed P2 can express modality, conditions, exceptions, time, identity, and
  quantification, but the current IR-to-benchmark projection lacks some relation
  and feature dimensions. On all 16 frozen cases it validated only 2 responses
  and yielded no exact semantic hit; P1 yielded 1/16 and P0 yielded 6/16.

## Model and transport failures

- X1 exceeded the provider request limit on a representative long row.
- Query-conditioned compaction reduced X3 input enough for transport, but exact
  source validation rejected the returned citations. Transport success is not
  counted as a valid prediction.
- Groq C1 was only partially schema-valid; OpenRouter claim output was often
  truncated/slow; Gemini, NVIDIA, Mistral, and Cerebras did not meet the role
  reliability gate.
- One NVIDIA `gpt` credential was exposed when a code-sample file was mistaken
  for a raw key and the HTTP library echoed an invalid header in an exception.
  That credential must be revoked and was excluded from all probes.

## External label mismatch

The selected ATFD/tau records provide trajectory reward/outcome, not a localized
Guardian error turn. X0/X5 both predict no violation for all 144 trajectories;
against the proxy this gives 83 FN and 61 TN. The result shows that current exact
checks do not detect general task failure, but it does not show that all 83 are
Guardian truthfulness failures. Pooling these counts with internal turn labels
would be invalid.

ToolSandbox/BFCL contain useful independent schemas but no compatible error
labels. AgentDojo's pinned repository lacks recorded TraceLogger results.

## Stop conditions applied

The candidate is rejected for production if it loses an incumbent exact
positive, creates a metamorphic hard violation, treats UNKNOWN as FALSE,
infers effects from names/schemas, treats failed as no-effect, reads labels in a
model arm, or changes after the frozen external label join. No such regression
was found in 511 tests. X6 was not built because X5 showed no conditional gain;
adding complexity would not be experimentally justified.
