"""Application adapter for the pinned executable fixture, NOT real tool semantics.

No independent reference implementation/knowledge/labels are imported. The T1
catalogue below is an explicit application interpretation of the fixture source.
It is checked against its exact documentation hash, never inferred from names.
"""

from guardian_truth.vnext.identity_aliases_v2 import IdentityDeclaration
from guardian_truth.vnext.integrity import canonical, digest
from guardian_truth.vnext.source_envelope_v4 import SourceEnvelope, SourceFrame
from guardian_truth.vnext.temporal_queries_v4 import MethodDeclaration, SnapshotDeclaration, TemporalQuery
from guardian_truth.vnext.tools import ConditionalGuarantee, ContractRegistry, EffectSpec, FieldCondition, TrustedContract
from guardian_truth.vnext.types import Span, ToolIdentity

PROVIDER = "vnext-binding-fixture"
SCHEMA_SHA256 = "681ed38ff53bbe1f024af06d01db5760a3fe169bd1fdc0e7102bb4f12e690ab3"
DOC_SHA256 = "53ab038a7ea48309b3b6087da67b5a134eedbc69e32b574d2e48e8c7322bb833"
NAMESPACE = "explicit-binding-fixture-records"
PROVENANCE = "application T1: pinned independent executable binding fixture documentation sha256=" + DOC_SHA256


def fixture_identity(name, version="v1"):
    return ToolIdentity("store." + name, PROVIDER, version, SCHEMA_SHA256)


def make_context(projected):
    if set(projected) != {"events", "query", "history_complete", "authority", "contracts"}:
        raise ValueError("safe fixture input projection required")
    if projected["authority"] != "EXPLICIT_EXECUTABLE_FIXTURE_PREMISE_NOT_REAL_PROVIDER":
        raise ValueError("explicit fixture authority required")
    metadata = projected["contracts"]
    if metadata["provider"] != PROVIDER or metadata["schema_sha256"] != SCHEMA_SHA256 or digest(metadata["documentation"]) != DOC_SHA256:
        raise ValueError("unknown fixture contract source; no T1 transfer")
    if digest(metadata["schema"]) != SCHEMA_SHA256:
        raise ValueError("fixture schema content/identity mismatch")
    prompt, frames = "", []
    for row in projected["events"]:
        if row["event_id"] != "e" + str(len(frames)):
            raise ValueError("contiguous source event identities required")
        body = row["body"] if isinstance(row["body"], str) else canonical(row["body"]).decode()
        span = Span("prompt", len(prompt), len(prompt) + len(body))
        prompt += body + "\n"
        tool = ToolIdentity(row["tool"], row["provider"], row["version"], row["schema_sha256"]) if row["tool"] else None
        frames.append(SourceFrame(span, span, row["actor"], row["kind"], tool,
            row["transport_call_id"], row["requestor"]))
    envelope = SourceEnvelope(prompt, "", tuple(frames), "executable-binding-source", "v2",
        "synthetic application-owned source event metadata; not real-provider traces",
        projected["history_complete"], "complete supplied executable fixture history" if projected["history_complete"] else None)
    snapshots = tuple(SnapshotDeclaration(IdentityDeclaration(fixture_identity(name), NAMESPACE,
        ("items", "*"), "record_id", ("name",), PROVENANCE, full_alias_snapshot=name == "read"),
        (FieldCondition("result", ("status",), '"observed"'),)) for name in ("read", "search"))
    contracts, methods = [], []
    effects = {"archive": ("archived", "true"), "unarchive": ("archived", "false"),
        "delete": ("exists", "false"), "restore": ("exists", "true"), "rename": ("renamed", "true")}
    for operation, (predicate, value_json) in effects.items():
        for version in ("v1", "v2"):
            identity = fixture_identity(operation, version)
            contracts.append(TrustedContract(identity, (), (), (predicate,),
                (ConditionalGuarantee((FieldCondition("result", ("status",), '"completed"'),),
                    (EffectSpec("record_id", predicate, value_json, True),)),),
                (EffectSpec("record_id", predicate, value_json, False),),
                (FieldCondition("result", ("status",), '"noop"'),),
                "timeout/accepted do not guarantee completion or no-effect", "result occurrence only",
                "v1 satisfied-state noop; v2 completed write is a new occurrence", PROVENANCE))
            methods.append(MethodDeclaration(identity, NAMESPACE, "record_id", ("record_id",), predicate, PROVENANCE, value_json))
    raw_query = projected["query"]
    selector = raw_query.get("entity", {"mode": "id", "value": "Q-701"})
    kind = raw_query["kind"]
    expected = raw_query.get("expected", True)
    if kind == "ALIAS_HISTORY":
        if expected is not True:
            raise ValueError("fixture adapter currently exposes positive observed-alias queries only")
        expected = raw_query["alias"]
    operation = raw_query.get("operation")
    query = TemporalQuery(kind, selector["mode"], selector["value"], NAMESPACE, "record_id", canonical(expected).decode(),
        (raw_query["field"],) if "field" in raw_query else (), raw_query.get("actor", "assistant"),
        tuple(fixture_identity(operation, version) for version in ("v1", "v2")) if operation else (),
        ("record_id",) if operation else (), effects[operation][0] if operation else None, raw_query.get("call_event_id"),
        method_effect_value_json=effects[operation][1] if operation else None)
    return envelope, snapshots, ContractRegistry(tuple(contracts)), tuple(methods), query
