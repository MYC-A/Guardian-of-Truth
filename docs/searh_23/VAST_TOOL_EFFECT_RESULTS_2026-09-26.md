# Vast tool-effect component results

These are authored component diagnostics, **not** a new Guardian benchmark or
whole-case score. Frozen code, paired inputs and gold were committed before
their respective API runs. Three prediction files were SHA-256 sealed before
scoring and their archived bytes, input hashes and code hashes were checked
after copying from Vast. Mistral was called through the existing API settings;
no model/dependency was installed or full benchmark started.

## 1. Tool description alone: no supported mapping

The counterfactual probe asks whether a successful result of each tool, *by
itself*, would necessarily establish the completed-action claim. It excludes
observed results to avoid mapping from whatever result happened to be in the
history. On three development families × six history variants it selected
the correct `DIRECT` tool on **0/18** rows. There were nine unique model
requests; the six variants of each family shared the same claim/catalog.

The model marked even the intended action tool `NON_ENTAILING`: it argued that
"Replace the device" does not prove every stage meant by "replacement has
been completed"; likewise sending a refund to a provider may precede final
refund processing. These are defensible readings of terse catalog lines. The
failure is not an API/JSON failure. No fresh run was needed after this
development failure. Relabelling the tools or adding favorable descriptions
would measure a different evidence regime.

## 2. Actual result plus tool description: unsafe false support

The second frozen probe supplies an observed `TOOL_RESPONSE` plus its catalog
line. Code first requires one uniquely paired earlier call, the same entity,
a valid JSON object and successful outcome. Failed results and wrong IDs are
rejected mechanically. No result returns `UNKNOWN`. Mistral decides only
whether the remaining concrete result entails the claim. The same authored
families were used, with separate support gold.

| Suite | Correct verdicts | False support of unrelated result | Missed true support |
| --- | ---: | ---: | ---: |
| Development, 18 rows | 14/18 | 3 | 1 |
| Fresh domains, 36 rows | 26/36 | 1 | 4 |

On development, it accepted an *audit* result as proof of replacement and a
trip *lookup* or booking *audit* result as proof that a booking was complete.
On fresh shipping cases, it accepted a scan-note result as proof of parcel
dispatch. Each result used the same ID and generic `"status":"completed"`.
The model frequently treated that string as completion of the *claim* rather
than completion of the tool's own operation. Four of six fresh true-result
families were missed or left unknown; stronger caution alone therefore did
not produce a useful verifier.

The fresh run had been started when the tool session was interrupted; the Vast
process completed it. The copied prediction and score files include a valid
seal and matching frozen input/code hashes. No inference prompt was changed
after the fresh result was opened.

## Decision

Neither component is safe to promote as a C1 false-positive veto or new
violation arm. In particular, an LLM claim/result quote and matching ID/status
are insufficient to establish a business action. The transferable idea from
the [external tool-trace audit](EXTERNAL_TOOL_TRACE_SYSTEMS_AUDIT_2026-09-26.md)
is an explicit, source-bound tool **postcondition** or authoritative state
change. If neither is available, `UNKNOWN` is the honest outcome. Future tests
should measure coverage as well as false support on held-out real traces;
synthetic 0-FP controls alone would not be evidence of transfer.

Artifacts: `outputs/searh_23/tool_effect_probe_2026-09-26/`.
