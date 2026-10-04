# Independent code review before inference

The user requested subagent control of implementation. A separate reviewer read
the new experiment contract, inspected the existing SourceStore/EvidenceGraph/
native-checker/transport boundary, reviewed the new four modules, and performed
independent offline edge probes. It did not edit files, author research answers,
read credentials or call APIs.

Five concrete findings were fixed before inference: unknown-usage breaker lost
on restart; full-system read absent from normative candidates; evidence actor
not mechanically validated; malformed provider choices/messages crashing decoding;
missing explicit provider-context preflight. Regressions cover every finding.

Final reviewer verdict: no remaining blocker identified for the bounded pilot.
Its independent 23-test run passed; exact code seals matched and diff against
ba248421 in production and previous research code was empty. This is review
evidence, not a guarantee of bug-free software. The parent combined suite passed
174 tests. The single-round AUTO retrieval limitation remains explicit.

## Post-hoc helper and independent logic reviews

After the user additionally requested logic analysis, a second subagent traced
original source spans, raw provider output, decoded/admitted objects and saved
predictions. It confirmed A/C NO_ERROR originates in the model output while
their explanatory cause is correct. It found no inversion in the code, schema,
cache association or scoring. It independently confirmed AUTO norm discovery,
missing historical line receipt and unmeasured budget-stopped final judgment.
Its final report found no logical overclaim in the failure analysis.

The code reviewer separately ran the new scorer and full core/AUTO replay on a
temporary copy, not the original artifacts. It confirmed A/C binary false/cause
true/complete false, B complete true, payment/AUTO final null with BUDGET_STOP,
45,089 tokens, identical prediction/ledger bytes and exact restoration of both
completion files. No API calls were made. A minor post-hoc hardening suggestion
was applied: decision_reason_consistent must be bool/null and true for complete
recovery. This changes no retained arm outcome or inference code/template.
