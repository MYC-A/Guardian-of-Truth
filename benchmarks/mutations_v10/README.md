# V10 mutation contracts

The generator never reads dataset labels. It preserves the original inputs and
creates separate copies with recorded deltas, source hashes and a fixed seed.

## Implemented constructions

- `ARG_IDENTIFIER`: a new, syntactically valid UUID absent from the context,
  only when the input declaration explicitly supplies `[format: uuid]`.
  String field names are never treated as identifier schemas.
- `STATE_CONDITION`: true/false counterparts for a DECISIVE compiled condition,
  including exception activation. Only uniquely resolved observations qualify.
  Every other prerequisite must be resolved and the positive branch must remain
  a violation after checking all exception groups.
- `KNOWN_ANSWER`: insert a typed answer into the latest user event, conditional
  on an input-bound validated request frame. No frames are fabricated from
  case names or the desired label.
- `NEGATIVE_CONTROL`: render a native JSON payload with different whitespace
  and key order. Code verifies that all typed events, roles, names, values,
  chronology and original non-native text remain identical.

## Label scope

`NO_FINDING` applies only to the named rule, never to the whole response.
Positive compiled-rule labels are conditional on the rule being faithful to
the original policy. Three agreeing proposals establish reproducibility;
they do not establish independent semantic gold. Request-frame labels also
carry their semantic assumption explicitly. Negative controls assert equality
with their original case decision; they are not automatically negative cases.

Expectations are stored separately from model inputs. The scorer must preserve
these distinctions and group contrasts by original case and rule. It must not
turn missing whole-case labels into zero or pool contract recall with public46.

## Readiness

The selector requests eight examples of each type for each policy hash
(128 for four hashes). It records deficits and rejects an incomplete suite as
`PREPARED_INCOMPLETE_NOT_FULL_BENCHMARK`, without duplicating rows to fill it.
Actual tables and validated request frames are dependencies of generation.
The current source catalogs provide no explicit ID formats; the identifier
category therefore cannot honestly be populated from these catalogs yet.

Formatting controls do not prove robustness to textual paraphrases or shuffled
trajectories. Events are never called independent merely because tool names or
entity values differ. These original requested controls remain unimplemented
until their semantic/causal equivalence can be established.

No model inference is performed by this generator. The prepared draft is not
the final frozen benchmark and must not be scored as a completed 120-case run.
