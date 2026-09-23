# Rechecks after the rejection audit

Branch: `codex/recheck-experiments`. Run commands from the repository root.
Each experiment has its own folder and writes `config.json`, per-case records,
and `summary.json` to a **new** output directory. Existing output directories
are never overwritten. The labels are joined only for scoring; prompts and
tool selection never receive `gold`.
If a remote run stops, repeat its exact command with `--resume`; the runner
checks the frozen config and continues from completed per-case records.

## Environment

```bash
python -m pip install -e .
python -m pip install clingo openai pytest
python -m pytest tests/test_recheck_2026.py tests/test_cycle2_x5.py tests/test_cycle2_x5_execution.py -q
python scripts/recheck_remote_preflight.py
```

The local Granite run additionally needs the server's compatible PyTorch,
Transformers and Accelerate installation and a local Granite Guardian 3.3 8B
model directory. Mistral runs need `MISTRAL_API_KEY` in the environment;
the client can also read the existing
`/mnt/data/guardian/secrets/mistral.env` file, the server workspace's
`.mistral.env`, or a path named by
`MISTRAL_ENV_FILE`. Environment variables take precedence. `MISTRAL_MODEL`
defaults to `ministral-14b-latest`. No key is written into artifacts. Record
the served model and package versions on the
server alongside the run outputs.

Before full remote runs, use `--limit 2` for agent/holistic, `--limit 10` for
the FP reviewer, `--deep 2` for Q, and `--limit-cases 1` for S7 in separate smoke output directories. Inspect the
raw per-case outputs, then use new directories for full runs.

## Runs

1. **Typed tool selection** (`agent/`). The fixed and agent arms receive the
   same cases, tool catalog, grounded card IDs and maximum **executed** tool
   calls. An invalid action does not consume a tool call but is recorded.
   Graph paths and card IDs must match exactly; there is no fallback to card 1.
   Each planner step sees recent history and prior observations. The controller
   may promote a checked `violated` card; a `safe` card is only a candidate for
   further FP review, because the local replay showed that whole-response
   clearance from safe cards lost six true positives.

   ```bash
   python -m experiments.recheck_2026.agent.run --arm fixed --max-tools 4 --out outputs/recheck_2026/fixed_server_01
   python -m experiments.recheck_2026.agent.run --arm agent --max-tools 4 --out outputs/recheck_2026/agent_server_01
   ```

   Compare `n_executed_tools`, exact evidence status, card decisions, latency,
   and final labels on the same IDs. The agent's free-form proposed label is
   never used as a verdict. The fixed local replay on public46 currently
   reproduces pgjudge TP23/FP16/FN0; it produces 16 safe-card *candidates*
   and no automatic 1→0 flips.

2. **Discriminating questions** (`questions/`). Reads the saved S6/S9
   divergences but selects at most one exact-fragment candidate per case,
   spreading disagreement types. The already verified divergence fragment is
   used as the exact source quote; model-generated quote copying is logged
   separately and cannot block the paired test.
   A separate semantic check is recorded as probabilistic, never as Clingo
   proof. The same judge, system prompt, model and bounded case context are
   used with and without the proposed interpretation. Only paired valid
   outputs enter the delta.

   ```bash
   python -m experiments.recheck_2026.questions.run --deep 12 --out outputs/recheck_2026/q_server_01
   ```

   `--dry-run` lists the 12 selected IDs without API calls. Source divergences
   are from viewed public46, so this is a mechanism probe, not an independent
   contest score.

