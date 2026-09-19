# Guardian current handoff — 2026-09-20

This checkpoint records the actual state before the current agent context ends.
It supplements `WORKLOG.md`, `EXPERIMENT_MATRIX.md`, and `DECISIONS.md`.

## Safe local state

- Worktree: `A:\GIS_Загрузки\Guardian Offline Research 20260919`
- Branch: `research/offline-20260919`
- Published remote tip before this checkpoint: `83bbbb2`.
- Current local tip: `cc947041f6346ed5c902222d0a28b087cdec322d`.
- Do not switch, clean, reset, or delete the older server checkout. Experiments use
  separate detached worktrees.
- Commits added in the latest phase:
  - `620dfa0`: exact source-grounding contract.
  - `01e7ebf`: gold-free grounding runner and hashed manifest.
  - `1aa88a9`: 16 MiB CSV field limit in the competition CLI.
  - `b487f7e`: frozen AgentHallu DEV/LOCKED split and DEV adapter.
  - `83bbbb2`: Mistral Architecture A0/A1 runner.
  - `cc94704`: direct-entrypoint bootstrap for the src-layout runner.

## What was verified

### Competition CLI

- Published checkout `d4baa86` on the server processed the complete 46-row
  label-free CSV, including a 233,104-character field.
- `--backend none`: exit 0, 46 predictions and 46 audit records, 0.916 s wall,
  37,444 KiB maximum RSS, no GPU. Post-hoc metrics: TP12 FP0 FN11 TN23,
  F1 .685714.
- Input SHA-256: `9f6f5fc496d25e80a008adb589ddcb30fb681d0da131fb83c37fc220c5089e93`.

### Mistral direct BASE

- Server configuration exists and was checked without printing its values:
  `/mnt/data/guardian/secrets/mistral.env`, non-empty `MISTRAL_API_KEY`, and
  `MISTRAL_MODEL=ministral-14b-latest`.
- Full public46 run completed from detached checkout
  `/mnt/data/guardian/Guardian-research-d4baa86`.
- Output:
  `/mnt/data/guardian/Guardian-research-d4baa86/outputs/research_mistral_base_20260920/full46_direct/`.
- 46 rows, 43 API requests, 7 explicit fallbacks, 12 mechanical decisions,
  27 semantic decisions, 1,591,920 input characters, 239.95 s wall.
- Post-hoc metrics: TP20 FP10 FN3 TN13, F1 .754717. It gains eight TP over the
  exact baseline and adds ten FP. Exact OR is identical because Mistral already
  marks all exact TP positive.
- SHA-256: predictions `c208e9d70ef1ea8a2e1d7f6a927374d6dd937e42df4936b25c8f19f46d82b871`;
  audit `6cf3fbc6ba81c44a6b61c15973c12b4d0fc67a73cb68658497c93a36c09651eb`;
  run `2066d6c1478cd1a5a5574ac86ca677f2057302100a0b6e995540c44ea584b7d2`;
  comparison `db7baa35d2443482356532c834005fd7b0fb63b2878dd3985ab30e844e00385b`.
- This is PUBLIC_SEEN and API-dependent. It is the fixed flat BASE reference for
  A0/A1, not an offline final solution.

### Architecture A runner

- A0/A1 runner implements strict JSON schemas, temperature 0, append-only JSONL,
  resume, model/usage/latency/status capture, input/config/schema/prompt hashes,
  and exact source grounding for A1. Formal state stays `UNRESOLVED`.
- Combined Architecture A and AgentHallu focused tests: 25 passed at `83bbbb2`.
- The direct src-layout entrypoint defect found on the server is fixed at
  `cc94704`; Architecture A tests are now 20 passed, including a subprocess
  from a temporary cwd without `PYTHONPATH`.
- Remote isolated worktree:
  `/mnt/data/guardian/Guardian-research-a-83bbbb2`, detached at the older
  `83bbbb2` until it is safely refreshed.
- A0 three-row smoke PASS:
  `/mnt/data/guardian/Guardian-research-a-83bbbb2/outputs/research_mistral_a_20260920/public46_smoke_A0/`.
  Three of three records are OK; records SHA
  `652fed61299165fe3ad221a2e85493f0d9011a9d893156eabe027949fe049eb3`;
  manifest SHA `a446a77595867378294ec5bf78eb7c06d72b07a6a560a61aa88c8b4af0bc1bcf`.
- A1 three-row smoke was running when this checkpoint was written. Its manifest
  had journaled 2/3 OK records, two requests, `finished:false`, and empty stderr;
  no full run was started. Output path:
  `/mnt/data/guardian/Guardian-research-a-83bbbb2/outputs/research_mistral_a_20260920/public46_smoke_A1/`.
  Check its process and manifest before starting anything else. The runner is
  resumable; do not overwrite the namespace.

