# Independent review of the checked startup diagnostic — 2026-10-11

Code baseline: `96db8c8b4f3431cd336edf9f95057ea9ef72cd17`, branch
`fix/qwen-startup-probe-v3-checked-20261011`. This review concerns a diagnostic,
not a change to the B2 inference contract or a claim of GPU readiness.

Separate code and packaging reviewers checked the source and archive boundaries.
Findings were confirmed by executable regressions rather than reviewer agreement.

## Findings and resolution

- The original global weight-suffix assertion rejected legitimate runtime `.pth`
  hooks. Weight exclusion now applies to the model directory only. Runtime files
  and original ZIP modes/compressed records are preserved.
- The proposed driver bridge was erased by the original launcher. It is removed.
  The actual compact platform probe already passed CUDA driver initialization with
  that launcher. Driver-path failure is not established as the original cause.
- Initial Linux CI reproduced three cases where cleanup returned before killed
  descendants stopped. The supervisor now keeps the unreaped leader as the group
  anchor, waits for live group members to disappear, and reports bounded cleanup
  failure explicitly. It does not relax the descendant assertions.
- Main now retains dependency-check cleanup errors as well as engine cleanup
  errors. Either blocks a subsequent engine startup.
- Health alone no longer implies a successful startup test: served model identity,
  context limit and the completion response structure are checked separately.
- Logs, HTTP reads, individual phases and the whole diagnostic have explicit
  bounds. Dependency checks and engine variants use separate fresh caches.

The cleanup reviewer found no blocking issues in `96db8c8b`. Targeted Windows
review tests: 47 passed, 6 Linux-specific skips. The separate packaging reviewer
checked actual ZIP inventory, original `.pth` hooks, launcher/Python/ELF modes and
generated payload hashes; the final rebuild is tied to its own receipt.

## Validation evidence

- Full selected local suite: **156 passed, 10 skipped**. Sparse-checkout omissions
  initially caused four missing-import failures; expanding the existing Git tree
  resolved them without runtime code changes.
- Linux CI for the final code: **81 passed**, including real Linux descendant
  cleanup tests (one pytest configuration warning, no failed tests):
  https://github.com/MYC-A/Guardian-of-Truth/actions/runs/38092325305
- The first CI failure is preserved in GitHub Actions:
  https://github.com/MYC-A/Guardian-of-Truth/actions/runs/38091825016
- CI success receipt: `diagnostic/linux-ci-96db8c8b.json`.
- Full Linux test log: `diagnostic/linux-ci-96db8c8b.log`.
- Actual compact platform log: `diagnostic/compact-loader-platform.log.gz`;
  extracted facts: `diagnostic/compact-loader-result.json`.

Dummy initialization differs from checkpoint loading and may have different
temporary allocations and random FP8 scales. No real GPU dummy startup was run
locally. The original `VLLM_START_FAILED` cause remains unknown until an inner
engine traceback is observed. No prediction, quality or private-set timing claim
follows from these CPU tests or from a future dummy startup success.