3. **Granite suspicion support** (`claim_verifier/`). Reuses the 103 frozen
   S7 suspicion statements and supplies both context and target response as
   documents. Two separate criteria are tested. Under `groundedness`,
   `risk=yes` means the statement is not supported, while `risk=no` means
   probabilistic source support. Under `custom_violation`, the official
   [`custom_criteria` template](https://huggingface.co/ibm-granite/granite-guardian-3.3-8b)
   asks whether this exact alleged violation is
   supported; `yes` means probabilistic support for the violation. Neither
   score is a formal proof. `old_reinterpreted` is a no-GPU diagnostic from
   the old, differently bounded input, not a matched model ablation.

   ```bash
   python -m experiments.recheck_2026.claim_verifier.run --dry-run --out outputs/recheck_2026/s7_old_reinterpreted
   python -m experiments.recheck_2026.claim_verifier.run --mode groundedness --model-path /path/to/granite-guardian-3.3-8b --out outputs/recheck_2026/s7_groundedness_01
   python -m experiments.recheck_2026.claim_verifier.run --mode custom_violation --model-path /path/to/granite-guardian-3.3-8b --out outputs/recheck_2026/s7_custom_01
   ```

   Existing S7 records cover 23/46 cases, not the entire public46 set.

4. **Holistic context selection** (`holistic/`). Same Mistral judge, prompt,
   budget and cases. Only the 10k context selection changes: first 10k versus
   head/tail 10k. This isolates the previous truncation confound.

   ```bash
   python -m experiments.recheck_2026.holistic.run --out outputs/recheck_2026/holistic_server_01
   ```

5. **C2 → X5 handoff** (`c2_x5/`). Uses the already saved frozen C2 proposals,
   exact response spans and the same X5 solver for C0/C2. CRLF is canonicalized
   to LF in all paired arms to match the saved C2 source offsets. Missing
   action predicates remain UNKNOWN. The local 46-case run is already complete:
   44 schema-valid pairs, two exclusions, X5 TP7/FP0 in both arms, zero binary
   changes, and 12 `PROVED_NO_ERROR` → `UNRESOLVED` changes. C2's positive span
   extraction score did **not** become an end-to-end gain under this binder.

   ```bash
   python -m experiments.recheck_2026.c2_x5.run --out outputs/recheck_2026/c2_server_replay_01
   ```

6. **FP reviewer** (`fp_review/`). Replaces the missing v3 implementation with
   a fully versioned eight-operation critic. It sees the pgjudge allegation,
   exact grounded cards, bounded case and response. Every cited card must be
   refuted by an exact source quote before it proposes a 1→0 change. It also
   asks about other errors, so its clearance is **probabilistic**, not proof.
   Cases with no cited cards or a missing policy quote keep the base label.

   ```bash
   python -m experiments.recheck_2026.fp_review.run --dry-run --out outputs/recheck_2026/fp_review_dry
   python -m experiments.recheck_2026.fp_review.run --out outputs/recheck_2026/fp_review_server_01
   ```

7. **FP reviewer replay gate** (`fp_replay/`). Replay the new critic's JSONL or
   the original v3's recovered per-case predictions against frozen pgjudge
   labels and gold. Input JSONL rows must contain `id`, `label`, and
   `evidence`: a list of `{source, quote, operation}`. Every changed label
   needs an exact source quote and one of the eight named operations in
   `fp_replay/run.py`. This checks ID coverage and provenance, **not** the
   semantic correctness of the quote's interpretation.

   ```bash
   python -m experiments.recheck_2026.fp_replay.run --candidate outputs/recheck_2026/fp_review_server_01/records.jsonl --out outputs/recheck_2026/fp_review_replay_01
   ```

## Existing controls and limits

- Hotel v2 format and structural self-check are already in
  `outputs/searh_23/contrast_hotel_v2/`; preserve those artifacts as frozen
  controls. A new synthetic hotel score is not an independent holdout.
- A1's 120 original source-offset proposals are not present in this checkout.
  Its raw proposals must be restored before a source quote/offset repair can
  be replayed. The superz `e3a_a1r_posthoc` file is a different experiment.
- Q and S7 do not claim formal semantic validation; their outputs explicitly
  keep that boundary. The pending v3 FP score is not independently reproduced
  until its per-case data passes the replay gate.
- Run any final selector **once** on a previously unseen, grouped and
  response-type-stratified evaluation set. Public46 has been viewed repeatedly.
