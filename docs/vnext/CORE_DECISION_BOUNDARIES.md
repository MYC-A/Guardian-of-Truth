# Certificate-gated Core decision and bounded escalation

`vnext.decision.decide` integrates the proof solver, certificate construction and
independent verification. A definitive status without a validated certificate is
not constructible as a CertifiedCoreResult. Failed verification downgrades to
UNRESOLVED and exposes checker errors as missing-evidence diagnostics.

This proof/decision integration is implemented. Full integration of semantic
frontends and operational grounding into Core is still PENDING: candidate drift
labels, paraphrased policy conditions and goal actions must not become proof facts.
The next implementation must compile/bind them against actual source fields/events,
retain alternatives, and emit stable unresolved reasons for unsupported mappings.

Audit/safety-first/competition mappings live only in `vnext.adapters`. Audit returns
no label for unresolved/inconsistent; safety-first returns 1; frozen competition
mapping returns 0 for UNRESOLVED, 1 for INCONSISTENT. Every output retains Core
status, mapping version and used_fallback. A 0 fallback never means proved safe.

`vnext.escalation` has exactly three ordered opportunities after UNRESOLVED:
narrow reparse, indexed search expansion, independent semantic challenger. No more
than one callback per step; no escalation after a definitive or inconsistent result.
Exhaustion returns terminal_unresolved=true without inventing a new binary status.
Every proposed update is recertified; callback-provided verdicts are not trusted.

Original events/observations remain an immutable prefix; trusted effects/contracts
cannot be removed/rewritten. Previously admitted interpretations cannot be dropped
or silently rewritten behind the same identifier to obtain a desired verdict.
Unparsed failure placeholders are not real admitted meanings. In the current
version, authority-based pruning of admitted readings is deliberately unsupported;
such an extension would need separately checkable discarded-hypothesis reasons.

Unit checkpoint is separate from semantic stage results. It establishes neither
stage admission nor end-to-end improvement. The frozen T1 v1 sources/results remain
unchanged. No blind labels/rationales are opened by unit/integrity checks.
