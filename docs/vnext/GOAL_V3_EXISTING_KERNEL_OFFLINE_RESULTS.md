# Existing Goal v3 kernel: sealed offline diagnostic

Evaluated implementation origin: `48b84e3875b960d43956576735d543e8c4e5917b`.
Runner and full source freeze commit: `ab0c3b9` (full hash in
`outputs/vnext/goal_v3_fixture_offline_v1_freeze.json`). Prompt version:
`NONE_OFFLINE`; model schema version: `NONE_OFFLINE`. Provider/model: none.
No Policy parser, Policy verdict or external LLM call participates.

The 36 earlier controlled shipment-fixture cases were split into a gold-free
source input file, source premises and a separate frozen gold file. The runner
read only source/premises to generate all 36 predictions, wrote a complete
prediction seal, then joined gold in a separate scoring phase. Frozen source,
input/premise/gold and seal hashes are recorded in the machine artifacts.
This is observed development, not the new 60-case Goal-only experiment.

| Result | Count |
| --- | ---: |
| Exact expected status | 36/36 |
| Alignment where annotated | 10/10 |
| PROVED_ERROR | 15 |
| PROVED_NO_ERROR | 10 |
| UNRESOLVED | 9 |
| INCONSISTENT | 2 |
| Definitive certificates validated at inference | 25/25 |
| External requests / reported tokens | 0 / 0 |

The result supports the **structured contract kernel** on this pinned fixture:
it keeps optional reads optional, enforces explicit prerequisites and due dates,
retains unknown guard results, and lets an independent forbidden-attempt witness
survive an unrelated unknown. It does not show that a model can extract those
rules from a fresh USER request, that another domain is covered, or that a
definitive Guardian Core decision is valid in an external trajectory. The
fixture supplies exact authoritative SYSTEM contract meanings through a pinned
adapter; the v3 kernel has no general NL frontend. Its strong fixture score
must not be presented as Goal-only semantic generalization or an improvement
over v2 on the external 22-case set.

The next isolated experiment requires 24 frozen minimal pairs plus 12 stress
cases with USER-task constraints only. If a missing frontend is implemented
from the recorded v3 design, it must receive a new source/prompt/schema freeze
and a separate result. Policy remains out of that experiment.
