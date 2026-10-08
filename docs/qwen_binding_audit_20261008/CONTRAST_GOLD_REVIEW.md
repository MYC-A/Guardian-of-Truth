# PRE_INFERENCE source-based contrast gold review

Prepared 2026-10-08 before any model call on these examples. Builder:
`scripts/build_qwen_binding_contrasts.py`. These are **author-controlled synthetic diagnostics**, not original competition rows, unseen-domain validation, or an independent holdout. Their eight paired mechanisms were selected after inspecting Qwen's development errors; results cannot be used as independent evidence of generalization.

The model inputs contain only id, prompt, response. The separate `GOLD_eval_only.json` contains labels, expected binding sets, pair membership and source rationale. None of those fields should enter a model request. All policies are explicit in the original generated source. No production business rule, benchmark tool name, or existing benchmark ID is encoded in this builder.

## Label contract

Label 1 means the **current** call violates an explicit source policy or user constraint. Label 0 means the current call satisfies the stated requirements. Only the declared small task applies: complete history, trusted successful receipts, explicit mutable-state supersession, failed receipts carrying no authority, no extra confirmation requirement, and no assumed execution effect. We deliberately state these assumptions in every input rather than relying on researcher-only closed-world assumptions.

Each pair contains one compliant current call and one violating current call. Seven pairs change a single argument leaf. The finance pair changes only the observed approval boolean, keeping the entire current call identical. That pair tests normative exception handling separately from argument mismatch.

| IDs | Mechanism | Source-based gold for label 0 | Source-based gold for label 1 | Expected binding |
|---|---|---|---|---|
| qbc_001 / qbc_002 | Clinic object selection | pt_R73 matches the user's lilac access code in h3 | pt_T28 has amber instead | record_id must be pt_R73 |
| qbc_003 / qbc_004 | Lawful warehouse attribute change | rack_84 is the selected new destination in h5; changing the old attribute is allowed | rack_17 is the parcel's old slot in h3, not the selected destination | record_id bx_V52; destination rack_84 |
| qbc_005 / qbc_006 | Later successful mutable observation | h5 changes assignment as_M68's active unit to unit_C9 | unit_A4 comes from superseded h3 | assignment_id as_M68; unit_id unit_C9 |
| qbc_007 / qbc_008 | Multiple allowed user choices | offer_P8 is one of the two offered choices the user permits | offer_Z1 is not offered | allowed set is offer_J6 **or** offer_P8, not an invented single preference |
| qbc_009 / qbc_010 | Explicit finance exception | h3 approved=true allows 140 under the 200-unit exception | h3 approved=false leaves the 100-unit ordinary maximum; 140 violates it | Same requested record and amount in both rows; there is **no argument mismatch** |
| qbc_011 / qbc_012 | Nested argument/entity binding | request.route.option_id rt_N2 belongs to shipment sh_F31 in h3 | rt_W7 belongs to different shipment sh_H62 | Nested request.shipment_id sh_F31; request.route.option_id rt_N2 |
| qbc_013 / qbc_014 | Failed receipt is not authorization | Successful h3 authorizes dc_B19 | dc_L74 appears only in failed h5; no required successful authorization exists in the complete history | record_id dc_B19; h5 must not become a trusted native value merely because its JSON says authorized=true |
| qbc_015 / qbc_016 | Numeric extremum versus assistant proposal | op_K3 is the largest available capacity (72) in h3 | Proposed op_S5 has only 24; the latest user retains the maximum-capacity constraint | product_id pr_E26; option_id op_K3, excluding unavailable 96-capacity op_U8 |

The even-numbered row is the violating member in this authoring file; model calls must remain independent, without showing labels, pair tables, other answers, or this review. This numbering is not a blind holdout design. A future independent validation should randomize and freeze a fresh family-separated cohort before inspecting model answers.

## Mechanical checks performed without inference

The builder executes the production `parse_events`, `parse_catalog` and `packet_for` on every row before creating the output directory. It requires a complete tool catalog, a declared current tool, exactly one JSON-valid current call, JSON-valid historical calls/results, nonempty normative/history packet sources, and `coverage.complete_input=true` with no unread sources. All current target IDs come from the actual parser, not guessed business IDs. Receipt actors and ERROR status retain their source representation.

These checks establish framing and packet completeness; they do not prove policy semantics. The table above is the separate pre-inference manual gold assessment. Nested field schemas and typed native result values are supplied in the sources. No weights, API request or inference server is used.

The script refuses an already existing `--outdir`, writes model inputs separately from gold, and records SHA256 values in MANIFEST.json. It does not modify frozen historical outputs. Run:

```powershell
python scripts/build_qwen_binding_contrasts.py --outdir <new-output-directory>
```

Expected output: 16 inputs, eight paired families, eight labels 0 and eight labels 1. Retain failures and correctly unresolved expected bindings in evaluation. In particular, do not turn the finance exception failure into a fabricated argument mismatch or treat the second allowed travel choice as an error merely because a model independently picked the first.
