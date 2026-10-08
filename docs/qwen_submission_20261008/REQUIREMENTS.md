# Guardian submission: checked requirements, 2026-10-08

Primary sources:

- https://dsworks.ru/champ/aij26-guardian
- https://dsworks.ru/champ/aij26-guardian/data
- https://dsworks.ru/champ/aij26-guardian/comments (all 1199 extracted lines read)
- https://gitverse.ru/api/repos/gitverse/AIJ/raw/branch/master/AIJourney2026-rules-ru.pdf

Rules PDF SHA256: `9462490004b977e6d99a157c02effdb577b767dcf90a69e7765b78b8e8b5e3df`.
Pages 8–10 specify source archive root containing pyproject.toml, model/, src/,
scripts/predict.py. Platform runs `pip install .`, then
`python scripts/predict.py --input INPUT --output OUTPUT`; one id,label per input.
Predict from prompt,response only; explanation/label are reference fields.
Limit: 30 minutes; upload strictly below 40GB; ten successful submissions total.
PDF footnote13 defines success as all validation stages passed, execution within
limits and accepted output. Footnote14 defines a failed solution narrowly as
providing no prediction because of a critical execution error. Do not promise
that every nonzero exit or partial-output timeout is free of submission cost.
Choose three final solutions with the platform checkboxes by October20 inclusive;
otherwise the platform selects the three with the highest recorded metric.

The PDF calls this a Docker image but describes an unpacked source archive.
The registry-based Docker instructions on page 11 belong to the SECOND task.
For Guardian, an October 4 request for registry references remains unanswered.
We prepare a ZIP for upload and a separate Dockerfile for local verification.

Organizer clarifications supersede the stale H100 line in the PDF:

- Sep 7 / Sep 21: A100, specifically one A100 80GB.
- Sep 16: 40GB is the archive limit, GPU memory limit80GB.
- Sep 28: ZIP39.93GB expanding to41.01GB is accepted.
- Sep 22: model weights are NOT preloaded; include them.
- Sep 21: use transcript formatting in actual examples.
- Sep 8: do not include a directory named metrics.
- Aug 31: external public APIs unavailable during evaluation.

Community advice (not an organizer guarantee): ZIP succeeds where tar.gz fails;
files at archive root; directories755/files644; Parquet output is safest even at
a .csv output path. Organizer Sep7 says both CSV/Parquet supported, but several
participants subsequently needed Parquet. Organizer blanda7513 also supplied an
actual PyArrow Parquet-reader failure on Sep1. Default output is therefore
Parquet; changing only the filename to .csv is not a format conversion. Native
Python/loader/llama binaries require755, ordinary files644, directories755.

Unresolved officially: whether30min includes initialization, whether public and
private have separate budgets, dependency installation networking and exact
preinstalled environment. Bundle offline dependencies; benchmark cold start and
the whole input. Do not rely on participant-reported vLLM version.
The Sep16 answers about separate runs and installation networking are from a
participant, not the organizer. The Oct5 question about whether "one tool call
at a time" means a call-count violation per recorded turn is also unanswered.
It cannot certify an unconditional count rule or experimental gold.

The score-tie thread reports548 evaluated rows (130positive/418negative), not a
confirmed full input size. Equal confusion matrices do not prove equal answers.
The current leaderboard changed after the Oct5 numbers; do not use that cohort
as a guaranteed runtime bound.

Review provenance: cached comments HTML875629 bytes,
SHA256 `a5d1eb70f0deb251c1a46c7ac9493fe43915d00a34cb6c9c301a0f22f2edb4db`;
656 visible-text lines and all1199 web-extracted lines inspected. Full procedure,
stage diagnostics and source authority are in PLATFORM_UPLOAD_REVIEW.md.
The community uploader attachment was not retrieved or executed; no code-safety
claim is made for it. Publication on the comment page is not an organizer audit.

Baseline choice: measured Qwen B2, no unconditional Granite OR, no experimental
ABC/idcheck hard enforcement, no incomplete thinking arm. Historical valid46
13TP/1FP/10FN F1 .7027; external+tau2h+holdout2 diagnostic191 labels117/7/24
F1 .8830. These are development diagnostics, not contest predictions.
