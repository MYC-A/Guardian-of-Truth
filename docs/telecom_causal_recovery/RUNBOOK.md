# Offline runbook

Run from `Guardian-telecom-causal-recovery-20261004` research worktree. Inference
source is frozen at `fd8efa9f`; later docs/tools do not alter it. Existing Python
3.13.7 replay environment uses Pydantic 2.13.5/tokenizers 0.22.2; source/gold audit
uses pandas/pyarrow in the existing system Python. No API key is needed offline.

```powershell
$env:PYTHONPATH = "$PWD;$PWD\src"
$r5_py = "$env:TEMP\guardian-v4-replay-20261004\Scripts\python.exe"
$tc_out = "outputs/telecom_causal_recovery/v1"
$tc_tokenizer = "$env:TEMP\guardian-v5-tokenizer\286acad9b0e27fce778ac429763536accf618ccb6ed72963b6f94685e531c5c7.json"
& $r5_py -m pytest -q tests/telecom_causal_recovery tests/research_v5 tests/test_evidence_graph.py tests/test_policy_table_v11.py tests/test_policy_table_v11_obligations.py
& $r5_py tools/replay_telecom_causal_recovery.py --out $tc_out --tokenizer-file $tc_tokenizer
python tools/score_telecom_causal_recovery.py --out $tc_out
```

Use an equivalent environment path elsewhere. The public tokenizer must already
be cached; its exact hash is verified. No weights are downloaded. Replay prohibits
all HTTP and credential access, enforces frozen source/protocol/input/body/
reservation/cache integrity, reproduces predictions byte-for-byte, leaves the
ledger unchanged and restores live completion metadata exactly. The output
`.gitattributes` preserves LF on future Windows checkouts.

Scoring reads only original id/label columns plus separately saved human causal
annotations. It never rewrites raw replies. Each semantic assessment has its
own reason and original source references. Synthetic controls have no official
binary gold. Missing model replies remain unmeasured, with explicit BUDGET_STOP.
`cause_correct` means explanatory content; complete success additionally requires
the emitted decision and all requested criteria. See annotations for this explicit
post-hoc definition, which avoids declaring A/C fully successful.

Do not run `prepare` over the retained output directory or launch `run`/`auto`
to repeat this phase. The durable ledger protects prior attempts, but a new
experimental version needs a new frozen protocol, not edits to these replies.
The automatic result is a source plan plus unexecuted final request; no semantic
AUTO result exists. Original preparation was independently audited and committed
before inference, then executed in a detached server checkout of that commit.

Integrity hashes are in [offline_replay.json](../../outputs/telecom_causal_recovery/v1/offline_replay.json).
Original source SHA256:
`6050a0d6ba08d6fc74890c6b528d11503f81939e1f0b0c9d7056b02059845339`.
Protocol SHA256:
`fa91925acd5e64dfd04d2ed1c9084bd374a85bbf207e6d2594e00a05de910d37`.
Final total: 6 inference HTTP, 45,089 known=charged tokens, zero unknown usage,
retries or fallback. Independent subagent code review and separate logic audit
are retained in the reports.
