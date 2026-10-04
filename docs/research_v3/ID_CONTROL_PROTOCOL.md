# Development-only source-address controls

The primary development responses confuse source roles and generated leaf paths.
Test the already implemented, previously unmeasured `IdGraph` on the same 16 dev
cases and same Mistral model. It supplies code-owned line span IDs and arity
constraints to the existing early INVENTORY/EFFECT/LINK/WITNESS pipeline. Its
existing modality prompts are also retained, so this is a bundled ID/arity/scope
control, not pure source-ID causality. Limits: 60 requests / 180,000 tokens.

A separate 16-request / 40,000-token A0 control leaves its semantic prompt intact
and constrains policy_ids/evidence_ids by actual source enums in JSON Schema.
These controls are development-only: no heldout labels are used to select fixes,
and they cannot replace the frozen A0/A1/A2/A3 scores.

Adapters and original span-ID implementation hashes are sealed before inference;
all source-ID validity remains distinct from semantic citation support.
