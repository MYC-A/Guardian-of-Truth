# Original Selector baseline

A imports the unchanged historical `coverage_plan()`. It is supported only for
the two single-call Telecom cases with its original tagged policy interface.
Thirteen of fifteen cases explicitly return `UNSUPPORTED_BASELINE_CASE`, across
all four budgets (52 cells). No unsupported outcome is a semantic UNKNOWN.

At eight reads A covers 2/8 raw development alternatives but only 1/8
operational alternatives, and 0/7 known evaluation alternatives. One raw credit
comes from mandatory current actions/declarations despite an unsupported
selector. On the actual supported subset, A is complete in 1/2 cases and B1 in
0/2. Thus B1's broader availability does not establish better retrieval on the
original interface. A retains its internal eight-read cap even at a twelve-read
allowance. Its complete policy sections and the new methods' explicit windows
are different read units; serialized source cost is also reported.

The fifteen-case eight-read totals are ten retrieved A sources and 50,241
source-record UTF-8 bytes, including mandatory targets/declarations. A's raw
normative recall is 5/28 and history recall 2/52; excluding two independently
identified bank081 declaration-ENUM annotation defects gives normative 3/26.
These sparse cross-domain totals include unsupported cases and are not fair
quality estimates for its supported Telecom interface.

The unchanged local BM25 is a second reusable baseline. With eight reads it
completes 1/8 development and 3/7 known evaluation sets; with twelve, 2/8 and
3/7. Query-equivalent BM25S ranks identically on all fifteen cases in the
separate diagnostic. Neither baseline establishes negative-case completeness:
no tested method completes any of the six negative references at any budget.

See [full comparison](RETRIEVAL_COMPARISON.md), [independent source audit](SOURCE_COVERAGE.md)
and the retained packet matrix. Binary decisions and causes have their own
paired experiment; these are retrieval metrics, not binary F1.
