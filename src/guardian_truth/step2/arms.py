"""Evidence-source arms A-J (section 22 of the brief).

Every arm answers the same interface: given a TrajectoryCase, produce

  * candidate facts (with per-arm provenance of HOW they were proposed),
  * verified facts (witnessed by the deterministic verifier), and
  * ungrounded established facts (arms A/B only — the leakage diagnostic).

Arms never use tool names as proof. Arm E masks names entirely; arms D/F/G/I
are pure code over payload structure and contracts; arms A/B/C are LLM
diagnostics of what happens WITHOUT deterministic grounding.

  A  name+description only          (leakage baseline, unwitnessed)
  B  description+schema             (unwitnessed)
  C  description+schema+result      (unwitnessed proposals, counted as established)
  D  result-only structural         (deterministic, no docs at all)
  E  narrow LLM proposer name-blind (proposals)
  F  structured effect classifier   (deterministic ontology rules)
  G  result->fact extractive mapper (deterministic, conservative)
  H  E + deterministic witness      (only witnessed facts enter the ledger)
  I  explicit oracle contracts      (deterministic, ORACLE track)
  J  <base> + later read confirmation (temporal post-layer over any base)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .ledger import FactLedger, Proposition, ProbeAnswer
from .proposer import parse_proposal
from .result_types import (ASYNC_VALUES, STATE_KEYS, classify_payload,
                           json_path_get, scalar_to_json)
from .types import (Authority, EffectClass, EffectStrength, FactEvent,
                    LedgerKind, Provenance, Truth, WorldFact)
from .verifier import (CallEvent, CandidateFact, Rejected, ResultEvent,
                       TrajectoryCase, VerifiedFact, verify_candidate)

DETERMINISTIC_ARMS = ("D_result_only", "F_structural", "G_extractive", "I_contract")
LLM_ARMS = ("A_name_desc", "B_desc_schema", "C_full", "E_nameblind", "H_hybrid")
POST_LAYERS = ("J_read_confirmation",)
ALL_ARMS = ("A_name_desc", "B_desc_schema", "C_full", "D_result_only",
            "E_nameblind", "F_structural", "G_extractive", "H_hybrid",
            "I_contract")
BASE_ARMS = ALL_ARMS


@dataclass
class ArmOutput:
    arm: str
    case_id: str
    verified: list[VerifiedFact] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    ungrounded: list[dict] = field(default_factory=list)   # arms A/B/C pseudo-facts
    proposal_meta: dict = field(default_factory=dict)      # result_type/effect_class per call
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"arm": self.arm, "case_id": self.case_id,
                "verified": [v.as_dict() for v in self.verified],
                "rejected": [r.as_dict() for r in self.rejected],
                "ungrounded": self.ungrounded,
                "proposal_meta": self.proposal_meta,
                "errors": self.errors}


# --------------------------------------------------------------- utilities ----

def _mask_names(case: TrajectoryCase) -> tuple[dict, dict]:
    """Mask tool names with opaque labels assigned by FIRST APPEARANCE in the
    trajectory (not alphabetically), so that an opaque rename of the catalog
    produces a byte-identical prompt: name-blindness is invariant by
    construction, and the rename check verifies the implementation only."""
    catalog = {t["name"]: dict(t) for t in case.tools}
    order: list[str] = []
    for event in (*case.calls, *case.results):
        if event.tool not in order:
            order.append(event.tool)
    for name in catalog:
        if name not in order:
            order.append(name)
    mask = {}
    for i, name in enumerate(order):
        masked = f"tool_{i:02d}"
        mask[name] = masked
        catalog[name]["name"] = masked
        # descriptions that literally name the tool would leak; mask mentions
        catalog[name]["description"] = catalog[name].get("description", "").replace(name, masked)
    return catalog, mask


def _pair(case: TrajectoryCase):
    """Yield (call, result) pairs in trajectory order, strictly paired."""
    by_id = {r.call_id: r for r in case.results}
    for call in case.calls:
        result = by_id.get(call.call_id)
        if result is None:
            continue
        yield call, result


def _catalog(case: TrajectoryCase) -> dict:
    return {t["name"]: t for t in case.tools}


# ------------------------------------------------------- deterministic arms ---

def _echo_values(payload, depth: int = 0):
    """Yield every string value in the payload (bounded depth) for echo checks."""
    if depth > 3:
        return
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, str):
                yield value
            else:
                yield from _echo_values(value, depth + 1)
    elif isinstance(payload, list):
        for value in payload[:8]:
            if isinstance(value, str):
                yield value
            else:
                yield from _echo_values(value, depth + 1)


def _entity_from_echo(call: CallEvent, result: ResultEvent) -> tuple[str, str] | None:
    """Bind entity via argument-value echo in the result (entity/value §16)."""
    if not isinstance(call.payload, dict):
        return None
    echoed = set(_echo_values(result.payload or {}))
    best = None
    for arg_name, arg_value in call.payload.items():
        if not isinstance(arg_value, str) or not arg_value:
            continue
        if arg_value in echoed and arg_name.endswith("_id"):
            if best is None or len(arg_name) > len(best[0]):
                best = (arg_name, arg_value)
    return best


def _top_level_scalars(payload: dict) -> list[tuple[str, Any]]:
    """Top-level scalar leaves only — facts cite exact report fields."""
    out = []
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out.append((f"$.{key}", value))
    return out


def arm_D_result_only(case: TrajectoryCase) -> ArmOutput:
    """Structure only: no docs, no ontology. Read-shaped results yield
    OBSERVED facts via entity echo; everything else stays UNKNOWN."""
    out = ArmOutput("D_result_only", case.case_id)
    for call, result in _pair(case):
        rtype = classify_payload(result.payload)
        out.proposal_meta[call.call_id] = {"result_type": rtype.value}
        if result.payload is None:
            continue
        if rtype.value == "OBSERVATION":
            echo = _entity_from_echo(call, result)
            if echo is None:
                continue
            entity_field, entity_value = echo
            etype = _entity_type(entity_field)
            for path, value in _top_level_scalars(result.payload):
                if str(value) == entity_value:
                    continue  # entity echo, not a distinct fact
                rendered = scalar_to_json(value)
                if rendered is None:
                    continue
                candidate = CandidateFact(
                    predicate=f"{etype}.{path[2:]}", entity_type=etype,
                    entity_field=entity_field, entity_value=entity_value,
                    value_json=rendered, json_path=path,
                    strength=EffectStrength.OBSERVED,
                    effect_class=EffectClass.READ, is_observation=True)
                verdict = verify_candidate(case, call, result, candidate)
                if isinstance(verdict, VerifiedFact):
                    out.verified.append(verdict)
                else:
                    out.rejected.append(verdict)
    return out


def _predicate_from_path(path: str, entity_type: str) -> str:
    """$.a.status -> {entity_type}.status : facts are namespaced by entity type."""
    body = path.lstrip("$")
    parts = [p for p in body.split(".") if p]
    leaf = parts[-1].split("[")[0] if parts else path
    return f"{entity_type}.{leaf}" if leaf else path


def _entity_type(entity_field: str) -> str:
    base = entity_field[:-3] if entity_field.endswith("_id") else entity_field
    return base or "entity"


def arm_F_structural(case: TrajectoryCase) -> ArmOutput:
    """Deterministic ontology rules over result shape (no docs, no names):
    OBSERVATION -> read facts; BUSINESS_STATE -> self-reported state facts;
    ASYNC_ACCEPTED -> REQUESTED/INITIATED facts; SUCCESS_ACK -> nothing."""
    out = ArmOutput("F_structural", case.case_id)
    for call, result in _pair(case):
        rtype = classify_payload(result.payload)
        out.proposal_meta[call.call_id] = {"result_type": rtype.value}
        if result.payload is None:
            continue
        echo = _entity_from_echo(call, result)
        entity_field, entity_value = echo if echo else (None, None)
        if rtype.value == "OBSERVATION" and echo:
            out.verified.extend(_observation_facts(call, result, entity_field,
                                                   entity_value))
        elif rtype.value == "BUSINESS_STATE" and echo:
            etype = _entity_type(entity_field)
            for path, value in _top_level_scalars(result.payload):
                # entity-echo fields restate the id, not a distinct fact
                if str(value) == entity_value:
                    continue
                rendered = scalar_to_json(value)
                if rendered is None:
                    continue
                async_val = isinstance(value, str) and value.strip().lower() in ASYNC_VALUES
                strength = (EffectStrength.INITIATED if async_val
                            else EffectStrength.EXECUTED)
                candidate = CandidateFact(
                    predicate=f"{etype}.{path[2:]}",
                    entity_type=etype,
                    entity_field=entity_field, entity_value=entity_value,
                    value_json=rendered, json_path=path, strength=strength,
                    effect_class=EffectClass.UPDATE)
                verdict = verify_candidate(case, call, result, candidate)
                if isinstance(verdict, VerifiedFact):
                    out.verified.append(verdict)
                else:
                    out.rejected.append(verdict)
        elif rtype.value == "ASYNC_ACCEPTED" and echo:
            etype = _entity_type(entity_field)
            for path, value in _top_level_scalars(result.payload):
                leaf = path[2:]
                if not (leaf in STATE_KEYS or leaf.endswith("_status")
                        or leaf.endswith("_id")):
                    continue
                rendered = scalar_to_json(value)
                if rendered is None:
                    continue
                if str(value) == entity_value:
                    continue
                candidate = CandidateFact(
                    predicate=f"{etype}.{leaf}",
                    entity_type=etype,
                    entity_field=entity_field, entity_value=entity_value,
                    value_json=rendered, json_path=path,
                    strength=EffectStrength.REQUESTED,
                    effect_class=EffectClass.REQUEST)
                verdict = verify_candidate(case, call, result, candidate)
                if isinstance(verdict, VerifiedFact):
                    out.verified.append(verdict)
                else:
                    out.rejected.append(verdict)
        # SUCCESS_ACK / FAILURE / EMPTY / MALFORMED -> deliberately nothing
    return out


def _observation_facts(call, result, entity_field, entity_value) -> list:
    facts = []
    etype = _entity_type(entity_field)
    for path, value in _top_level_scalars(result.payload or {}):
        if str(value) == entity_value:
            continue
        rendered = scalar_to_json(value)
        if rendered is None:
            continue
        candidate = CandidateFact(
            predicate=f"{etype}.{path[2:]}",
            entity_type=etype,
            entity_field=entity_field, entity_value=entity_value,
            value_json=rendered, json_path=path,
            strength=EffectStrength.OBSERVED,
            effect_class=EffectClass.READ, is_observation=True)
        verdict = verify_candidate(None, call, result, candidate)
        if isinstance(verdict, VerifiedFact):
            facts.append(verdict)
    return facts


def arm_G_extractive(case: TrajectoryCase) -> ArmOutput:
    """Conservative extractive mapper: read tools -> all observation facts;
    mutation tools -> ONLY explicit post-state fields (new_*, status) with
    entity echo; generic success proves nothing."""
    out = ArmOutput("G_extractive", case.case_id)
    for call, result in _pair(case):
        rtype = classify_payload(result.payload)
        out.proposal_meta[call.call_id] = {"result_type": rtype.value}
        if result.payload is None:
            continue
        echo = _entity_from_echo(call, result)
        if echo is None:
            continue
        entity_field, entity_value = echo
        if rtype.value == "OBSERVATION":
            out.verified.extend(_observation_facts(call, result, entity_field, entity_value))
        elif rtype.value in ("BUSINESS_STATE", "ASYNC_ACCEPTED"):
            etype = _entity_type(entity_field)
            for path, value in _top_level_scalars(result.payload):
                leaf = path[2:]
                # only fields whose NAME declares post-state semantics
                if not (leaf.startswith("new_") or leaf in STATE_KEYS):
                    continue
                if str(value) == entity_value:
                    continue
                rendered = scalar_to_json(value)
                if rendered is None:
                    continue
                async_val = isinstance(value, str) and value.strip().lower() in ASYNC_VALUES
                strength = (EffectStrength.REQUESTED if rtype.value == "ASYNC_ACCEPTED"
                            else EffectStrength.INITIATED if async_val
                            else EffectStrength.EXECUTED)
                candidate = CandidateFact(
                    predicate=f"{etype}.{leaf}",
                    entity_type=etype,
                    entity_field=entity_field, entity_value=entity_value,
                    value_json=rendered, json_path=path, strength=strength,
                    effect_class=EffectClass.UPDATE)
                verdict = verify_candidate(case, call, result, candidate)
                if isinstance(verdict, VerifiedFact):
                    out.verified.append(verdict)
                else:
                    out.rejected.append(verdict)
    return out


def arm_I_contract(case: TrajectoryCase) -> ArmOutput:
    """ORACLE track: explicit documented postconditions, deterministically
    evaluated. No contract -> UNKNOWN (never 'sounds like a mutation')."""
    out = ArmOutput("I_contract", case.case_id)
    contracts = case.oracle_contracts or {}
    for call, result in _pair(case):
        contract = contracts.get(call.tool)
        out.proposal_meta[call.call_id] = {"contract": bool(contract)}
        if not contract:
            continue
        rtype = classify_payload(result.payload)
        if rtype.value == "FAILURE":
            out.rejected.append(Rejected(
                CandidateFact(predicate="(no-effect)", entity_type="",
                              entity_field="", entity_value="",
                              value_json="null", json_path="$",
                              strength=EffectStrength.NONE),
                "FAILURE_RESULT", "contract suppressed: result failed"))
            continue
        entity_field = contract.get("entity_field", "")
        entity_value = (call.payload or {}).get(entity_field)
        if entity_value is None:
            continue
        entity_value = str(entity_value)
        # result bindings: call argument must equal result field (entity echo)
        ok = True
        for arg_field, result_path in (contract.get("result_bindings") or {}).items():
            left = (call.payload or {}).get(arg_field)
            right, present = json_path_get(result.payload, result_path)
            if not present or left is None or str(left) != str(right):
                ok = False
        if not ok:
            continue
        for post in contract.get("postconditions", []):
            candidate = CandidateFact(
                predicate=post["predicate"],
                entity_type=contract.get("entity_type", _entity_type(entity_field)),
                entity_field=entity_field, entity_value=entity_value,
                value_json=post["value_json"], json_path=post["json_path"],
                strength=EffectStrength(post.get("strength", "EXECUTED")),
                effect_class=EffectClass(contract.get("effect_class", "UPDATE")),
                contract_bound=bool(contract.get("result_bindings")))
            verdict = verify_candidate(case, call, result, candidate)
            if isinstance(verdict, VerifiedFact):
                if contract.get("documented_contract"):
                    fact = verdict.fact
                    upgraded = WorldFact(
                        predicate=fact.predicate, entity_type=fact.entity_type,
                        entity_id=fact.entity_id, value=fact.value,
                        truth=fact.truth, strength=fact.strength,
                        authority=Authority.CONTRACT_GUARANTEE,
                        provenance=Provenance(call_id=fact.provenance.call_id,
                                              result_index=fact.provenance.result_index,
                                              json_path=fact.provenance.json_path,
                                              authority=Authority.CONTRACT_GUARANTEE),
                        observed_at=fact.observed_at, valid_from=fact.valid_from)
                    out.verified.append(VerifiedFact(upgraded, verdict.witness_checks))
                else:
                    out.verified.append(verdict)
            else:
                out.rejected.append(verdict)
        for obs in contract.get("observe_fields", []):
            value_json = obs.get("value_json")
            if value_json is None:
                # dynamic observation: read whatever value sits at the path
                actual, present = json_path_get(result.payload, obs["json_path"])
                rendered = scalar_to_json(actual) if present else None
                if rendered is None:
                    continue
                value_json = rendered
            candidate = CandidateFact(
                predicate=obs["predicate"],
                entity_type=contract.get("entity_type", _entity_type(entity_field)),
                entity_field=entity_field, entity_value=entity_value,
                value_json=value_json, json_path=obs["json_path"],
                strength=EffectStrength.OBSERVED,
                effect_class=EffectClass.READ, is_observation=True)
            verdict = verify_candidate(case, call, result, candidate)
            if isinstance(verdict, VerifiedFact):
                out.verified.append(verdict)
            else:
                out.rejected.append(verdict)
    return out


# ------------------------------------------------------------- LLM arms -------

def run_llm_arm(case: TrajectoryCase, arm: str, proposer) -> ArmOutput:
    """Arms A/B/C/E propose via LLM and are counted as ESTABLISHED without a
    witness (the diagnostic: what the LLM alone claims). Arm H runs the same
    name-blind proposals as E through the deterministic witness — only
    witnessed facts enter its ledger.
    """
    out = ArmOutput(arm, case.case_id)
    witness = arm == "H_hybrid"
    base_arm = "E_nameblind" if arm == "H_hybrid" else arm
    catalog, mask = _mask_names(case) if base_arm == "E_nameblind" else (_catalog(case), {})
    include_results = base_arm in ("C_full", "E_nameblind")
    for call, result in _pair(case):
        tool = catalog.get(call.tool, {"name": call.tool, "description": ""})
        view_tool = dict(tool)
        if base_arm == "E_nameblind":
            view_tool["name"] = mask.get(call.tool, call.tool)
        try:
            answer = proposer.ask(
                SYSTEM_PROMPT_ARM(base_arm),
                build_arm_prompt(base_arm, view_tool, call.payload,
                                 result if include_results else None))
        except Exception as exc:  # transport failures become UNKNOWN, never guesses
            out.errors.append(f"{call.call_id}: {type(exc).__name__}: {exc}")
            continue
        proposal = parse_proposal(answer)
        # lenient recovery: the model may omit predicate/entity_type
        try:
            ec = proposal.effect_class
        except Exception:
            ec = EffectClass.UNKNOWN
        recovered = []
        raw_facts = (answer.get("value") or {}).get("facts") or []
        strict_keys = {(f.entity_field, f.json_path, f.value_json) for f in proposal.facts}
        for item in raw_facts:
            if not isinstance(item, dict):
                continue
            key = (item.get("entity_field"), item.get("json_path"),
                   item.get("value_json"))
            if all(isinstance(part, str) for part in key) and key in strict_keys:
                continue  # already parsed strictly
            candidate = _lenient_candidate(item, ec)
            if candidate is not None:
                recovered.append(candidate)
        all_facts = list(proposal.facts) + recovered
        out.proposal_meta[call.call_id] = {
            "result_type": proposal.result_type.value,
            "effect_class": proposal.effect_class.value,
            "effect_strength": proposal.effect_strength.value,
            "n_facts": len(all_facts),
            "n_strict": len(proposal.facts),
            "n_recovered": len(recovered)}
        for candidate in all_facts:
            if witness:  # H: every proposal must pass the deterministic witness
                verdict = verify_candidate(case, call, result, candidate)
                if isinstance(verdict, VerifiedFact):
                    out.verified.append(verdict)
                else:
                    out.rejected.append(verdict)
            else:  # A/B/C/E: unwitnessed proposals, counted as established
                out.ungrounded.append({
                    "call_id": call.call_id, "tool": mask.get(call.tool, call.tool),
                    "predicate": candidate.predicate,
                    "entity_type": candidate.entity_type,
                    "entity_id": candidate.entity_value,
                    "value": candidate.value_json,
                    "strength": candidate.strength.value,
                    "provenance": {"call_id": call.call_id,
                                   "result_index": None,
                                   "json_path": candidate.json_path,
                                   "authority": "NONE"},
                })
    return out


def SYSTEM_PROMPT_ARM(arm: str) -> str:
    from .proposer import SYSTEM
    if arm in ("A_name_desc", "B_desc_schema"):
        return (SYSTEM + " You are NOT shown any actual result; judge only "
                "what the documented tool contract could establish on success.")
    return SYSTEM


def build_arm_prompt(arm: str, tool: dict, arguments, result) -> str:
    from .proposer import build_user_prompt
    include = {"A_name_desc": ["name", "description"],
               "B_desc_schema": ["name", "description", "schema"],
               "C_full": ["name", "description", "schema", "arguments", "result"],
               "E_nameblind": ["description", "schema", "arguments", "result"]}[arm]
    parts = []
    if "name" in include:
        parts.append(f"TOOL NAME: {tool.get('name', '(unknown)')}")
    if "description" in include:
        parts.append(f"TOOL DESCRIPTION: {tool.get('description', '(none)')}")
    if "schema" in include:
        parts.append(f"INPUT SCHEMA:\n{_render_schema(tool)}")
    if "arguments" in include:
        parts.append(f"ACTUAL CALL ARGUMENTS: {json.dumps(arguments or {}, ensure_ascii=False)}")
    if "result" in include:
        parts.append(f"ACTUAL TOOL RESULT: {json.dumps(result.payload if result and result.payload is not None else {}, ensure_ascii=False)}")
    parts.append(PROMPT_TAIL)
    return "\n\n".join(parts)


PROMPT_TAIL = (
    "TASK: propose what world facts this one tool interaction could prove. "
    "Return strict JSON: {\"result_type\": \"...\", \"effect_class\": \"...\", "
    "\"effect_strength\": \"...\", \"facts\": [...]}. Each fact MUST contain "
    "ALL of these keys: \"predicate\" (entity-type-prefixed fact name, e.g. "
    "\"order.status\"), \"entity_type\" (e.g. \"order\"), \"entity_field\" "
    "(an argument field name), \"entity_value\" (the literal argument value, "
    "or \"\" if absent), \"value_json\" (the exact scalar found in the result, "
    "JSON-encoded), \"json_path\" (exact result path like \"$.status\"), "
    "\"strength\" (REQUESTED, INITIATED, EXECUTED, CONFIRMED or OBSERVED). "
    "Example fact: {\"predicate\":\"order.status\",\"entity_type\":\"order\","
    "\"entity_field\":\"order_id\",\"entity_value\":\"#9001\","
    "\"value_json\":\"\\\"cancelled\\\"\",\"json_path\":\"$.status\","
    "\"strength\":\"EXECUTED\"}. A generic success acknowledgement or a tool "
    "NAME alone proves nothing about business state; async statuses "
    "(queued/processing/pending/scheduled/created) prove at most "
    "REQUESTED/INITIATED. If nothing is provable, return an empty facts "
    "list. Never invent fields, values or paths that are not literally "
    "present in the given data.")


def _render_schema(tool: dict) -> str:
    fields = tool.get("fields") or {}
    if not fields:
        return "(no input schema)"
    lines = []
    for name, spec in fields.items():
        if isinstance(spec, str):
            lines.append(f"  {name}: {spec}")
        else:
            req = "!" if spec.get("required") else ""
            enum = f" [enum: {'|'.join(spec.get('enum', []))}]" if spec.get("enum") else ""
            desc = f" — {spec['description']}" if spec.get("description") else ""
            lines.append(f"  {name}: {spec.get('type', 'string')}{req}{enum}{desc}")
    return "\n".join(lines)


def _lenient_candidate(item: dict, effect_class: EffectClass) -> CandidateFact | None:
    """Build a candidate even when the model omitted predicate/entity_type:
    derive them from entity_field and the json_path leaf."""
    required = ("entity_field", "entity_value", "value_json", "json_path")
    if any(not isinstance(item.get(k), str) for k in required):
        return None
    entity_field = item["entity_field"]
    entity_value = item["entity_value"]
    if not entity_field:
        return None
    try:
        decoded = json.loads(item["value_json"])
    except (ValueError, TypeError):
        return None
    if decoded is not None and not isinstance(decoded, (str, int, float, bool)):
        return None
    try:
        strength = EffectStrength(item.get("strength", "NONE"))
    except ValueError:
        return None
    if strength is EffectStrength.NONE:
        return None
    path = item["json_path"]
    leaf = path.lstrip("$").split(".")[-1].split("[")[0] if path else ""
    predicate = item.get("predicate") or (
        f"{_entity_type(entity_field)}.{leaf}" if leaf else None)
    if not predicate:
        return None
    entity_type = item.get("entity_type") or _entity_type(entity_field)
    return CandidateFact(
        predicate=predicate, entity_type=entity_type,
        entity_field=entity_field, entity_value=entity_value or "",
        value_json=item["value_json"], json_path=path,
        strength=strength, effect_class=effect_class,
        is_observation=strength is EffectStrength.OBSERVED)


# ------------------------------------------------------------- J layer -------

def build_ledger(case: TrajectoryCase, output: ArmOutput) -> FactLedger:
    """Fold verified facts (+ J layer if requested) into the append-only ledger."""
    ledger = FactLedger()
    for verified in output.verified:
        fact = verified.fact
        kind = (LedgerKind.OBSERVE if fact.strength is EffectStrength.OBSERVED
                else LedgerKind.EFFECT)
        ledger.append(FactEvent(index=fact.observed_at, kind=kind, fact=fact))
    return ledger


def apply_read_confirmation(ledger: FactLedger) -> tuple[FactLedger, list[dict]]:
    """Arm J post-layer: later authoritative read confirmation / contradiction.

    Rules (section 13):
      * a later OBSERVE of the same (entity, predicate) with the same value
        upgrades an EFFECT fact to CONFIRMED (authority READ_OBSERVATION);
      * a later OBSERVE with a different value invalidates earlier EFFECT and
        OBSERVE facts from that index on (stale state), and the read wins;
      * no retroactive justification: upgrades carry their own observed_at,
        PRIOR_TRUE before that index still returns the old strength.
    """
    events = sorted(ledger.events, key=lambda e: e.index)
    new_events: list[FactEvent] = []
    upgrades: list[dict] = []
    by_key: dict[tuple, list[FactEvent]] = {}
    for event in events:
        by_key.setdefault(event.fact.key(), []).append(event)
    for key, group in by_key.items():
        observes = [e for e in group if e.kind is LedgerKind.OBSERVE]
        effects = [e for e in group if e.kind is LedgerKind.EFFECT]
        for effect in effects:
            later = [o for o in observes if o.index > effect.index]
            if not later:
                continue
            first_later = later[0]
            if first_later.fact.value == effect.fact.value:
                upgraded = WorldFact(
                    predicate=effect.fact.predicate,
                    entity_type=effect.fact.entity_type,
                    entity_id=effect.fact.entity_id,
                    value=effect.fact.value, truth=Truth.TRUE,
                    strength=EffectStrength.CONFIRMED,
                    authority=Authority.READ_OBSERVATION,
                    provenance=first_later.fact.provenance,
                    observed_at=first_later.fact.observed_at,
                    valid_from=effect.fact.valid_from,
                    invalidated_at=None)
                new_events.append(FactEvent(index=first_later.fact.observed_at,
                                            kind=LedgerKind.EFFECT, fact=upgraded))
                upgrades.append({"kind": "CONFIRMED", "entity": key,
                                 "at": first_later.fact.observed_at})
            else:
                invalidated = WorldFact(
                    predicate=effect.fact.predicate,
                    entity_type=effect.fact.entity_type,
                    entity_id=effect.fact.entity_id,
                    value=effect.fact.value, truth=effect.fact.truth,
                    strength=effect.fact.strength,
                    authority=effect.fact.authority,
                    provenance=effect.fact.provenance,
                    observed_at=effect.fact.observed_at,
                    valid_from=effect.fact.valid_from,
                    invalidated_at=first_later.fact.observed_at)
                replacement = FactEvent(index=effect.index, kind=effect.kind,
                                         fact=invalidated)
                events[events.index(effect)] = replacement
                new_events.append(FactEvent(index=first_later.fact.observed_at,
                                            kind=LedgerKind.INVALIDATE, fact=first_later.fact))
                upgrades.append({"kind": "CONTRADICTED", "entity": key,
                                 "at": first_later.fact.observed_at,
                                 "self_report": effect.fact.value,
                                 "observed": first_later.fact.value})
    result = FactLedger()
    for event in sorted(events + new_events, key=lambda e: e.index):
        result.append(event)
    return result, upgrades


# ------------------------------------------------------------- dispatcher ----

def run_arm(case: TrajectoryCase, arm: str, proposer=None) -> ArmOutput:
    if arm in DETERMINISTIC_ARMS:
        return {"D_result_only": arm_D_result_only,
                "F_structural": arm_F_structural,
                "G_extractive": arm_G_extractive,
                "I_contract": arm_I_contract}[arm](case)
    if arm in LLM_ARMS:
        if proposer is None:
            raise ValueError(f"arm {arm} requires an LLM proposer")
        return run_llm_arm(case, arm, proposer)
    raise ValueError(f"unknown arm {arm}")
