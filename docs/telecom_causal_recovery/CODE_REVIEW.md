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
