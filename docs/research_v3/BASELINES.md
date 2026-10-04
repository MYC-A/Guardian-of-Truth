# Historical baseline reproduction

Command, with this worktree's `src` on `PYTHONPATH`:

```powershell
python experiments/searh_23/evidence_graph_v1/probe.py replay --out outputs/searh_23/evidence_graph_address_probe_20261004
```

The saved frozen protocol/source/schema hashes verify; replay executes no HTTP.
The replay reproduces 47 unique responses per address arm, offset INVENTORY 2/31,
offset EFFECT 16/16, quote INVENTORY 0/31, quote EFFECT 11/16 and 37/37 UNKNOWN
current native calls in each arm. `git status --short` after replay is clean:
tracked artifacts reproduce byte-for-byte under local Pydantic 2.10.3.
The 94 saved requests cost 399,533 provider tokens in the original experiment;
the new replay adds zero tokens. Old reply hashes cannot answer new V4 requests.

System V2 full-auto and single-step oracle results are available in its committed
JSON and report. They are retained as historical evidence, not regenerated through
its old client: that client loads a nonlocal credential/cache path at import and
contains retries contrary to the user's current no-wait/no-retry preference.
The V4 runner instead uses a durable one-attempt ledger. The previous historical
sealed outcomes are already disclosed and are not a fresh independent reserve.

The new A1 arm uses the unchanged graph prompts, schema and admission, on the
same new source inputs as A0/A2/A3. Historical 37-call abstention rates are not
compared as if they were scores on these new 31 call targets and one prose target.
