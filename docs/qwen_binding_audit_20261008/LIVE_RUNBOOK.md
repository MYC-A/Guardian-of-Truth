# Local Qwen phases — 2026-10-08

The GPU model is supervised as `guardian-qwen-binding-20261008` at localhost8081.
Do not restart it or change settings during a frozen phase. Existing management
services and other worktrees are untouched.

Phase2 process `guardian-qwen-binding-pilot2-20261008`, PID4682 at start, runs in
`/workspace/guardian/repos/Guardian-qwen-binding-20261008`, frozen HEAD43578208.
Expected172 records (86 inputs ×2 modes). Its immutable source view/extraction
contract is described in PHASE2_PROTOCOL.md.

Phase3 `guardian-qwen-source-completion-pilot-20261008` has a supervised waiting
wrapper, **not concurrent model inference**. The wrapper waits for the exact
phase2 process to terminate, then checks its full unique expected ID/mode set.
Incomplete phase2 refuses automatic continuation. It then starts the command
in PHASE3_PROTOCOL.md from the separate worktree
`/workspace/guardian/repos/Guardian-qwen-source-completion-20261008`, HEAD213ba578.
That preserves phase2's frozen HEAD. Expected92 result records,53 unique wires.

Logs: `/workspace/guardian/logs/qwen_binding_20261008_pilot2.{log,err}` and
`qwen_source_completion_20261008.{log,err}`. Model logs use
`qwen_binding_20261008_server.{log,err}`. Phase caches, request bodies and durable
ledgers live under each worktree's `outputs/qwen_binding_pilot/<phase>/`.

Status checks are bounded and infrequent; a wrapper RUNNING state alone does
not mean phase3 inference started. Check its actual manifest/records/log.
Never restart because an observation timed out. Freeze output phases separately,
fetch them without `.phase.lock`, and retain failures.

Offline score after full fetch:

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONDONTWRITEBYTECODE='1'
python -X utf8 scripts/qwen_binding_pilot_score.py --records <phase2/records.jsonl> --output <NEW_phase2_score.json>
python -X utf8 scripts/qwen_source_completion_score.py --records <phase3/records.jsonl> --output <NEW_phase3_score.json>
```

Scorers refuse overwriting an output. Neither one authenticates provider caches
by itself: preserve and inspect manifests, raw request hashes and attempt ledgers.
Pending independent source review is explicit in reports. A partial score is
coverage telemetry, not an accepted improvement. Defaults remain unchanged.
