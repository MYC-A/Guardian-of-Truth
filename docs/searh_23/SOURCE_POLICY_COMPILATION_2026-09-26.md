# Source policy compilation probes (2026-09-26)

## Question and boundary

The open failure is source interpretation: which *action* a policy clause
constrains, and whether every prerequisite has been represented. A correct
event graph cannot recover an omitted prerequisite or repair a condition bound
to a preliminary lookup. These probes use `MISTRAL_MODEL=ministral-14b-latest`
and `MISTRAL_API_KEY` from the server environment via Mistral API. No key is
stored in Git, no local model was downloaded, and no full competition benchmark
was run. All cases and gold are local; the provider saw only the query for each
task. The competition entry point was not changed.

The initial capacity arm used pinned `ministral-14b-2512` with a different
prompt and full tool descriptions. It got 4/7 exact typed-atom policies and
0/5 exact service-desk/hotel clause scopes. The attempted Medium arm received
HTTP 429 and produced no comparable score. These results cannot isolate model
capacity from prompt/catalog effects. The hardcoded Small 4 follow-up was not
run because the subsequent instruction was to use the model in server env.

## Action scope: parent clause owns the restriction

The new prompt asks for the tools performing the action restricted by **one
original clause**, with short descriptions of the declared tools. It explicitly
separates performing an action from checking a prerequisite or submitting a
request. The parent clause's scope is then inherited by its prerequisites in
`source_rule_block_v1`; children may not substitute their own `governs_tool`.
That component only evaluates a supplied interpretation of a supported clause
and never issues a global SAFE verdict.

| Split | Strict exact scope **and literal action quote** | Tool scope before quote validation |
| --- | ---: | ---: |
| Previously viewed service desk/hotel clauses | 4/5 | 4/5 |
| Other clauses from those same two policies | 5/5 | 5/5 |
| Original public46 clauses from retail, airline and telecom | 5/7 | 7/7 |

The one semantic scope error is the hotel cancellation-order clause: the model
included `cancel_reservation` along with `process_refund`, although the clause
requires cancellation *before* refunding and constrains the refund step. In
public46, the two rejected outputs chose the expected tools but returned
`modify` for source `modified`, and `send payment request` for source typo
`send payement request`. Exact source provenance correctly rejected both.

A separately frozen, post-hoc quote-only repair asked the same env model to
copy a literal substring and kept the tool list fixed. It produced valid quotes
on 2/2 invalid public46 responses. This is a format recovery result, not a
retroactive 7/7 first-pass score. The accepted quotes do not prove that the
chosen tools capture every action in an arbitrary rule.

The service/hotel prompt was developed after prior failures on those policies.
The five clause holdouts share the same two policies, and public46 was already
available for repo research. The 7 public clauses provide a domain/catalog
transfer check, not a blind benchmark. All expected scopes were authored from
source text before the corresponding calls, and no binary labels were supplied
to the model.

## Independent audit of atom coverage

A second prompt compared the original policy with a candidate typed rule. For
five supported conjunction policies, the frozen candidate was either the
authored gold, gold with one condition deleted, or gold with one condition's
governed action changed to a request tool. This isolates whether a separate
LLM question can detect omission or wrong action binding. It is **not** an
end-to-end test of model-produced atoms.

The first catalog omitted two argument names of target tools. A post-hoc v2
supplied those argument names, without trace values or labels, and repeated all
15 calls with the same prompt. Counts below require a coherent JSON answer and
a literal source quote for a reported flaw:

| Candidate type | v1 strict correct | v2 corrected catalog strict correct |
| --- | ---: | ---: |
| Fully correct | 2/5 | 2/5 |
| One prerequisite removed | 4/5 | 4/5 |
| One prerequisite bound to a request | 4/5 | 5/5 |

In v2, the model rejected three fully correct candidates: the document rule
(`PRIOR_TRUE` was cited as though it were source text), the refund rule (it
claimed the customer-ID prerequisite had wrong scope), and the booking rule
(it invented `verify_traveler` inside a supposed source quote). Two rejection
quotes also contained inserted markdown markers and failed literal validation.
The audit therefore behaves like a high-abstention **diagnostic veto** on these
synthetic cases; it cannot certify that all source requirements were captured.
It would discard three of five valid supported rules even with the corrected
catalog. No false acceptance was observed among the ten constructed flawed
candidates in v2, but ten cases cannot establish a reliable safety bound.

## Engineering decision

Keep the clause-owned action scope and exact-quote gate as candidates for a
future component: they addressed the concrete lookup-versus-action failure and
transferred to three public46 domains at the level measured here. Do not use
scope extraction alone to declare compliance. Keep the atom coverage audit off
the contest decision path: a second LLM found some controlled mistakes but
also rejected correct formalizations. Existing `source_guard_reason` syntax
tripwires catch only a small known vocabulary; they cannot prove arbitrary
policy completeness.

The next gate for promoting this architecture is an independent set of full
policies and traces, with exceptions, numeric relations, implicit conditions,
revoked approvals, and tool catalogs with complete argument/result schemas.
Score source IR against policy gold *before* any binary replay. A proposed
SAFE must remain UNKNOWN when a clause is unsupported or a complete source
interpretation cannot be established. Only after that should a small, frozen
end-to-end arm be compared to the existing contest detector.

## Reproduction

Protocols were frozen in Git before their respective API calls:

- `d039aa7`: ten service/hotel clauses, protocol SHA256
  `2b54013adb32ef623782e66ab12073575bf175e00d2dd32dae03b433351fbba9`.
- `4b67279`: seven public46 clauses, protocol SHA256
  `8e86e3faa40450fc84d0c9a743cc12f41180ca3e7f515d31b7d55290e15a89ec`.
- `13f792d`: quote-only repair, protocol SHA256
  `4549550c210c76d7be08aad18ac83f04f28e6f25c5290457db8552d74096b839`.
- `32b2678`: first coverage audit, protocol SHA256
  `16ce2e51654b1afc35d6396eebd1b914e8c111536e744628b82ae1c6868cd4ea`.
- `7c64786`: repaired catalog audit, protocol SHA256
  `2527708072631f8fff473ab9973aa96ac9e4993fce47decabc005c4f5d51b51b`.

Run `python experiments/searh_23/<probe>.py score`, where `<probe>` is
`source_scope_probe_v2`, `source_scope_public_v1`,
`source_scope_quote_repair_v1`, `source_coverage_audit_v1`, or
`source_coverage_audit_schema_v2`. Per-task raw responses and score files are
under the corresponding `outputs/searh_23/` directories. The JSON records
seal protocol/query hashes and requested model; they do not contain API keys.
