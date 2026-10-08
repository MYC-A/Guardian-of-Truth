# Same-object query: unmeasured next hypothesis

The ongoing compact pilot shows an observed failure mode: both modes may select
an arbitrary entry of a related list. Hiding the current argument cannot prevent
this semantic binding error. This observation motivates a separate prototype,
not an amendment to the running phase or an accuracy conclusion from partial data.

`experiments/guardian_binding/relational.py` asks for a quoted user criterion,
native object field, literal string, EQ/SUFFIX operation and direct projection
field. Code searches native JSON objects and records both leaves in the SAME
object. It refuses arbitrary list projections, ambiguous objects, unsupported
user quotes and scan gaps. No tool name, domain or benchmark-specific fields
are hardcoded. Both blind and visible request constructors use the same schema.

The model still chooses semantic field roles and interprets the request. Literal
matching of a negated request can execute correctly while proposing the wrong
meaning; a regression explicitly demonstrates this boundary. Every relation
remains SOURCE_RELATION_ONLY, binding/applicability UNRESOLVED, and any mismatch
needs the separate policy verifier. No new universal code certificate exists.

Supported capability is deliberately explicit: direct same-object fields and
string exact/suffix comparison. Multi-hop joins, arithmetic, aliases, temporal
state and absence are unsupported. Multiple equal projected values in distinct
objects remain ambiguous; an unrelated malformed result currently blocks a
unique lookup conservatively. These restrictions can lose recall and must be
measured before considering an integration.

18 parser/source-bound contrast tests passed. No inference or binary F1 has
been measured for this prototype. It remains disconnected from defaults and
the two frozen live phases. New inference requires a separate frozen protocol.
