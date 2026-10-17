# Full blind-review submission build — 17.10.2026

Requested artifact: a NEW full ZIP (weights + bundled Linux runtime), not the small code package.
Previous submission ZIPs are preserved. Repository production defaults remain overall-only;
this archive explicitly selects submission/JUDGE_BLIND_REVIEW_EXPERIMENT.json, review_mode=blind.

Pinned input runtime archive:
A:/Guardian-submissions/guardian-judge-qwen36-awq-6540dc50UP1.zip,
SHA256 f54329f9c8fd7779fe31a66fdeca76f520de699c2969421355d29d45182c56c7.
The builder verifies this hash and every final archive member, preserving all runtime bytes.

Model: cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit,
revision 00fcea2d3bcf5389b518d4fc082e5590e0ba4844, existing A:/Guardian-weights/qwen36-awq.
All 21 files must match their pinned download receipt (SHA256 or git blob SHA1),
including the exact six-shard index. No new model download or package upgrade is required.

New builder flags: --judge-config selects an opt-in archive config, --source-revision
records its code commit. Invalid review config fails before any weight/source-ZIP read.
The default repository config and existing single-pass/dense build modes stay available.
Fixture ZIP tests check legacy, dense, and blind modes, packaged runtime imports and README.

```bash
python scripts/build_judge_submission.py \
  --source-zip SOURCE.zip \
  --source-sha256 f54329f9c8fd7779fe31a66fdeca76f520de699c2969421355d29d45182c56c7 \
  --model-dir /existing/qwen36-awq \
  --model-id cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit \
  --model-revision 00fcea2d3bcf5389b518d4fc082e5590e0ba4844 \
  --judge-config submission/JUDGE_BLIND_REVIEW_EXPERIMENT.json \
  --source-revision CODE_COMMIT --output NEW_FULL_SUBMISSION.zip
```

For the actual release the local driver additionally verifies the pinned model receipt
against all current model files before the builder writes the final ZIP.

GPU access: bounded attempts to configured guardian-vast-new and guardian-vast failed
(connection timeout / connection refused). GPU_UNTESTED; no Qwen F1, throughput or
A100 whole-script runtime claim follows from this build. Linux CI and final archive
inspection results are recorded separately with their exact commit and SHA256.

Acceptance scope: archive integrity/offline layout/runtime dependencies/public entrypoint
and available CPU/CI checks. Algorithmic ACCEPT requires the independent data and
quality/timing experiment described by the original handoff; it remains unproven.
