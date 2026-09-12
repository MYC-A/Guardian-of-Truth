# External data manifest and blind run

The machine-readable freeze is `contracts/external_sources_v1.json`. Before
artifact parsing, the harness verified Guardian commit/tree, four evaluation
file hashes, every repository HEAD, selected-file SHA-256, safe relative paths,
and license-file presence. The first scored run is now recorded as completed;
the readiness gate prevents silently opening a second cycle under the same
manifest.

| Source | Pinned commit | Frozen use | Selected budget | Result |
|---|---|---|---:|---|
| ATFD | `690c9962155865b3b17333bbb9354c15d3eb4170` | recorded tau-family trajectory proxy | 48 trajectories | evaluated |
| tau-bench | `59a200c6d575d595120f1cb70fea53cef0632f6b` | historical trajectory proxy | 24 task groups / 96 trials | evaluated |
| AgentDojo | `357c80dea9af34323f709c3505d9e6d224654c7e` | availability audit | 0 | no recorded traces; unavailable |
| ToolSandbox | `c8571d7854316d2e1c5f288e59fe1e34e53f6dd1` | static tool-schema diagnostic | 32 functions | evaluated |
| BFCL/Gorilla | `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8` | independent schema diagnostic | 30 rows | evaluated |

Selection was label-independent: paths and task IDs were sorted before reward,
outcome, messages, answers, or categories were used. Every selected trajectory
was rendered turn-by-turn: each assistant event became a response, its exact
prior native events became the prompt, and future results were never moved
backward. Trajectory prediction is binary OR over frozen turn predictions.

All 144 trajectories were renderable. The harness froze 288 trajectory
predictions (two detectors) under SHA-256
`f9bc0c87ad5896e7c2c2572e8741f5b764db284f47bdbaacd5b6d75d8f4c50c5`
before joining labels.

The ATFD/tau label mapping is intentionally described as
`trajectory_outcome_proxy_not_guardian_turn_localized`. It is useful evidence
about OOD coverage but is not an independent Guardian accuracy score. The
ToolSandbox and BFCL outputs contain aggregate schema counts only and no inferred
failure labels. Source code and license-restricted excerpts are not redistributed.
