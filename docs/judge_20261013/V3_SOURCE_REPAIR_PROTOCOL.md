# Source repair before any optimizer update, 2026-10-18

The 205-row blind stratified audit of candidate SHA256
b5525ffe8fb08b7bf27c619201df8694106697bcd4fabc84a486ddc1f3ffe41c
contains 33 disagreements/technical failures. This is not an annotation error
rate. Review against the actual source found unsupported calendar dates in
ToolRM and questionable inherited negative labels in RAGTruth QA/Summary.
The original candidate is NOT approved for training.

Before seeing any training/evaluation result, apply the following conservative
quarantine to a new directory; preserve all old rows and labels unchanged:

- Quarantine every RAGTruth QA/Summary component, both labels. Do not scale
  these adaptations until their strict-grounding labels are repaired. Retain
  Data2txt provisionally, subject to a fresh blind sample/source review.
- Quarantine each ToolRM component containing a target ISO calendar date that
  is absent verbatim from preceding user/tool/system messages. Assistant claims
  alone cannot establish the missing calendar anchor. This is conservative;
  it does not certify all other argument values.
- Exclude entire existing split components, preserving every contrast twin.
  No corrections to protected evaluation labels and no selective removal based
  on evaluation performance. Keep a full quarantine ledger and parent hashes.

Run the independent mechanical proof audit again, followed by a new pinned35B
blind sample. A separate source review matching the NEW candidate hash must
explicitly approve exploratory training; the old review cannot unlock it.
Retain the original six-hour deadline 2026-10-19T02:18:43Z and all original
quality/human/long-context failures. No optimizer update precedes review.

Existing source caps and 30-40% positive / >=30% hard-negative checks remain
binding for the exploratory subset. If deterministic frozen selection cannot
satisfy them, record a failed freeze and fix selection before optimization;
do not waive the checks. No extra model, training seed, teacher service, or
production/ZIP change is authorized by this repair.
