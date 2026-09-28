# LEVEL F — Ready IE Frontends: protocol

Branch: `codex/step1-ready-ie-frontends-20260928` (from
`codex/relation-research-20260928`). `scripts/predict.py` untouched.

## Question

Does a READY information-extraction / semantic-parsing system produce a
more correct SOURCE-BACKED candidate semantic graph than the current
self-built H2/Stanza frontend — and can an endpoint-grounded evidence
certificate stop the FULL-GOLD wrong-endpoint licensing failure?

Pipeline under test:

```
POLICY
  -> ready IE system            (proposes nodes/types/arguments/relations)
  -> candidate typed graph
  -> source-anchored endpoints  (exact offsets or UNKNOWN)
  -> endpoint-grounded evidence certificate
  -> trusted policy relations   (frozen DIR/CLS/GRP stack)
```

The external system only PROPOSES. Guardian verifies.

## Frozen artifacts (this commit, BEFORE any inference)

- `frozen/level_f_cases.json` — 15 cases, 133 typed mentions
  (EVENT 52 / ENTITY 32 / EVENT_REFERENCE 22 / ARTIFACT 15 /
  STATE_OR_FACET 8 / CHECK 4), 54 canonical events, 54 semantic links
  (REFERENCE_OF / STATE_OF / ARTIFACT_ABOUT / CHECKS / SAME_EVENT),
  38 arguments, 23 normative edges with evidence spans.
- `frozen/level_f_cases_renamed.json` — opaque tool ids `tool_NN`.
- `frozen/level_f2_cases.json` (+renamed) — sealed validation, 5 cases,
  scored once after the final pipeline is frozen.
- `frozen/certificate_cases.json` — 22 endpoint-certificate unit items
  (9 supported incl. reference chains; 11 unsupported incl. wrong
  endpoint, argument-as-endpoint, state/artifact/check confusions,
  reverse direction, no-relation coordination; 2 OR-group items).
- `frozen/manifest.json` — sha256 of all frozen files.

Level E failures were used ONLY to define categories, never as cases.

## Arms

Frontends (zero-shot/pretrained ONLY in the first comparison):

| arm  | system                     | notes                                   |
|------|----------------------------|-----------------------------------------|
| CUR  | current H2/Stanza frontend | ported as-is to Level F                 |
| ONEKE| OneKE (zjunlp)             | schema-guided LLM extractor             |
| UIE  | PaddleNLP UIE (uie-*-en)   | span+offset extractive; two modes       |
| AMR  | real AMR parser            | predicate/argument structure witness    |
| DKE  | DeepKE                     | investigated; run or documented reason  |
| OMNIEVENT | OmniEvent            | trigger + argument extraction           |
| OPENNRE | OpenNRE                  | RE baseline on gold endpoints           |
| GLINER | GLiNER (2024-2026 line)  | modern zero-shot mention detection      |
| LLM-SG | schema-guided LLM (API)  | same schema paradigm, our infra         |

Hybrids only after individual ablations. Every adapter maps into the
Level F ontology; adapters are fixed on dev/F-free cases only.

## Oracle controls

ORACLE MENTIONS / ORACLE TYPES / ORACLE SEMANTIC LINKS / FULL GOLD
graph — decompose where loss remains (extraction / typing / linking /
licensing).

## Tracks

- **Track A** — frontend quality alone: mention P/R, type micro/macro
  F1, argument accuracy, semantic-link P/R, hallucination rates,
  source-provenance availability.
- **Track B** — full Step 1 downstream with the frozen relation stack
  (CE band 0.35 -> evidence -> judge -> DIR -> CLS), strict Level E
  graph scorer semantics.

## Evidence arms

- E1 current extractor (+ judge);
- E2 frontend-informed extractor;
- E3 endpoint-aware extractor with Q1-Q5 decomposition:
  where is A, where is B, is THIS pair related, which direction,
  which type. Paraphrase without exact source anchor -> UNKNOWN.

## Discipline

- UNKNOWN never becomes negative truth; unmapped labels stay UNKNOWN.
- No keyword rules, no business verb dictionaries, no case-id hacks.
- Rename suite must keep verdicts stable.
- Adapters defined BEFORE sealed test; no post-hoc label remaps.
- Dataset commit before inference; code commit before sealed test;
  results commit after test.
