# RUNBOOK v2
```bash
export PYTHONPATH=$PWD:$PWD/src
python -m pytest -q tests/test_universal_repair_v2.py tests/test_universal_repair.py      # 19 + 21
# offline replay of the committed live R_fix runs with v2 code (0 misses)
python -X utf8 -m experiments.universal_repair.run --set lb3_long --rep 2 --arm R_fix --with-live-cache --runs-dir ../universal_repair_v2/runs_offline
python -X utf8 -m experiments.universal_repair.v2_replay --out /tmp/replay.json
python -X utf8 -m experiments.universal_repair.judge_v2 recheck_v1          # invariants over v1 judgements, no calls
python -X utf8 -m experiments.universal_repair.judge_v2 report              # from committed v2 judgements
python -X utf8 -m experiments.universal_repair.holdout_v2                   # frozen vs adjudicated-v2 holdout metrics
python -X utf8 -m experiments.universal_repair.funnel_v2
# live (MISTRAL_API_KEY; one process at a time; cached by exact key)
python -X utf8 -m experiments.universal_repair.judge_v2 run [--attempt 1 --sample 80]
python -X utf8 -m experiments.universal_repair.oracle_probe [--neg]
# public opt-in profile (default unchanged)
guardian-review INPUT.jsonl --repair r_fix [--offline --cache-dir DIR]
```
