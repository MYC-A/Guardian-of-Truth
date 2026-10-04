# Frozen next diagnostic: full-context direct vs grounding

Written before provider inference. The earlier audit/oracle phases are preserved
at `de3e4389` and `f2d9a771`. No V4 gold or completed model result is rewritten.

The chosen mechanism combines **relevant mandatory process grounding** with
**role/entity-aware receipt validity**, because offline oracle probes exposed both
a real process FN and a real native-role failure. The general atomic prototype
remains unvalidated and is not substituted into this experiment.

## Additional infrastructure gate

The role view validates unique receipts on the original full event stream first.
It excludes only a uniquely paired read whose supplied alias explicitly points
to another entity. Ambiguous receipts and a later receipt for the same entity
still block the old fact. Original raw sources/indices stay intact; production
code is unchanged. A code-owned date comparison reads the selected native field
and explicit system time. Oracle validation fixes the expired-line native query
even for an incomplete log, because it uses positive evidence rather than absence.
The archived Guardian OR Granite already detects that case; no additional OR FN
recovery is claimed. Artifacts are in `outputs/research_v5/oracle_role_scope`.
22 contract tests pass, including polymorphic read aliases, same-entity supersession,
ambiguous receipts, exception uncertainty and permission/prohibition separation.

## Selection and comparable control

Three **known development** cases are frozen in `valid_diagnostic3_inputs.jsonl`:

1. Banking task003: conditional oracle-supported residual OR FN.
2. Expired telecom line: source-clear FN of the current context-limited R0 service,
   exposing the original native fact validity bug.
3. Banking task057: official negative and archived Granite FP; a request for
   verification must not be interpreted as executed account creation.

Selection uses historical errors and is fully disclosed. This is not random,
independent or hidden testing. No claim about generalization or full-valid46 F1
will be made from three cases. Official gold is read only by a separate scorer
after predictions have been saved. Gold-selected oracle annotations never enter
the model packet.

Fresh D0 directly assesses the **whole current move**; fresh P3 returns relationships
and code checks them. Both receive the same lossless packet, same full original
prompt/response, all current targets, candidate addresses, model, temperature and
one-call output cap. Neither arm silently truncates long sources. Redundant scalar
values/declaration quotations are omitted from the *derived address index*, not
from originals. Models refer to candidate IDs; code owns values, pointers and
relation IDs. This current pilot differs from the historical V4 first-target A0,
so old Gemma cache is not reused as if it were a real-valid46 D0 prediction.

P3 is deliberately narrow: mandatory prior processes and a grounded native date
constraint. It can return ERROR on a checked violation but otherwise returns
UNKNOWN. That limitation and UNKNOWN→0 are scored, rather than interpreting
abstention as certified NO_ERROR. D0 has broader semantic scope. Report both
mechanism coverage and binary correctness; schema admission is not a win.

## Budget and provider preflight

At most six inference HTTP requests, total charged ceiling 100,000 tokens,
temperature 0, output cap 2,500 for both arms, timeout 120 seconds, no retries and
no fallback. Stop on provider error/429. A durable reservation and request snapshot
precede each HTTP call. Finished raw responses, including usage and actual returned
model, are saved; interrupted or unknown-usage requests retain their reservation.
Budget stops remain explicit UNKNOWN and incomplete pairs are excluded from
comparative conclusions, without deleting their receipts.

Use pinned `ministral-14b-2512` only if live read-only model metadata confirms its
availability/context. This is a fresh **same-model** pilot of both arms; it is not
a cross-model comparison with historical Gemma. A public pinned tokenizer is used
for a conservative reservation of twice the full serialized request tokenization
(including schema/metadata), plus output cap and 1,024 template slack. This does
not assert exact identity with the hosted tokenizer. The tokenizer file is pinned
by SHA256 `286acad9b0e27fce778ac429763536accf618ccb6ed72963b6f94685e531c5c7`, from the
[Mistral-owned model repository](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512/blob/d1002e707ddf4eab6f17da795287fb9d0d334aed/tokenizer.json).
Only the tokenizer is downloaded; no weights or GPU deployment are needed.

The provider GET and tokenizer download are separately logged read-only network
operations, not inference usage. Protocol preparation hashes code, inputs, full
packets, requests and budget reservations before any inference. Model metadata,
context preflight failures and unavailable models are saved without retry.

## Stop/advance rule

First verify E2 infrastructure, then inspect P3 relation meaning, entity roles,
timing, exception scope, native values and final binary outcome against the fresh
D0. Report paired deltas and costs on exactly the common executed cases. No
automatic architectural win is declared if D0 already detects the same errors,
P3 merely abstains on the negative, or grounding maps a nonmandatory tool to a
requirement. Expand to a new independently labeled family holdout only after a
useful incremental signal; otherwise preserve the negative/inconclusive pilot
and keep the full atom architecture on hold.
