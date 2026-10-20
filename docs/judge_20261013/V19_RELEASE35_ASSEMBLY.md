# Immediate experimental 35B LoRA assembly, 20 October 2026

The operator explicitly requested immediate ZIP assembly with available completed
35B LoRA weights, current fixes and cleanup of obsolete archives. Training and
queued final regressions were stopped. V18 had no optimizer updates; V17 v2
also stopped before any update. No unfinished or zero-update adapter is packaged.
The latest completed adapter is V7, warm-started from V5, last16 layers,100
source modules. SHA256:
`4a44903c463d9244f2816ffd84d8f0bd8ba032a1340ca9b3716e6ae887101313`.

Source ZIP: `guardian-judge-qwen36-awq-open-review40-max-34fb1c75-20261018.zip`.
All original base weights and bundled runtime records preserved by raw copy.
Current production parser/mechanical closure, bounded-turn hard checks and
source-quote contract are included. Primary stays unadapted overall/open/final
MAX with quota .40 and hard protection. A separate 35B instance loads the one
V7 adapter and verifies actual baseline positives using their saved primary
context. Two-line source review192, exact YES-NO odds, threshold0, no refill.
Incomplete/inexact verification preserves the baseline globally. No4B model.

Runtime changes are explicit: primary chunk64, bfloat16, eager synchronous;
primary stop1050/kill1140, verifier stop1560, watchdog1680 seconds from original
entrypoint start. This reserves time for the verifier within30 minutes. It is
not a measured full/private cold-run guarantee. Verifier initialization reloads
the same base weights, rather than adding another full model copy to the ZIP.

Archive: `A:/Guardian-submissions/guardian-judge-qwen36-35b-lora-v7-fixes40-20261020.zip`.
Size30,706,314,899 bytes. SHA256:
`ffd7d9d64eae10819456722f0cb3a49ba0657923fa46dd5da9f5f940f4512123`.
Independent assets audit streamed all21 base assets, including every shard,
and checked every patched-file hash and Python syntax. Only model/judge and
model/lora35_v7 weights exist. Matching checksum is not a quality acceptance.

The shortened-clock six-row primary GPU smoke reached6 exact overall scores
and6 valid prepasses; its300-second clock expired before final scoring after
cold engine initialization. The wrapper correctly retained the primary fallback
and did not falsely claim LoRA applied. The follow-up verifier-only smoke uses
the actual primary spool and no gold labels. Its first driver failed because
it lacked a multiprocessing main guard; production worker already has the guard.
Driver v2 fixes only that test harness. Preserve both failures and final receipt.

Final verifier-only GPU integration PASSED:100 source modules,124 GPU A/B pairs
exactly match source tensors,2/2 candidates had admitted exact final scores,
112.902 seconds on host runtime. It used the exact packaged inference code and
adapter on actual saved primary inputs, followed by guarded decision/output
writing. It is not a full end-to-end MAX control or a private quality/time run.
Aggregate receipts in `v19_evidence/`; complete offbox evidence in
`A:/Guardian-submissions/guardian-release35-evidence-20261020/`.
CPU42 tests passed, including full-wrapper completion vs global fallback,
duplicate IDs, hard protection, no refill and source/parser boundaries.

This is operator-authorized experimental assembly, not original ACCEPT. Human
holdout review remains unavailable. V7 did not outperform the base verifier on
V12's previously used1893-row cohort (.687692 vs .692308). Private improvement
and full target-runtime completion are not established by these checks.

Explicit obsolete ZIP cleanup, with resolved-parent checks: removed the old
4B blend40 archive and six-question MAX archive, freeing69,536,927,324 bytes.
The best source ZIP and research evidence/weights were retained.
