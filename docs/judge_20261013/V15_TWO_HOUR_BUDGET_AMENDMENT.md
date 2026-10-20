# V15: user time budget amendment, before native optimization

The user reduced the remaining GPU budget to one, possibly two hours. Replace
the waiting V15 v3 controller with v4, preserving the old snapshot and its
zero-optimization receipt. V13 TRAIN-only mining is already running and is the
only remaining data dependency. Do not repeat V12 or wait for its offbox audit.

Freeze a total deadline 7200 seconds after this amendment is launched. Training
maximum 5400 seconds, evaluation reserve 900 seconds, minimum start reserve 3600
seconds. These are ceilings, not a prediction. The source recipe, hard-pair
gates, weights, loss, epoch count and final-checkpoint rule remain unchanged.
Do not shorten or trim input data, lower the 16-error gate or change families
based on evaluation results to fit the budget. If the complete epoch cannot
finish, preserve committed checkpoints and explicitly report a partial epoch.

V16 final regression may use only time left within the same two-hour deadline;
it receives no extension and must use the final v4 candidate. All older waiting
controllers are stopped before replacement so they cannot launch duplicate GPU
work. Native train data and GPU work remain separate from protected evaluation.
