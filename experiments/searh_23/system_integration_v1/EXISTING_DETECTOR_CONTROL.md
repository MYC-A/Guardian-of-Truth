# Existing-detector control on frozen full trajectories

Input renderer and both split JSONL files were committed before this control's
model calls. The renderer receives only frozen `*_inputs.json`; neither gold nor
reviewed policy/goal annotations enter it. It writes the normal public-style
system policy, complete tool catalog, user and ordered assistant/tool history,
and target assistant reply. Structured documented contracts in the catalog are
included as text so the old detector sees the same declarations available to
the experimental Step 2 compiler. Every rendered case passed catalog and
call/result JSON parsing before evaluation (21 dev, 20 sealed).

Run `scripts/predict.py` unmodified with `--backend mistral --mode graph`,
server `MISTRAL_MODEL`, threshold 0.5 and `--unknown-label 0`, writing audit
and run-report files. The binary CSV fallback label is a technical 0; score
an audit row with `used_fallback=true` as UNKNOWN. Score ERROR and NO_ERROR
only when the detector actually decided them. No prompt/threshold changes
after inspecting dev or sealed results. This suite is synthetic and authored
by the same project, so even a favorable comparison is not external transfer.
