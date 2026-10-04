# Paired model impact

No comparable improvement over the original Selector's supported case was
observed. B1 changes Silver's raw false positive into a correct negative label,
but its seed omits the authoritative profile/reservation receipts. The cause
audit therefore does not credit this as a retrieval-grounded repair.

One fixed model (`ministral-14b-2512`, actual returned model matches), strict
schema, temperature 0, unchanged decision-last I4 prompt and eight-read/20,000
source-record bound were used. The cases and exact requests were committed in
`0c5c7b19` before inference. A's unsupported inputs and one intermediate skip
remain null technical outcomes. Telecom B1 and local BM25 have identical wire
requests and share a cached response. Six eligible review rows used five new
HTTP calls and **22,174 actual tokens**; adding per-row token fields would
double-count that reuse.

| Case, original binary gold | A raw / admitted | B1 raw / admitted | local BM25 raw / admitted |
|---|---|---|---|
| Telecom device diagnostic, 1 | NO_ERROR / NO_ERROR | NO_ERROR / NO_ERROR | NO_ERROR / NO_ERROR, cached B1 |
| Silver baggage information, 0 | unsupported / null | NO_ERROR / NO_ERROR | ERROR / ERROR |
| Bank57 identity request, 0 | unsupported / null | ERROR / null: actor admission | reserved skip / null |

The only directly comparable supported A/B1 case stays a false negative. On
the two B1/local raw paired cases, B1 removes one false positive and leaves one
false negative; there is no true positive in either arm. Bank's raw ERROR is
another false positive, independently rejected for source actors. Null admission
failures are not UNKNOWN or negative predictions. Semantic UNKNOWN maps to 0
only when admitted; there is no impact-phase UNKNOWN. An overall valid46 F1,
production improvement or independent-holdout result cannot be inferred here.

Independent causal inspection against the whole originals identifies:

* Telecom mistakes a listed USER diagnostic for an ASSISTANT permission. All
  packets omit the distinguishing device heading and complete agent inventory;
  declaration absence alone is not a complete-catalog absence proof.
* Silver B1 correctly states two bags per passenger and four in total, but the
  native profile/reservation supporting these facts is missing from its packet.
  It invents a verification REQUIRE from a profile-attribute list and calls the
  prior correct calculation incorrect. Local BM25 treats the user's Gold claim
  as operative state and invents verification/override duties for information.
* Bank57 applies a later account-opening duty to the current request for
  identification. No account opening occurs. Its KB result sources have native
  assistant actors; labeling them system is separately an admission failure.

Source-ID/schema admission is therefore necessary but insufficient for causal
correctness. Numeric label correctness alone must not credit an unsupported
reason. Detailed row judgments are in [CAUSAL_AUDIT.md](CAUSAL_AUDIT.md).

The frozen review adapter also misclassifies native prefixed JSON receipts as
normative candidates: strict JSON decoding sees `TOOL_RESPONSE:` plus JSON and
fails. The original source actor/text remains intact, but factual receipts can
enter the policy-ID namespace. This is a presentation defect, distinct from
retrieval-span integrity and model actor errors. It plausibly affects judgments;
the experiment does not isolate its causal effect. Independent verification finds
two affected actual HTTP requests (Silver S0 and S2), with h8 and h8/h7,
respectively. Their raw norm citations remain policy q IDs; their rejected
evidence actor claims are separate. No post-hoc fix or rerun was
used to improve these frozen results.

Raw responses, provider-qualified wire hashes, requests, admission outcomes and
usage are retained in `outputs/retrieval_bakeoff_v1`. Replay independently checks
transport hashes and reconstructs decoding without any HTTP call. Additional
S2G evidence and its costs are reported separately.
