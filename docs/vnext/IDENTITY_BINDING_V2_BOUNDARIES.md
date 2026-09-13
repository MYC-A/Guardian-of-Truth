# Source-owned identity and scoped result evidence v2

New development modules: `identity_aliases_v2` and `scoped_result_evidence_v2`.
They are not yet consumed by the frozen native Goal v2, T2 v1 or old Core.
Their addition changes no running/frozen implementation or prompt.

An authoritative IdentityDeclaration specifies exact tool/provider/version/schema
identity, system namespace, record collection path, stable ID type/field and
alias fields. These are trusted source metadata supplied outside the model;
the code does not guess a schema or derive business effects from tool names.
Only real TOOL-role result records contribute observations, never user/assistant
text or call arguments. Each record group stays separate, preventing a mix-up
between one record's name and another record's ID/value.

Duplicate names yield every stable ID, without confidence selection or top-k.
Namespaces remain distinct even when local IDs match. Incompatible versions or
schemas cannot borrow an identity declaration. Missing/malformed fields preserve
positive candidates but mark search incomplete. Source completeness covers only
the supplied observed namespace, not unrestricted identity meaning or absence.

Every alias observation is historical. Only an explicitly authoritative full
alias snapshot supersedes prior alias knowledge for that stable ID; partial
records cannot erase old knowledge. Same-event conflicts are not last-wins.
Queries before later incomplete events preserve their prior coverage status.
A missing name always reports not-observed, never absent.

Name/time indexes restrict lookup to matching observations. An entity/event
index stores immutable grouped records, so checking one selected field does not
scan every unrelated record. Controlled 2000-record tests verify all-candidate
retention and one-record lookup. These are not model or blind measurements.

Scoped result-field proof compares typed finite JSON inside the selected record
at one exact event. Numbers 1 and 1.0 agree; booleans are not numbers. Missing
fields/source roles are UNKNOWN. Conflicting same-identity/event values yield
BOTH; different identity bindings remain separate worlds. Incomplete alias
search cannot yield a definite aggregated binding answer.

This proves only literal TOOL_RESULT_FIELD equality at that event, not current
state, persistence, completed action or causality. It is primitive evidence, not
an independently certified whole-Core verdict. Thirty-four new controlled tests
pass. Natural-language grounding, authoritative declaration discovery, source
adapters, shared Core world/certificate integration and the frozen Binding stage
remain pending. Do not feed scoped entities into the old flattening Binder as
if it already understood these namespaces/record groups.
