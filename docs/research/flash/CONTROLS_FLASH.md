# Control configurations — flash line (directive sec. 3)

Purpose: every new mechanism must be measured against UNCHANGED controls on identical
inputs. Selected controls are content-wise DIFFERENT (structural / direct judge /
grounded neural / verified / ensemble), not five variants of one idea.

## Fixed controls (public46 = PUBLIC_SEEN, gold joined post-hoc only)

| ID | Architecture | TP | FP | FN | TN | P | R | F1 | Source / provenance |
|---|---|---|---|---|---|---|---|---|---|
| C-struct | offline structural baseline `--backend none` | 12 | 0 | 11 | 23 | 1.000 | 0.522 | 0.6857 | reproduced twice exactly (E1 superz; ifc stage-A), 0.4s CPU, fully offline |
| C-judge-pol | direct judge, pollinations gpt-oss-20b, A0 prompt semantics | 17 | 6 | 5 | 11 | 0.739 | 0.773 | 0.7556 | n=39 (7 long-telecom FAILED); superz E2 |
| C-judge-mist | direct judge, frozen Codex Mistral A0 run | 22 | 16 | 1 | 7 | 0.579 | 0.957 | 0.7213 | historical, sealed; superz/ifc records |
| C-judge-block | direct judge, blockrun pool | 19 | 19 | 3 | 2 | 0.500 | 0.864 | 0.6333 | n=43; superz E2 (high-recall/low-precision) |
| C-verify-e3a | A1R re-anchored suspicions, unverified | 20 | 19 | 3 | 4 | 0.513 | 0.870 | 0.6452 | superz E3a (control for E4 verification arms) |
| C-granite-or | baseline OR granite_groundedness | 13 | 0 | 10 | 23 | 1.000 | 0.565 | 0.7222 | superz E7, exact match with history; offline |
| C-ensemble-ifc | baseline OR granite_grounded (ifc variant) | 20 | 2 | 3 | 21 | 0.909 | 0.870 | 0.8889 | ifc line, best confirmed so far; granite FP ids documented |
| C-and-judges | AND of independent judges Mistral × gpt-oss-20b | 16 | 4 | 7 | 19 | 0.800 | 0.696 | 0.7442 | superz E5; FN overlap between judges = 0 |

## Controls used for specific comparisons

- A4/E4b verification: paired control = C-verify-e3a (same suspicions, no verification);
  secondary = C-judge-mist (producer alone). Per-suspicion deltas (eliminated FP / lost TP /
  new FP / gained TP) measured against C-verify-e3a.
- Experiment G: paired control = E4b blockrun full-context verdicts (same channel, same
  prompt skeleton, raw context vs graph digest). Same-suspicion pairing, only context differs.
- Experiment P: control = the same architecture with P-module disabled ( Base/P/G/G+P matrix
  on identical inputs, fixed models, comparable budgets).
- Independent-set reference (NOT a contest-equivalent control): granite groundedness on
  AgentHallu DEV 488 = F1 0.4043 (P .644, R .295) — recorded to prevent public46 overfitting
  claims; any new mechanism must state its behavior on the same external slice.

## Rules of use

1. No control is replaced silently; new runs must re-print the control row from the same
   journal format.
2. public46 results are never mixed with the 69-case E2E dev or external benchmarks in one
   ranking.
3. Missing predictions default to label 0 ONLY where the pre-registered rule of that
   experiment says so; UNRESOLVED/FAILED are reported separately and never counted as
   refutation evidence.
4. Model identity per call (served_model) recorded for every keyless call (catalog rotation).
