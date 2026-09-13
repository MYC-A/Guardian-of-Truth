"""Independent executable binding fixture, not a real-provider contract.

Authoritative fixture rules:
* store.read returns a complete snapshot only for status=observed.
* archive/delete/restore v1 return noop when the state is already satisfied;
  noop guarantees no new mutation. completed guarantees the named mutation.
* v2 completed writes are non-idempotent action occurrences, even if state agrees.
* timeout/accepted may have an effect, never guarantee completion or no-effect.
* rename is observable through subsequent reads; names do not replace stable IDs.
* source completeness is an explicit fixture premise; partial search is not absence.

Only source event JSON enters the candidate adapter. Internal reference knowledge
and latent timeout application flags must never enter the candidate input.
"""

from copy import deepcopy
import hashlib
import json


PROVIDER = "vnext-binding-fixture"
SCHEMA = {"type": "object", "properties": {"record_id": {"type": "string"}, "new_name": {"type": "string"}}}
SCHEMA_SHA256 = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
TOOLS = ("store.read", "store.search", "store.archive", "store.unarchive", "store.delete", "store.restore", "store.rename")


def candidate_input(executed):
    """Explicit application-source projection; never expose reference knowledge."""
    return {
        "events": deepcopy(executed["events"]),
        "query": deepcopy(executed["query"]),
        "history_complete": executed["history_complete"],
        "authority": "EXPLICIT_EXECUTABLE_FIXTURE_PREMISE_NOT_REAL_PROVIDER",
        "contracts": {
            "provider": PROVIDER, "versions": ["v1", "v2"],
            "tool_names": list(TOOLS), "schema": deepcopy(SCHEMA),
            "schema_sha256": SCHEMA_SHA256,
            "documentation": __doc__,
        },
    }


def execute_fixture(value):
    states = deepcopy(value.get("initial", [
        {"record_id": "Q-701", "name": "Alex", "exists": True, "archived": False},
        {"record_id": "Q-702", "name": "Blair", "exists": True, "archived": False},
    ]))
    for index in range(value.get("extra_entities", 0)):
        states.append({"record_id": "EXTRA-" + str(index), "name": "Unrelated-" + str(index), "exists": True, "archived": False})
    by_id = {item["record_id"]: item for item in states}
    events, knowledge = [], []

    def emit(actor, kind, body, tool=None, version="v1", correlation=None, requestor=None):
        event = {"event_id": "e" + str(len(events)), "actor": actor, "kind": kind, "body": deepcopy(body),
            "tool": tool, "provider": PROVIDER if tool else None, "version": version if tool else None,
            "schema_sha256": SCHEMA_SHA256 if tool else None, "transport_call_id": correlation, "requestor": requestor}
        events.append(event)
        return event

    def read_snapshot(status="observed", actor="assistant", malformed=False):
        correlation = "fixture-call-" + str(len(events))
        tool = "store.read" if status == "observed" else "store.search"
        emit(actor, "call", {}, tool, correlation=correlation)
        rows = deepcopy(states) if status == "observed" else []
        body = '{"items":' if malformed else {"status": status, "items": rows}
        return emit("tool", "result", body, tool, correlation=correlation, requestor=actor)

    read_snapshot()
    for step in value.get("steps", []):
        if step.get("kind") == "text":
            emit(step.get("actor", "assistant"), "text", step["text"])
            continue
        operation, actor = step["operation"], step.get("actor", "assistant")
        version = step.get("version", "v1")
        if operation in {"read", "search"}:
            read_snapshot("observed" if operation == "read" else "partial", actor, step.get("malformed", False))
            continue
        entity = step.get("record_id", "Q-701")
        record = by_id.get(entity)
        arguments = {"record_id": entity}
        if operation == "rename":
            arguments["new_name"] = step["new_name"]
        tool, correlation = "store." + operation, "fixture-call-" + str(len(events))
        call = emit(actor, "call", arguments, tool, version, correlation)
        status = step.get("status", "completed")
        supported = tool in TOOLS and version in {"v1", "v2"} and record is not None
        desired = {"archive": ("archived", True), "unarchive": ("archived", False),
            "delete": ("exists", False), "restore": ("exists", True)}.get(operation)
        if status == "completed" and supported and desired and version == "v1" and record[desired[0]] == desired[1]:
            status = "noop"
        apply = supported and (status == "completed" or status in {"timeout", "accepted"} and step.get("latent_apply", False))
        if apply:
            if desired:
                record[desired[0]] = desired[1]
            elif operation == "rename":
                record["name"] = step["new_name"]
        result = emit("tool", "result", {"status": status}, tool, version, correlation, actor)
        knowledge.append({"call_event_id": call["event_id"], "result_event_id": result["event_id"],
            "actor": actor, "operation": operation, "record_id": entity,
            "completion": "TRUE" if supported and status == "completed" else "FALSE" if supported and status == "noop" else "UNKNOWN"})
    return {"events": events, "reference_knowledge": knowledge,
        "history_complete": value.get("history_complete", True),
        "query": deepcopy(value["query"])}


