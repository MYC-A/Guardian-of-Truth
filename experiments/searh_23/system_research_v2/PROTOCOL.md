# SYSTEM RESEARCH V2 — PROTOCOL (frozen before sealed inference)

Branch: `zai/system-research-v2-20260930` (from `codex/system-integration-step1-4-20260930` @ b473a2f9)
Date: 2026-09-30

## Environment change (documented, not hidden)

The Guardian GPU gateway (Granite/Mistral backend) is unavailable this
session and the previous Mistral API key returns 401. All V2 inference runs
on NEW providers (§ДОПОЛНИТЕЛЬНЫЕ API): ollama.com (gemma4:31b,
gpt-oss:20b/120b, nemotron-3-nano:30b/super/ultra), ukisai swift, vireonix
auto. V2 numbers are therefore NOT directly comparable to V1 model-specific
results; frozen-suite oracle paths (model-independent) reproduce exactly.

## Frozen before any sealed inference

1. `mutations.py` — generic mutation library (§15), constructive invariants
   only (§16); no domain vocabulary.
2. `frozen/trajectories_v2/` — 20 dev + 20 sealed trajectories
   (SHA256 in manifest.json), every case self-verified against the FROZEN
   proof runtime (verdict + world facts exact) BEFORE freezing.
   - dev families: bakery, ferry, museum, orchard, lab(prose-only)
   - sealed families: cinema, quarry, apiary, transit(refusal), archive
   - stress: async request-vs-completion, timeout rules, LONG multi-rule
     (ferry 8 sentences, quarry 7), schema version change, same field name
     in two tools, entity IDs that matter, amount scope joins, claim-mode
     stress, reachability (REACHABLE/OPEN/CLOSED/CLOSED-blocked)
3. Role assignment (dev-only probe, outputs/probe_task*.json):
   - primary extractor Φ1: gemma4:31b
   - second extractor Φ2: gpt-oss:120b
   - contract interpreter: swift (+ nemotron-3-super variant)
   - repair model: gemma4:31b
   - contrastive resolver: gemma4:31b / gpt-oss:120b

## Anti-leakage rules (directive §18/§60/§62)

- No sealed gold is opened before arms are frozen and inference complete.
- No prompt/rule/threshold changes after seeing sealed results.
- No domain dictionaries, case IDs, or regex fitted to sealed failures.
- Dev iteration only on the dev split + v1 dev material.
- Any post-sealed diagnostic is labeled post-hoc; confirmatory round is V3.

## Arms (frozen after this file, before inference)

- S1-A one-shot extraction (primary model)
- S1-B compositional (clause inventory → local gates → composition)
- S1-C action-inventory-first
- S1-D bidirectional source coverage verification
- S1-E CEGIS-like: mutation falsifier + localized repair (max 3 rounds)
- S1-F multi-Φ (Φ1 + Φ2 carried separately)
- Step2 prose contract acquisition (compositional + contrastive)
- Step3 compositional claim inventory + coverage
- Step4 goal/action discovery
- System: multi-Φ consensus (universal / error-existential variants),
  behavioural equivalence, oracle decomposition, full-auto metrics

## Kill criteria (§104)

A mechanism is removed from the active path if: no gain, dev-only gain,
fresh-holdout failure, disproportionate cost, more FP than TP, or domain
vocabulary dependence.
