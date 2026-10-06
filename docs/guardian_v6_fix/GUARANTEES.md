# v6fix: what each layer proves, and where the proof stops

Every finding = **fact** (checked by code on the current input, re-checkable with `recheck`) + **norm** with a basis:
`CONTRACT_TEXT` (a quoted sentence of this input), `MODEL_EXTRACTION` (a model's reading of a policy line, re-bound to
this input and code-checked) or `NONE`. Only `status=MECHANICAL` decides ERROR; `HYPOTHESIS` is reported, never decisive.

| Finding | Fact (code) | Norm | Decides when | Never decides when |
|---|---|---|---|---|
| S UNDECLARED_TOOL | tool name ∉ catalog re-parsed from the current declarations AND packet coverage says complete | catalog contract (only declared tools exist) | both agree | catalog incomplete/unverified, or declarations do declare the name |
| S REPEAT_AFTER_FAILURE | identical parsed-JSON args, uniquely PAIRED with a permanent failure, nothing in between | NONE | never (HYPOTHESIS) | transient failure, user turn / other call in between, ambiguous pairing, unparseable args |
| P UNSOURCED_REFERENCE | schema-typed reference field (id/identifier, not "new/choose") whose exact value occurs in no user message, tool-result JSON leaf or policy (examples "such as" excluded) of a COMPLETE input | quoted provenance contract whose scope covers the field (names it, or speaks of ids/values/information in general) | contract present + in scope | input incomplete (absence unprovable), no contract (HYPOTHESIS), value-typed/computed/new-id fields, unknown schema, nested JSON-in-string args |
| P NOT_FROM_USER | value of a field NAMED by a "must come from the user" contract occurs in no user message | that contract (quoted) | always when the fact holds | contract about another field |
| F MAX_TOOL_CALLS_PER_TURN / NO_TEXT_WITH_TOOL_CALL | count of calls / presence of text in the current turn | MODEL_EXTRACTION: quote bound to a line of this input; restriction marker + the single number in the quote = n; no condition/exception/scope/subject other than the agent (model fields + condition words in line + conditional heading); two independent extraction runs agree | all checks pass | permissive wording, number mismatch, any condition/exception/scope, rule addressed to the user, runs disagree |

Not guaranteed (out of scope of every layer): binding of a FOUND value to the right entity (binding=`UNVERIFIED`),
semantic conditions (confirmation, eligibility), correctness of computed values, value transformed from a user value
(CaMeL data flow), call/result pairing when the transcript lost ids, the correctness of the model's reading of a policy
line beyond the code checks above (a MECHANICAL F rule is still a model interpretation that passed checks — basis
`MODEL_EXTRACTION`, not a proof).
