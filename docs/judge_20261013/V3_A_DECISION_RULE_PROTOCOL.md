# V3 A: decision rules, frozen before calculation

Recorded 2026-10-18, branch research/v3-threshold-data-lora-20261019, base
7bc4a0b42da02b9351bbe6eed7cfb06e302811b1. Seed 20261019. Research only.
Do not change production profiles, defaults, ZIP or submit to the platform.
The attachment V3_USER_REQUEST.md and subsequent user noise amendment govern.

## Current implementation

- scripts/predict.py:1-4 delegates to guardian_truth.cli; the judge submission
  path is scripts/judge_submission.py, publish():432-441.
- submission/JUDGE_OPEN_REVIEW40.json:5,8,20 selects open review, max_exact and .40.
  Repository DEFAULTS .30 is not the reported .40 platform profile.
- src/guardian_truth/judge/blind_review.py:428-448 takes the row-wise maximum
  of available finite exact overall/final. Absent final does not erase overall.
- src/guardian_truth/judge/decision.py:22-34: all hard findings positive;
  target=round(.40 * number of scored rows), hard scored rows consume quota;
  remaining rows sort by (-score, original index). Hard unscored rows remain
  positive outside that scored denominator. Full-coverage saved data has no
  unscored rows. Use this implementation, including Python ties-to-even rounding.

## Data, groups and uncertainty

Only saved regression_r1/rows.csv scores max(overall,final), original hard
findings, regression_seen labels/inputs and conversation metadata. No GPU.
seen397 and real191 (ext_tau2, hold_tau2h, hold_holdout2) are reported separately;
valid46 is a regression subset, never independent evidence. Group by the
existing conversation identifier (not the per-turn prompt-proxy group).
Exact source IDs, row ordering, input hashes and file SHA256 are recorded.
All these sets were previously viewed; intervals do not make them fresh tests.

Prevalence grid .12,.15,.20,.25,.35,.50 and the cohort's original prevalence.
For each cohort generate one fixed paired importance-resampled batch of its
original size, with replacement, weights p/pi for positive and (1-p)/(1-pi)
for negative. Target p is the sampling probability, not an exactly forced class
count; report actual batch prevalence. The original-prevalence point uses the
actual original rows, preserving the published baseline exactly. Duplicates are
separate batch positions; original order resolves equal scores reproducibly.
All rules see exactly the same batch. Resample conversation groups1000 times
with replacement, keep all their turns (including TN-only groups), then apply
the same class-weighted batch resampling to the resulting pool. Recompute quota
and unlabeled EM on every batch. Paired 2.5/97.5 percentiles for F1 differences
against R0. Degenerate one-class bootstrap pools are counted and omitted, not
silently replaced. Calibration/thresholds remain the frozen cross-fit estimates
inside this bootstrap: intervals are conditional on those fitted estimates and
do not include refit/model-selection uncertainty. No independent significance
claim across overlapping397/191/46 cohorts.

## Closed candidates and leakage boundaries

R0 current .40 quota + hard; R1 score>0 + hard.
R2 score>t + hard. R3 Platt calibration plus Saerens EM batch prior adjustment,
then adjusted probability>tau + hard. No other candidate or ensemble.

Use five outer GroupKFold folds (shuffle=True, random_state=20261019) on397.
No conversation crosses folds. In each outer training partition use five inner
group folds for parameter choice. R2 threshold grid -32..32 inclusive, step.25;
maximize mean inner validation F1 over the seven prevalence points (with native
prior as the last), averaged equally across folds and points. Ties choose the
smallest threshold. R3 Platt LogisticRegression(C=1, solver=lbfgs, max_iter=1000,
no class weighting); fit only inner training scores/labels. Tau grid .05..95,
step.025, same objective and smallest-tau tie rule. Fit final Platt on outer
training after selecting tau. Each held-out outer fold is an unlabeled deployment
batch for EM. Its score likelihood ratios are used when subsequently drawing
cohort prevalence batches; combine cross-fit likelihood ratios to estimate one
batch prior. Record this cross-fit approximation. No outer gold enters Platt,
threshold choice or EM, except evaluation/reweighting after predictions.
For R2 inner folds do not fit a model, only estimate threshold utility; this
equals threshold choice on outer training cross-validation predictions.

EM: clipped likelihood ratios derived from calibrated probability divided by
the calibration-training prior odds. Initialize at that prior; update the mean
adjusted posterior until change<1e-9 or1000 iterations, clip prior to[1e-6,1-1e-6].
No evaluation labels enter prior estimation. Record convergence and prior error
for diagnostics only. The label-shift assumption may fail under domain shift.
Reference: Saerens et al.2002, https://doi.org/10.1162/089976602753284446.

Do not fit separate favorable policies for191 and397. All quality comparisons
use held-out outer-fold choices from the single397 cross-fit. A prospective
full397 fit may be serialized only after selecting a rule; it is not its own
unbiased quality estimate. Freeze implementation/training scope before E.

## Noise: user amendment accepted before results

First check existing evidence by model/runtime separately. For35B use the
strict arm of dev_replay_r1/r2/r3, matching text, token hashes and source config;
never compare different note arms as if they were repeats. For4B separately
inventory the standalone vanilla/disabled/original base audit; an adapter is
not a repeat of base. Report subset and runtime limitations.
For matching repeat pairs sd_obs=std(score differences,ddof=1)/sqrt(2), pooled
over the three unordered run pairs, with mean difference, max absolute difference
and number of matching inputs. This is empirical scorer noise on the observed
subset, not a full generation/cold-start repeat of the production pipeline.

Always test sd in{.05,.1,.25,.5,1.0} and additionally measured35B sd_obs.
200 Gaussian perturbations per sd, same random draws for all rules. Freeze
thresholds/calibration; recompute quota, Platt outputs and EM from noisy scores.
Report changed-label share, F1 change and rows within +/-2sd of threshold;
for R0 use the boundary non-hard ranked score; R3 map its batch probability
threshold back to each fold's score scale. Hard decisions cannot flip.
Report cohorts and prevalence points separately, mean and95th percentile of
changed-label share. Criterion uses mean share across200 draws, must hold for
both main cohorts at every prevalence point; no max/min selection after results.

## Acceptance, fixed

(a) At p=.12 AND .20: F1-R0>=.03 and lower paired CI>0 on BOTH397 and191.
(b) At p=.50 and original: F1-R0>=-.01 on BOTH main cohorts.
(c) If35B sd_obs exists, mean decisions changed<=.03 for both cohorts/all points.
If not, at EVERY declared sd candidate flip share<=R0 share+.01 on both cohorts/
all points; status must explicitly say relative only, absolute stability unknown.
Select simplest passing R1<R2<R3; if none pass retainR0. A positive research
decision does not itself authorize production changes before F.

Required tests: original397 R0 F1=.7512437810945274; grouped folds disjoint;
hard/missing/tie behavior; synthetic calibrated label-shift EM prior error<.02.
Save START, DONE even for failure, exact score rows, batches/folds/seeds, bootstrap
draw summaries and hashes. No retrospective grids, criteria or fold changes.
