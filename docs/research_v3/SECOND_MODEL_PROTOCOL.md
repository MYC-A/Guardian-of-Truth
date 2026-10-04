# Second-model replication

After primary inference produced its first development responses, freeze an
additional bounded replication with `gemma4:31b` through Ollama. Same source commit,
fixtures, gold, prompts, ID wire and fact runtime. No tuning to heldout labels.
Run A0/A2/A3 only; A1 remains the original-model control. The second model is not
silently substituted into an architectural comparison.

Limits: 140 one-attempt requests and 350,000 conservatively charged tokens,
120 seconds/request. A first HTTP/transport error disables this provider for the
entire phase; there is no automatic waiting, retry or switch to a different model.
This is a separate ceiling from the primary 360/1,000,000 allocation; combined
actual usage is reported, and no purchase or model download is authorized.

The reason for replication is a development-only observation: the primary model
produced valid source IDs but introduced an unsupported "immediate predecessor"
interpretation of "before" in its first contextual response. Its local lowerer
also confused policy anchors with native evidence and wrote payload-container
paths instead of pointers inside native JSON. These are different errors, so a
model control is more informative than assuming a single architectural fix.

The complete primary arms remain unchanged. No development response is replaced,
repaired or hidden. Source-address improvements and semantic understanding must
be reported separately.
