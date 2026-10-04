# Preparation revision before any inference

The first prepared protocol (`085609f3…`) is preserved with its exact input order,
metadata and code hashes in `outputs/research_v5/diagnostic3_preflight_v1`. It has
zero inference HTTP requests and no predictions. It is not retrospectively repaired.

Actual tokenizer preflight gave reservation sizes D0/P3 of 66,452/70,170 for the
77,117-char banking case, 47,544/51,262 for the telecom case, and 34,090/37,808 for
the negative control. The long first call could leave insufficient room to reserve
its paired arm under the 100,000 ceiling. Spending that call first would be a poor
comparison even without a model error. All full contexts fit the live model's
262,144 context capacity; the issue is total budget, not source truncation.

Before observing any new model output, the same three source rows are reordered
to **telecom role case → negative control → banking process case**. Their contents,
candidate generation, both prompts/schemas, inference code and official gold are
unchanged. Prepare a fresh output phase and seal. Reuse the same completed
read-only provider/tokenizer preflight, without new metadata requests/downloads.
The banking case may remain explicitly BUDGET_STOP/UNKNOWN if the full-source
reservation cannot fit. No comparison uses an incomplete pair.

This prioritizes the source-clear role validity failure over the conditional
oracle assertion that a specific complementary search is mandatory. A process
absence oracle does not establish that semantic entailment automatically. Even
successful role grounding does not show an incremental binary gain if the fresh
direct control already detects the error.
