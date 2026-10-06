"""Guardian v6-fix: mechanical layers with explicit guarantee boundaries.

Every finding separates
  fact      - a structural fact proven by code from the current input (re-checkable: `recheck(packet, finding)`),
  norm      - the norm that would make the fact a violation, with its basis:
              CONTRACT_TEXT (verbatim text of the current input, matched/checked by code) or
              MODEL_EXTRACTION (a model read the policy; quote and type/n consistency checked by code) or NONE,
  status    - MECHANICAL (fact proven AND norm established without unresolved condition/exception) or HYPOTHESIS.
Only MECHANICAL findings may decide ERROR. HYPOTHESIS findings are reported and never change the decision."""
