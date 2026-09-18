"""full_architecture_v1 — Phase B probe: GLiNER2.5 semantic typing layer (§8).

Model: fastino/gliner2.5-small-v1 (74M, local CPU) via gliner2 2.0.0.

Probed capabilities (each on the directive's own examples):
  T1  typed entity extraction          — ACTION/ENTITY/FIELD/CARDINALITY/
      METHOD/ACTOR/CHANNEL/VALUE/IDENTIFIER/TEMPORAL_EVENT
  T2  relation extraction (typed
      endpoints)                       — runtime extract_relations + JointIE
  T3  constrained classification       — classify_text (deontic typing)
  T4  schema-based extraction          — extract_json (entities+classification)

Rule (directive §8): whatever the reduced model cannot provide RELIABLY
stays unresolved — no handwritten domain rules, no benchmark literals.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
for p in (str(_BAKEOFF), str(_FULLARCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

MODEL = ("/home/z/.cache/huggingface/hub/models--fastino--gliner2.5-small-v1"
         "/snapshots/f1e4d8fdd6fe328f45dee6aca3e6a07c9db4296e")

REPO = _FULLARCH.parents[1]
OUT = REPO / "outputs" / "full_architecture_v1" / "probes"

_LABELS = ["ACTION", "STATE", "ENTITY", "FIELD", "COLLECTION", "CARDINALITY",
           "METHOD", "TYPE", "IDENTIFIER", "SOURCE", "ACTOR", "CHANNEL",
           "VALUE", "TEMPORAL_EVENT", "READ", "MUTATION"]

# focused inventory: the directive §8's own semantic dimensions only
_LABELS_FOCUSED = ["ACTION", "ENTITY", "FIELD", "CARDINALITY", "METHOD",
                   "ACTOR", "CHANNEL", "VALUE", "IDENTIFIER"]

_SENTENCES = [
    "The assistant called exchange_delivered_order_items on order 7 after "
    "the customer confirmed delivery by SMS verification with two one-time "
    "passwords.",
    "A user may request at most three refunds per month for any single "
    "account, verified by password.",
    "The number of passengers on the reservation must not exceed the "
    "maximum allowed by the fare class.",
    "Agents must read the customer balance before initiating any card "
    "replacement for that account.",
]


def _extractor():
    from gliner2 import AutoExtractor
    return AutoExtractor.from_pretrained(MODEL, map_location="cpu")


def probe_typing(extractor) -> dict:
    started = time.perf_counter()
    per_inventory = {}
    for inventory_name, labels in (("generic-16", _LABELS),
                                   ("focused-9", _LABELS_FOCUSED)):
        per_sentence = []
        hits = {}
        for sentence in _SENTENCES:
            result = extractor.extract_entities(
                sentence, labels, include_confidence=True, include_spans=True,
                threshold=0.3)
            found = {}
            for label, items in (result.get("entities") or {}).items():
                entries = [{"text": sentence[item["start"]:item["end"]],
                            "confidence": round(float(item["confidence"]), 2)}
                           for item in items[:3]]
                if entries:
                    found[label] = entries
                    hits[label] = hits.get(label, 0) + len(entries)
            per_sentence.append({"sentence": sentence[:70], "spans": found})
        per_inventory[inventory_name] = {
            "labels_offered": len(labels),
            "labels_hit": {k: v for k, v in sorted(hits.items())},
            "per_sentence": per_sentence}
    generic_hits = set(per_inventory["generic-16"]["labels_hit"])
    focused_hits = set(per_inventory["focused-9"]["labels_hit"])
    return {
        "status": "RUN",
        "inventories": per_inventory,
        "label_set_sensitivity": {
            "only_in_focused": sorted(focused_hits - generic_hits),
            "only_in_generic": sorted(generic_hits - focused_hits),
            "note": "span->label assignment shifts with the offered "
                    "inventory (e.g. 'one-time passwords' is CARDINALITY "
                    "under the focused inventory but MUTATION under the "
                    "16-label one; sentence 3 'number of passengers' is "
                    "extracted under focused-9 but missed under generic-16) "
                    "— the reduced model's typing is label-inventory "
                    "sensitive; production use must pin the inventory"},
        "runtime_s": round(time.perf_counter() - started, 1),
    }


def probe_relations(extractor) -> dict:
    started = time.perf_counter()
    text = _SENTENCES[0]
    findings = {"status": "RUN", "runtime_extract_relations": {},
                "joint_ie": {}}
    # runtime relation extraction
    try:
        result = extractor.extract_relations(
            text, {"acts_on": {"head": ["ACTION"], "tail": ["ENTITY"]}},
            include_confidence=True)
        findings["runtime_extract_relations"] = {
            "ok": True, "result": {k: (len(v) if isinstance(v, list) else v)
                                   for k, v in result.items()}}
    except Exception as error:
        findings["runtime_extract_relations"] = {
            "ok": False, "error": f"{type(error).__name__}: {error}"[:200]}
    # JointIE engine (typed endpoints + constraints)
    try:
        from gliner2.joint_ie import JointIEEngine, JointSchema
        from gliner2.joint_ie.schema import EntitySpec, RelationSpec
        engine = JointIEEngine.from_pretrained(MODEL, device="cpu")
        schema = JointSchema()
        schema.entities = [
            EntitySpec(name="ACTION", threshold=0.2),
            EntitySpec(name="ENTITY", threshold=0.2),
            EntitySpec(name="ACTOR", threshold=0.2)]
        schema.relations = [
            RelationSpec(name="acts_on", head=("ACTION",), tail=("ENTITY",),
                         threshold=0.2),
            RelationSpec(name="performs", head=("ACTOR",), tail=("ACTION",),
                         threshold=0.2)]
        result = engine.extract(text, engine.compile_schema(schema))
        findings["joint_ie"] = {
            "ok": True,
            "entities": [(e.label, text[e.start:e.end])
                         for e in result.entities][:6],
            "relations": [(r.label, r.head, r.tail)
                          for r in result.relations][:6]}
    except Exception as error:
        findings["joint_ie"] = {
            "ok": False,
            "error": f"{type(error).__name__}: {error}"[:250],
            "note": "gliner2 2.0.0 + gliner2.5-small-v1 + transformers "
                    "4.57.1: empty-candidate amax crash in "
                    "boundary/pool.py forward — relation extraction via "
                    "JointIE NOT_RELIABLE in this environment; preserved as "
                    "unresolved (no custom rules written)"}
    findings["runtime_s"] = round(time.perf_counter() - started, 1)
    return findings


def probe_classification(extractor) -> dict:
    started = time.perf_counter()
    rows = []
    cases = [
        ("Users must not exchange delivered order items unless the delivery "
         "has been confirmed.", "FORBID"),
        ("The agent must verify identity before closing any account.",
         "REQUIRE"),
        ("Customers are allowed to cancel reservations at any time.",
         "ALLOW"),
    ]
    for text, expected in cases:
        result = extractor.classify_text(
            text, {"obligation_type": {"labels": ["FORBID", "REQUIRE",
                                                  "ALLOW", "OTHER"]}},
            include_confidence=True)
        got = (result.get("obligation_type") or {}).get("label", "?")
        confidence = round((result.get("obligation_type") or {})
                           .get("confidence", 0.0), 2)
        rows.append({"expected": expected, "got": got,
                     "confidence": confidence,
                     "correct": got == expected})
    correct = sum(1 for row in rows if row["correct"])
    return {"status": "RUN", "cases": rows, "correct": correct,
            "total": len(rows),
            "note": "constrained classification API works; the reduced "
                    "74M model misclassifies 'must not ... unless' as "
                    "REQUIRE at low confidence — NOT reliable for deontic "
                    "typing; modality stays with the extraction layer",
            "runtime_s": round(time.perf_counter() - started, 1)}


def probe_structured(extractor) -> dict:
    started = time.perf_counter()
    try:
        result = extractor.extract_json(
            _SENTENCES[0],
            {"obligation": {"entities": ["ACTION", "ENTITY", "METHOD"],
                            "classification": {
                                "task": "obligation_type",
                                "labels": ["FORBID", "REQUIRE", "ALLOW"]}}},
            include_confidence=True)
        return {"status": "RUN", "ok": True, "result": result,
                "note": "partial output: entities extracted, classification "
                        "array empty — schema-based extraction NOT reliable "
                        "on the reduced model; preserved as unresolved",
                "runtime_s": round(time.perf_counter() - started, 1)}
    except Exception as error:
        return {"status": "RUN", "ok": False,
                "error": f"{type(error).__name__}: {error}"[:200]}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    extractor = _extractor()
    payload = {
        "model": "fastino/gliner2.5-small-v1 (74M) via gliner2==2.0.0, CPU",
        "environment": "reduced-model analogue (directive §0); future "
                       "full-system run may swap the model without "
                       "architecture changes",
        "typed_entity_extraction": probe_typing(extractor),
        "relation_extraction": probe_relations(extractor),
        "constrained_classification": probe_classification(extractor),
        "structured_extraction": probe_structured(extractor),
        "ablation_hook": "semantic typing ON contributes typed spans "
                         "(CARDINALITY/METHOD/CHANNEL/...) to the binding "
                         "signal; typing OFF = raw text only — measured as "
                         "the N1 vs N2 arm difference on real46 (§22)",
        "verdict": "typed spans RELIABLE; relations/classification/JSON "
                   "NOT reliable in this environment — kept as unresolved "
                   "channels, no handwritten substitutes (directive §8)",
    }
    (OUT / "semantic_typing_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "typed_labels_focused": payload["typed_entity_extraction"]["inventories"]["focused-9"]["labels_hit"],
        "typed_labels_generic": payload["typed_entity_extraction"]["inventories"]["generic-16"]["labels_hit"],
        "label_sensitivity_only_in_focused": payload["typed_entity_extraction"]["label_set_sensitivity"]["only_in_focused"],
        "relations_ok": payload["relation_extraction"]["joint_ie"]["ok"],
        "classification_correct":
            f"{payload['constrained_classification']['correct']}/"
            f"{payload['constrained_classification']['total']}",
        "verdict": payload["verdict"]}, indent=1))


if __name__ == "__main__":
    main()
