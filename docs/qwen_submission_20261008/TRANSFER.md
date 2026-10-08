# Artifact transfer: protocol and current limits

The artifact is unchanged:30,447,402,247 bytes, SHA256
`46317b9570c76833771f14468e045e642f9802c7b516fba8234fefa23a493835`.
Transfer tools are operator-only and not included in the submission runtime.

The first SSH stream failed after675,837,867 bytes. The initial HTTP downloader
was stopped after exposing an unbounded wait for other large responses on the
first connection failure. Its partial is not ready and is not adopted without a
valid ledger. A second attempt was stopped before network data while CPython's
Windows truncate manually wrote zeroes even on a sparse file. Native NTFS
SetFilePointerEx/SetEndOfFile was verified onA:30GB logical allocation took0.03s.

The current phase is `guardian-qwen-b2-20261008-r3.zip`. It has a durable chunk
ledger, sparse allocation, strict206/Content-Range/length/encoding checks,
per-range absolute timeout and visible received/completed-byte counters. Resume
rehashes all completed chunks and only downloads missing ones. A hard-killed
owner leaves a lock that must be checked against its recorded PID before removal.

An initial transient CDN header timeout stopped this phase cleanly after9.3MB
of durable chunks. The explicit resumed protocol permits up to3 attempts/range
and up to256 additional retry calls cumulatively in its ledger. Only transient
network errors/502/503/504/clean premature EOF are eligible. Auth/quota errors,
invalid range headers, local write failures and final hash failures are not.
There is no unlimited retry/polling loop and no new model inference.

## Identical public weight source

Verified Hugging Face repository `ggml-org/Qwen3.8-27B-GGUF`, exact revision
`71bc7b627595dc8a91039addd9c791ae548d6747`, file `Qwen3.8-27B-Q8_0.gguf`:

- LFS size28,595,763,648 bytes;
- LFS content SHA256
  `aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1`;
- Xet hash `8d07619d143cafd92b0fed6ec2b0ad50117f69d87543f75fa1f81e5a4accfbbf`
  explains the server's different blob filename; it is not the content SHA.

The server ZIP central directory and local header independently give stored
model data offset927171, bytes28,595,763,648 and CRC32 2659452010. These model bytes
are fetched from the public HTTPS mirror; prefix927171 bytes and suffix
1,850,711,428 bytes come from the original server ZIP. The full mapped file is
still verified against the original archive SHA, then each manifest entry/CRC.

The frozen mapping is `receipts/artifact_source_segments.json`. Public mirror
requests receive no Authorization. HTTPS redirects are restricted to the declared
HF host suffixes; the private server token is only used at its original endpoint.
Tokens are outside Git and the archive. Signed redirect URLs are not published.

## Remaining deliverable

Server ZIP is complete. LocalA transfer is still incomplete until its status
reads READY and an actual final file exists. Preallocated logical size, a running
PID, a successful tiny probe or local tests do not establish completion of30GB.
Do not upload a partial or stop/delete the server while it holds the only full
prepared ZIP in volatile `/dev/shm`.