def reference_query(executed):
    """Formal typed-query gold from the independent fixture, not candidate code."""
    query, events = executed["query"], executed["events"]
    reads = [event for event in events if event["kind"] == "result" and event["tool"] == "store.read"
        and isinstance(event["body"], dict) and event["body"].get("status") == "observed"]
    last_result = next((event for event in reversed(events) if event["kind"] == "result" and event["tool"] in {"store.read", "store.search"}), None)
    selector = query.get("entity", {"mode": "id", "value": "Q-701"})
    records = [record for event in reads for record in event["body"]["items"]]
    ids = {record["record_id"] for record in records if record["record_id"] == selector["value"]} if selector["mode"] == "id" else {
        record["record_id"] for record in (reads[-1]["body"]["items"] if reads else []) if record["name"] == selector["value"]}
    if not ids:
        return {"truth": "UNKNOWN", "bindings": [], "candidate_set_complete": False}
    values = []
    for entity in sorted(ids):
        kind = query["kind"]
        relevant = [item for item in executed["reference_knowledge"] if item["record_id"] == entity
            and item["operation"] == query.get("operation") and item["actor"] == query.get("actor", "assistant")]
        truth = "UNKNOWN"
        if kind == "FIELD_AT_LAST_READ":
            if last_result and last_result["tool"] == "store.read" and isinstance(last_result["body"], dict):
                rows = [item for item in last_result["body"]["items"] if item["record_id"] == entity]
                answers = {json.dumps(item[query["field"]], sort_keys=True) == json.dumps(query["expected"], sort_keys=True)
                    if query["field"] in item else None for item in rows}
                truth = "TRUE" if answers == {True} else "FALSE" if answers == {False} else "UNKNOWN"
        elif kind == "ALIAS_HISTORY":
            seen = any(record["record_id"] == entity and record["name"] == query["alias"] for record in records)
            truth = "TRUE" if seen else "FALSE" if executed["history_complete"] else "UNKNOWN"
            if query.get("expected", True) is False:
                truth = {"TRUE": "FALSE", "FALSE": "TRUE", "UNKNOWN": "UNKNOWN"}[truth]
        elif kind in {"METHOD_COMPLETION_COUNT", "METHOD_HISTORY", "CAUSE_OF_METHOD"}:
            if kind == "CAUSE_OF_METHOD":
                relevant = [item for item in relevant if item["call_event_id"] == query["call_event_id"]]
                truth = relevant[0]["completion"] if len(relevant) == 1 else "UNKNOWN"
                if query.get("expected", True) is False:
                    truth = {"TRUE": "FALSE", "FALSE": "TRUE", "UNKNOWN": "UNKNOWN"}[truth]
            else:
                known = sum(item["completion"] == "TRUE" for item in relevant)
                uncertain = any(item["completion"] == "UNKNOWN" for item in relevant) or not executed["history_complete"]
                if kind == "METHOD_COMPLETION_COUNT":
                    truth = "UNKNOWN" if uncertain else "TRUE" if known == query["expected"] else "FALSE"
                else:
                    occurs = "TRUE" if known else "UNKNOWN" if uncertain else "FALSE"
                    truth = occurs if query.get("expected", True) else {"TRUE": "FALSE", "FALSE": "TRUE", "UNKNOWN": "UNKNOWN"}[occurs]
        else:
            raise ValueError("unsupported independent typed fixture query")
        values.append({"record_id": entity, "truth": truth})
    distinct = {item["truth"] for item in values}
    return {"truth": next(iter(distinct)) if len(distinct) == 1 else "UNKNOWN", "bindings": values,
        "candidate_set_complete": executed["history_complete"] and last_result is not None
            and last_result["tool"] == "store.read" and isinstance(last_result["body"], dict)}