### AgentHallu external DEV

- Source revision `9ffe8bc888feaf15d89833f4b0e3c4697f44acc1`, 693 trajectories.
- Frozen normalized-question split: DEV 488, LOCKED 205. Nine duplicate-question
  groups remain wholly inside one split. Manifest SHA
  `302c7d339bc99126d2334ba7cd5360f81a1e6dc6b4022dba8ba727f2e8f9c470`.
- DEV has 319 positive and 169 negative trajectories. Label-free input SHA
  `342f695b4732d4b46b4b1d2ea7b9ff2f5ebfc32cee242563089694420d860bf3`.
- The adapter filters by frozen manifest before reading source files; LOCKED
  content remains unopened. Six tests and real artifact cross-validation pass.
- Exact baseline on DEV predicts zero for all rows: TP0 FP0 FN319 TN169, F1 0;
  predictions SHA `fdf3829cf507f366c7a22aae4cecf95f510d1b87bda601577feaae708fe4fb29`.

## Existing model/server resources

- A10 with 23,028 MiB VRAM; GPU was idle before Architecture A API runs.
- Main venv: `/mnt/data/guardian/venv/bin/python`.
- GLiNER venv: `/mnt/data/guardian/gliner2_env/bin/python`.
- Cached/installed: Granite Guardian 3.3 8B, NuExtract3-W4A16,
  GLiNER2.5 multi v1, BGE-M3, BGE reranker v2 M3, and NLI DeBERTa v3 base.
- `/mnt/data` has ample space. `git-lfs` is installed.
- Docker, tmux, and screen are absent. Long SSH work must stay in a foreground
  PTY session or use a verified scheduler/setsid wrapper. A prior nohup launch
  did not survive the SSH session.
- The directory named `mistral-7b-instruct-v0.3-c170c708` is an abandoned,
  incomplete download and must not be treated as a usable model.

## What remains, in order

1. Check the running A1 smoke. Seal and record it; do not overwrite its output.
2. Push `cc94704`, then safely refresh or create another detached server
   worktree. Re-run only the entrypoint smoke needed to prove the fix.
3. Run public46 A0 and A1 sequentially with the same label-free input and fixed
   model. Join labels only afterward. Record TP removed/lost, FP removed/added,
   grounding admission rate, latency, requests, tokens, and all hashes.
4. If A1 improves the FP/TP tradeoff over A0, freeze a representative AgentHallu
   DEV slice and run A0 then A1. Keep LOCKED unopened until prompts, schemas,
   thresholds, and selector are frozen.
5. Implement and test A2 only if A1 leaves useful but disputable grounded
   suspicions. A2 must name a concrete missing premise or counterfact and exact
   source words; one review plus one targeted repair maximum.
6. Start controlled B0/B1/B2 on the same fixed DEV inputs using the existing
   NuExtract/GLiNER caches and Mistral API. Do not call the historical semantic
   pipeline a completed B comparison.
7. Select a local model only after A/B behavior is measured, then repeat the
   promising arm locally. The final competition entrypoint must work offline.
8. Run Docker build/cold-start on a Docker-capable host and measure image size,
   wall time, RAM/VRAM, and fresh-input inference.

## Manual action requested from the user

Nothing needs to be downloaded manually for the current A0/A1/B research:
the API key/model setting, model caches, Python environments, dataset, and disk
space are present.

The following external actions remain useful:

1. Rotate the ModelScope access tokens that were exposed earlier in the private
   tool transcript by a malformed diagnostic command. No token is stored in Git
   or project artifacts. The Mistral key was not printed in this phase.
2. Provide a Docker-capable host or install Docker on a suitable machine for the
   final container build and cold-start test. The prepared server and local
   machine currently have no Docker CLI.
3. Do not manually continue the partial Mistral 7B download. The exact local
   model and quantization should be chosen after A0/A1 and B results. Downloading
   a large candidate now risks duplicating an unsuitable model. Once selected,
   download it into a new versioned directory under `/mnt/data/guardian/models/`
   and record revision, license, file hashes, size, and context limit.

## Resume commands

Check Architecture A processes and artifacts without printing secrets:

```bash
ssh guardian-modelscope 'ps -eo pid,etime,cmd | grep run_mistral_suspicions.py | grep -v grep; find /mnt/data/guardian/Guardian-research-a-83bbbb2/outputs/research_mistral_a_20260920/public46_smoke_A1 -maxdepth 1 -type f -printf "%f %s\n" 2>/dev/null | sort'
```

The server key and model must always be loaded in the same remote Bash process:

```bash
source /mnt/data/guardian/secrets/mistral.env
```

Never print that file or copy it into the repository.
