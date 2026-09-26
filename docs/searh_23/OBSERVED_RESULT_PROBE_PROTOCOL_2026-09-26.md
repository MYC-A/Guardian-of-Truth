# Observed-result entailment probe

The earlier catalog-only counterfactual probe returned no `DIRECT` tool on
any of its three development claims (0/18 mapped variants). The model argued
that a terse action description does not guarantee all stages implied by the
word *completed*. This is a real limitation of the source, not a reason to
silently relabel or loosen the output. Its sealed development artifact is
archived under `outputs/searh_23/tool_effect_probe_2026-09-26/`.

This second probe asks a narrower question: does a **specific observed tool
result** establish the specific completed-action claim? It sees the exact
catalog line and JSON result. Code first requires one parsed call/result pair,
the same identifier, and a successful outcome. Failed results and wrong-entity
results are rejected mechanically. No observed result yields `UNKNOWN`, never
an unsupported-completion finding. The model's semantic relation is
`ENTAILS`, `DOES_NOT_ENTAIL` or `UNKNOWN`.

The same frozen development and fresh input suites are used: 3 and 6 action
families, six paired variants per family. Separate support labels are in
`dev.observed_gold.json` and `fresh.observed_gold.json`. The action state,
claim entity, and policy meaning remain authored oracles. This tests a
possible *false-positive refutation* component, not an independent detector
of policy violations. A coincidentally correct verdict must not hide a wrong
semantic relation; score each valid and invalid result separately.

The development run is scored first. The fresh run is made once, with the
prompt and labels committed before it starts. Seal prediction bytes before
opening gold. If any unrelated successful result is labelled `ENTAILS`, do
not use the component as a C1 veto. Even zero false support on these authored
cases does not establish transfer to real contest histories.
