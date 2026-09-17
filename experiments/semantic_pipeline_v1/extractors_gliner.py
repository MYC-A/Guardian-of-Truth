"""semantic_pipeline_v1 — Phase 6C: GLiNER2 local extractor.

GLiNER2.5-small-v1 (74M, DeBERTa-v3-xsmall encoder, gliner2 2.0.0 package,
AutoExtractor/BoundaryExtractor, CPU) is an independent zero-shot typed-span
extractor.  We ask it for typed semantic spans (actions, conditions,
exceptions, thresholds, temporal markers, actors) and assemble RuleIR
candidates DETERMINISTICALLY from the typed spans.  GLiNER is NOT forced to
produce whole rules when it cannot: no action span => partial UNKNOWN-modality
candidate (span evidence only).

Spans come with model-provided offsets, so grounding is exact.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from rule_ir import (Atom, Cardinality, Comparison, ConditionNode, Provenance, Ref,
                     RuleIR, SourceSpan, Temporal)
from units import Unit

MODEL_DIR = "/home/z/models/gliner2.5-small-v1"
LABELS = [
    "forbidden action", "required action", "allowed action",
    "condition", "exception", "numeric threshold",
    "temporal marker", "actor", "tool name", "state field",
]
_CONFIDENCE = 0.35

_MODALITY_OF_LABEL = {"forbidden action": "FORBID", "required action": "REQUIRE",
                      "allowed action": "ALLOW"}

_CARD_RE = re.compile(r"(at least|at most|no more than|no fewer than|exactly)\s+(\d+)\b", re.IGNORECASE)
_THR_RE = re.compile(r"(?:less than|more than|greater than|fewer than|under|over|above|below|"
                     r"at least|at most|no more than)\s+(\d+(?:\.\d+)?%?)", re.IGNORECASE)


class GlinerExtractor:
    def __init__(self, model_path: str = MODEL_DIR, threshold: float = _CONFIDENCE):
        self.model_path = model_path
        self.threshold = threshold
        self._model = None

    def _load(self):
        if self._model is None:
            from gliner2 import AutoExtractor
            self._model = AutoExtractor.from_pretrained(self.model_path, map_location="cpu")

    def typed_spans(self, text: str) -> dict[str, list[dict]]:
        """{label: [{text, start, end, confidence}, ...]} — GLiNER2 provides
        character offsets into the given text."""
        self._load()
        result = self._model.extract_entities(text, LABELS, include_confidence=True,
                                              include_spans=True, threshold=self.threshold)
        out: dict[str, list[dict]] = {}
        for label, items in (result.get("entities") or {}).items():
            keep = []
            for item in items:
                if item.get("confidence", 0) < self.threshold:
                    continue
                span_text = text[item["start"]:item["end"]]
                if span_text.strip():
                    keep.append({"text": span_text, "start": item["start"], "end": item["end"],
                                 "confidence": round(float(item["confidence"]), 4)})
            if keep:
                out[label] = sorted(keep, key=lambda entry: -entry["confidence"])
        return out

    # ------------------------------------------------------- deterministic map

    def extract(self, unit: Unit, tool_names: list[str]) -> tuple[list[RuleIR], list[dict]]:
        spans = self.typed_spans(unit.text)
        rules: list[RuleIR] = []
        failures: list[dict] = []
        action_labels = [label for label in ("forbidden action", "required action", "allowed action")
                         if spans.get(label)]
        if not action_labels:
            partial = self._partial(spans, unit, tool_names)
            if partial is not None:
                rules.append(partial)
            elif any(spans.get(label) for label in ("condition", "exception", "numeric threshold")):
                failures.append({"unit": unit.unit_id, "kind": "NO_ACTION_SPAN", "detail": "gliner span evidence without action"})
            return rules, failures
        for label in action_labels:
            modality = _MODALITY_OF_LABEL[label]
            action = spans[label][0]
            target = Ref(kind="ACTION", text=action["text"],
                         ref=self._ref_for(action["text"], tool_names))
            conditions = self._node_for(
                [span for span in spans.get("condition", [])[:3]
                 if span["text"].strip() != action["text"].strip()], unit, tool_names)
            exceptions = [self._node_for([span], unit, tool_names)
                          for span in spans.get("exception", [])[:2]
                          if span["text"].strip() != action["text"].strip()]
            exceptions = [node for node in exceptions if node is not None]
            temporal = Temporal(relation="NONE")
            markers = spans.get("temporal marker", [])
            anchors = [span for span in (spans.get("required action", []) + spans.get("allowed action", [])
                                         + spans.get("forbidden action", []))
                       if span["text"] != action["text"]]
            if markers and anchors:
                relation = self._relation(unit.text, action, markers[0])
                anchor = anchors[0]
                temporal = Temporal(relation=relation,
                                    anchor=Ref(kind="ACTION", text=anchor["text"],
                                               ref=self._ref_for(anchor["text"], tool_names)))
            source = SourceSpan(document=unit.document,
                                start=unit.span[0] + action["start"],
                                end=unit.span[0] + action["end"], quote=action["text"])
            rule = RuleIR(
                rule_id=f"{unit.unit_id}:gliner:{len(rules)}",
                modality=modality, target=target, conditions=conditions, exceptions=exceptions,
                temporal=temporal, actor=self._actor(spans, unit),
                source_spans=[source],
                provenance=Provenance(extractor="gliner2",
                                      fragment_id=unit.fragment_ids[0] if unit.fragment_ids else None,
                                      segment_id=unit.segment_id,
                                      raw_output=json.dumps({k: [i["text"] for i in v] for k, v in spans.items()},
                                                            ensure_ascii=False)[:400]))
            rules.append(rule)
            lowered = unit.text.lower()
            if rule.exceptions or conditions is None:
                continue
            if any(cue in lowered for cue in ("unless", "except", "за исключением")):
                # unless-mirror: admit the exceptions-variant as a SEPARATE
                # candidate (both readings stay in Phi; NLI judges them)
                rules.append(rule.model_copy(update={
                    "rule_id": rule.rule_id + ":unless_mirror",
                    "exceptions": [conditions], "conditions": None,
                    "unresolved": list(rule.unresolved) + ["unless-cue present; mirror keeps the "
                                                           "exceptions-variant as a second interpretation"]}))
        return rules, failures

    def _partial(self, spans: dict, unit: Unit, tool_names: list[str]) -> RuleIR | None:
        leaves = []
        for label in ("condition", "exception", "numeric threshold", "state field", "tool name"):
            for span in spans.get(label, [])[:2]:
                leaves.append(ConditionNode(atom=self._atom_for(span, unit, tool_names)))
        if not leaves:
            return None
        return RuleIR(
            rule_id=f"{unit.unit_id}:gliner:partial",
            modality="UNKNOWN",
            target=Ref(kind="UNKNOWN", text=leaves[0].atom.text, ref=leaves[0].atom.ref),
            conditions=ConditionNode(all_=leaves),
            provenance=Provenance(extractor="gliner2",
                                  fragment_id=unit.fragment_ids[0] if unit.fragment_ids else None,
                                  segment_id=unit.segment_id),
            unresolved=["gliner span evidence without action label"],
            source_spans=[SourceSpan(document=unit.document, start=unit.span[0], end=unit.span[1],
                                     quote=unit.text[:400])],
            temporal=Temporal(), actor=self._actor(spans, unit))

    def _node_for(self, span_list: list[dict], unit: Unit, tool_names: list[str]) -> ConditionNode | None:
        atoms = [self._atom_for(span, unit, tool_names) for span in span_list[:3]]
        atoms = [atom for atom in atoms if atom is not None]
        if not atoms:
            return None
        return ConditionNode(all_=[ConditionNode(atom=atom) for atom in atoms])

    def _atom_for(self, span: dict, unit: Unit, tool_names: list[str]) -> Atom | None:
        text = span.get("text", "")
        if not text or text.strip() not in unit.text:
            return None
        comparison = None
        threshold = _THR_RE.search(text)
        if threshold:
            number = threshold.group(1).rstrip("%")
            op = self._op_for(text)
            comparison = Comparison(lhs=Ref(kind="STATE", text=text, ref=self._ref_for(text, tool_names)),
                                    op=op, rhs_literal=number)
        cardinality = None
        card = _CARD_RE.search(text)
        if card:
            cardinality = Cardinality(
                subject=Ref(kind="STATE", text=text, ref=self._ref_for(text, tool_names)),
                op={"at least": "AT_LEAST", "no fewer than": "AT_LEAST",
                    "at most": "AT_MOST", "no more than": "AT_MOST",
                    "exactly": "EXACTLY"}.get(card.group(1).lower(), "AT_LEAST"),
                count=int(card.group(2)))
        return Atom(kind="CONDITION" if "action" not in str(span.get("_label", "")) else "ACTION",
                    text=text.strip(), ref=self._ref_for(text, tool_names),
                    comparison=comparison, cardinality=cardinality,
                    span=SourceSpan(document=unit.document, start=unit.span[0] + span.get("start", 0),
                                    end=unit.span[0] + span.get("end", 0), quote=text) if "start" in span else None)

    @staticmethod
    def _actor(spans: dict, unit: Unit) -> str:
        actor_spans = spans.get("actor", [])
        if actor_spans:
            lowered = actor_spans[0]["text"].lower()
            if "agent" in lowered or "assistant" in lowered:
                return "assistant"
            if "user" in lowered or "customer" in lowered or "client" in lowered:
                return "user"
        return "UNKNOWN"

    @staticmethod
    def _relation(unit_text: str, action: dict, marker: dict) -> str:
        marker_text = marker["text"].lower()
        if marker.get("start", 10**9) < action.get("start", -1):
            # marker before the action mention
            if "before" in marker_text or "prior" in marker_text:
                return "AFTER"
            if "after" in marker_text or "once" in marker_text:
                return "BEFORE"
        else:
            if "before" in marker_text or "prior" in marker_text:
                return "BEFORE"
            if "after" in marker_text or "once" in marker_text:
                return "AFTER"
        if "until" in marker_text:
            return "UNTIL"
        if "while" in marker_text:
            return "WHILE"
        return "UNKNOWN"

    @staticmethod
    def _op_for(text: str) -> str:
        lowered = text.lower()
        if "at least" in lowered or "no less" in lowered or "minimum" in lowered:
            return "GE"
        if "at most" in lowered or "no more" in lowered or "maximum" in lowered:
            return "LE"
        if "less than" in lowered or "under" in lowered or "below" in lowered or "fewer" in lowered:
            return "LT"
        if "more than" in lowered or "greater" in lowered or "over" in lowered or "above" in lowered:
            return "GT"
        return "LT"

    @staticmethod
    def _ref_for(text: str, tool_names: list[str]) -> str:
        for tool in sorted(tool_names, key=len, reverse=True):
            if tool and re.search(r"(?<![\w.-])" + re.escape(tool) + r"(?![\w.-])", text):
                return tool
        key = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48]
        return key or "UNKNOWN"
