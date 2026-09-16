# E2E V1 — External Benchmark Audit (spec sections 132-134)

Probed at terminal-decision time (post-seal; no external data touched the
fresh run).  GitHub API rate-limited this sandbox (HTTP 403); raw
reachability probe:

{
 "ethz-spylab/agentdojo": {
  "reachable": true
 },
 "sierra-research/tau2-bench": {
  "reachable": true
 },
 "apple/ToolSandbox": {
  "reachable": true
 },
 "LiYu0524/ATbench": {
  "reachable": true
 }
}

All four benchmarks were located in the prior Phase-0 audit (see
E2E_COMPONENT_MANIFEST_V1.md / prior session records: agentdojo at
ethz-spylab/agentdojo, tau2-bench at sierra-research/tau2-bench,
ToolSandbox at apple/ToolSandbox, ATBench at LiYu0524/ATbench).

## Adaptation decision (deferred with reasons)

NONE was adapted into the E2E V1 fresh corpus:
1. Trajectory format: none of the four uses the Guardian source envelope
   (role-marked events, call_id identity attributes with
   provider/version/schema hashes, versioned T1 effect contracts);
   adaptation is a format+ontology mapping project, not a corpus graft.
2. Gold provenance (spec section 133): several benchmarks derive labels
   from external LLM judges; the spec forbids treating them as
   authoritative truth without independent verification.
3. Cohort coverage: the E2E V1 fresh corpus already covers the spec's
   section-152 cohort matrix with deterministic construction gold.

External adaptation is recorded as an OPEN item for any future
separately-registered line.
