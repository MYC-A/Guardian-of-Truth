# Transcript integration, 14.10.2026

The single-pass judge now uses `guardian_truth.transcript` through its existing mechanical API.
The modules originate from the user's attached proposal; the judge still makes one model call
per row and writes output in its existing CSV/Parquet-by-suffix format. The proposed standalone
`io.py` was not adopted. Strong and weak findings are model hints, never automatic positives.

Changes to the proposal:

- Accept the previous third positional `analyze` argument without promoting unknown references.
- Recognize both `- tool — description` and `- tool: description`. Unknown catalog syntax disables
  the completeness claim. Unsupported/duplicate parameter schemas are not used to prove violations.
- Error results have a separate source kind. Their values do not establish successful grounding or
  arithmetic support. Occurrence categories never establish semantic applicability to an entity.
- Preserve signed amounts: a negative amount is not a match for its positive counterpart.
- Judge only assistant calls, keeping user/device calls separate. Multiple calls and mixed text/call
  turns remain hints, with an explicit requirement to assess their effect on the outcome.
- Preserve the previous narrow expired-contract gate, reading successful assistant-tool results.
- Use the parsed system boundary for context trimming and prefix grouping, including attributed
  role headers and CRLF. Large policies may still be shortened when they cannot fit the token cap.
- Add all required transcript modules to the ZIP builder's replacement inventory.

`GUARDIAN_JUDGE transcript` logs format/diagnostic counters and analysis errors. `stage_input.jsonl`
and `decisions.jsonl` retain features and hint tiers; decisions also bind prompt and response SHA256
to the original row position and id. Stage failures keep the initial mechanical output, with explicit
fallback sources. No additional model calls, calibration changes or training are introduced.

Validation includes the attached parser tests, regressions for the discovered failures, partial-score
output with duplicate/literal ids, and importing the integrated modules from a verified tiny ZIP.
These CPU checks do not establish model F1, A100 kernel compatibility or full-set runtime. The public
valid46 audit is development evidence only; do not turn its zero false positives into a guarantee.

Run the unchanged GPU comparison with the new hints and inspect coverage, exact-score probing,
policy trimming and elapsed whole-script time before treating this build as ready for submission.
