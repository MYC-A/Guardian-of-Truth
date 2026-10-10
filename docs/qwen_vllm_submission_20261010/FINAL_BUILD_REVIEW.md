# Final local assembly review — 2026-10-10

The selected transport is the original server export, not a CI replacement.
Runtime ZIP: 5,700,777,181 bytes, SHA256
`bd8fae06c167df4b166e708cccc76022e013755efb741409e533c4b3db1f5e2f`.
Its source is `65bf34384929a6001132d8dd6e6a8be51298d990`.
The final archive supplies every one of its 78 declared model assets from the
locally downloaded pinned FP8 model. No old GGUF is used.

## Independent source and configuration review

`submission_config_review` inspected the actual runtime ZIP without extracting
the large runtime. All 350 packaged Python files match their manifest hashes
and compile. Packaged B2 and adapter agree with measured graph16 commit
`ea4b7b34`; adapter SHA is also identical to historical graph16 receipts.
Runtime modules match current source after presentation-only newline
normalization, apart from the intentionally generated experiments namespace.

Profile: vLLM 0.19.1, Transformers 5.8.0, official
`Qwen/Qwen3.8-27B-FP8` revision
`017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`, workers16/slots16,
context32768, CUDA graphs (no enforce-eager), prefix caching,
chunked prefill, BF16 compute, KV auto, thinking off.

Output recovery preserves strict valid decisions, then accepts a completely
decoded top-level primary model decision, and uses DEFAULT_ZERO only when
that decision is unavailable. Recovered classification does not become an
admitted accusation; unsupported explanations are cleared. No partial JSON
fragment or nested decision is inferred as a label.

Historical graph16 used startup900s and a 400-call ceiling. The public package
uses startup600s and a cohort-dependent ceiling; valid46 ceiling is 5148.
The ceiling is not a plan to issue that many calls. Public caches are fresh
and bundled Python is relocated; historical measurements used a venv.
Historical OMP/OpenBLAS values are not frozen by the packaged launcher.
These differences require a public cold GPU timing run for validation.

## Independent assembly boundary review

`assembly_boundary_review` checked actual inventory, identities, model
declarations, paths, modes and forbidden filenames without duplicating the
full hash scan. The transport contains 52,594 members; omitted manifest
members are exactly the 78 declared model assets. This is the supported
runtime-only transport of a fully verified server stage, not an inference ZIP.

The real inventory JSON is 21,339,744 bytes and exceeded the former 16MiB
metadata cap. The assembler now has a separate 64MiB runtime-inventory cap;
model JSON retains its 16MiB cap. Positive and negative regression tests
cover that distinction. No integrity, schema or identity check was removed.

Local extra files `gitattributes` and `safetensors-md5sum.txt` are not declared
assets and are excluded. No external benchmark inputs, gold or predictions
are included. Wheel-owned fixture names remain distinguishable from application
data. Filename review is not a general secret-content certification.

109 packaging/public-entrypoint/B2 tests passed. Actual local assembly separately
checks every runtime and model file SHA, then all final ZIP members and modes.
The output is root-level ZIP64 with stored safetensors, immutable sources,
exclusive publication and a strict 40,000,000,000-byte cap.

## Validation boundary

The user requested that the separate active `guardian-arm` GPU experiment
remain running. No GPU process is stopped, and no 36GB ZIP is uploaded to the
server. CPU-only relocation checks use existing frozen server stage bytes.
Their receipts and final local assembly receipt are recorded separately.

Historical graph16 valid46 was 16TP/0FP/7FN, F1 .8205, whole wall 677.55s in
one development repetition. That is not cold GPU validation of this package
or proof of full/private-test timing. The adapter's 1800s internal deadline
starts after public input preparation; cleanup/publication can extend beyond
it. No strict whole-public-wall guarantee is made.

Final path: `A:/Guardian-submissions/guardian-qwen-vllm-fp8-graphs16.zip`.
Receipts: `A:/Guardian-submissions/vllm-fp8-build-20261010/`.
The original Q8 submission ZIP remains unchanged.
