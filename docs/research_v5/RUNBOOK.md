# Offline reproduction

Run from the research worktree root on branch
`research/semantic-atomic-v5-20261004`. The inference source is frozen at
`b33c77137db56a4f9b874403a4a3ff385ad7bd11`; later commits add reporting and
replay helpers without altering that source. No model credentials or live
inference are needed for the commands below. Do not prepare a new protocol over
the retained pilot directory.

## Environment

The successful Windows replay used Python 3.13.7, Pydantic 2.13.5 and tokenizers
0.22.2. The pandas/pyarrow diagnostics used the existing local Python installation.
Set the source path in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\src"
$r5_py = "$env:TEMP\guardian-v4-replay-20261004\Scripts\python.exe"
$r5_out = "outputs/research_v5/paired_role_diagnostic"
```

These are the actual existing local addresses, not a requirement to create the
same temporary directory elsewhere. Use a compatible interpreter on another
machine. Source/request/schema hashes in replay must still match the sealed run.

## Deterministic checks

```powershell
& $r5_py -m pytest -q tests/research_v5 tests/test_evidence_graph.py tests/test_policy_table_v11.py tests/test_policy_table_v11_obligations.py
```

Observed result: **151 passed**. The earlier unchanged V4 audit separately passed
85 tests and replayed all seven preserved phases without HTTP. See the repository
audit for that historical checkpoint.

The following diagnostics read original labels and saved baselines; they write
only their research output directories. Oracle relations are explicit human
annotations, not model outputs or automatic policy rules.

```powershell
python experiments/research_v5/diagnostics/binary_audit.py
python experiments/research_v5/diagnostics/r0_context_audit.py
python experiments/research_v5/diagnostics/oracle_probe.py
python experiments/research_v5/diagnostics/oracle_roles.py
```

The first script verifies original input/gold hashes. The R0 diagnostic runs the
unchanged current service with network tripwires. It measures its actual guard
behavior, not an inferred full-context R0 transfer. Gold UNKNOWN is never edited;
the alternate V4 process contract is a separate sidecar. valid46 is known
development data.

## Byte-identical model replay

The public tokenizer must already be cached locally. Its SHA256 is
`286acad9b0e27fce778ac429763536accf618ccb6ed72963b6f94685e531c5c7`.
Its pinned public location and acquisition metadata are in the retained provider
preflight. This is a tokenizer file, not model weights. After obtaining the file,
replay is offline:

```powershell
$r5_tokenizer = "$env:TEMP\guardian-v5-tokenizer\286acad9b0e27fce778ac429763536accf618ccb6ed72963b6f94685e531c5c7.json"
& $r5_py tools/replay_v5_diagnostic.py --out $r5_out --tokenizer-file $r5_tokenizer
```

The wrapper relocates only the immutable tokenizer address. It prohibits network
and credential access, verifies source/protocol/request/reservation hashes,
requires byte-identical predictions and unchanged ledger, and restores the live
completion file exactly. The scoped output `.gitattributes` keeps retained JSON
and logs in LF on Windows checkouts. Both server and Windows replay passed.

Expected prediction SHA256:
`4530c2d00cf5899abd8c8c2fdfb45e32ccd52cb5a04d3f84f8bf4ffd01b8bf07`.
Expected ledger SHA256:
`73550ca7ea090176663e83c3b17f5db365e35e28abaa41667cddb065d29391a0`.
Protocol SHA256:
`eab5e5fd6f9fefd675a6341040fa00bf3cf6cef4d79733bf08cbfb34964711bc`.

## Scoring and causal audit

```powershell
python experiments/research_v5/diagnostics/score_pilot.py --out $r5_out
python tools/research_v5_failure_audit.py --out $r5_out
```

These post-hoc tools may read gold, while inference/replay do not. They never
repair raw model replies. The causal audit includes both executed pairs even when
P3 candidate admission fails, and represents the zero fully admitted comparison
as undefined rather than a measured F1. It also exposes the wrong cause of D0's
binary positive. Four successful inference calls charged 72,543 tokens; the
unexecuted longer pair remains a budget stop. No independent holdout or full-valid46
automatic improvement was measured.

Inspect [model results](MODEL_RESULTS.md), [test contrasts](CONTRASTIVE_TESTS.md)
and [final decision](FINAL_DECISION.md) before interpreting any intermediate
score. The next automatic variant, if attempted, must be a separately frozen
experiment; the retained negative phase remains unchanged.
