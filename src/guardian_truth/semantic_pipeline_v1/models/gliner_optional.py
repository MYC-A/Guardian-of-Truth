"""Dependency-isolated GLiNER2.5 subprocess adapter.

The Guardian process intentionally never imports gliner2 or its Transformers
4.x dependency tree. The sidecar accepts/returns plain JSON only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from ..rule_ir import rule_digest
from ..types import RuleCandidate, RuleExpression, RuleIR, RuleTerm, SourceSpan


_ENTITY_KINDS = {
    "action": "ACTION",
    "state": "STATE",
    "claim": "CLAIM",
    "value": "INFORMATION",
    "entity": "INFORMATION",
}


def _plain_span(item, *, segment_id: str, source_text: str) -> SourceSpan | None:
    if not isinstance(item, dict):
        return None
    try:
        start, end, text = int(item["start"]), int(item["end"]), str(item["text"])
    except (KeyError, TypeError, ValueError):
        return None
    if not text or not 0 <= start < end <= len(source_text) or source_text[start:end] != text:
        return None
    return SourceSpan(segment_id, start, end, text)


def _gliner_candidate(*, rule: RuleIR, spans: tuple[SourceSpan, ...], index: str,
                      model_name: str, segment_id: str,
                      unresolved: tuple[str, ...] = ()) -> RuleCandidate:
    extractor = f"gliner2:{model_name}"
    digest = rule_digest(rule)
    candidate_id = hashlib.sha256(
        f"{extractor}\0{segment_id}\0{index}\0{digest}".encode("utf-8")
    ).hexdigest()[:20]
    return RuleCandidate(candidate_id, rule, spans, (segment_id,), (extractor,),
                         unresolved_components=unresolved, canonical_digest=digest)


def normalize_gliner2_evidence(row: dict, *, segment_id: str, source_text: str,
                               model_name: str) -> tuple[RuleCandidate, ...]:
    """Convert the sidecar's plain JSON to independent semantic hypotheses.

    Scores are retained in ``gliner_evidence.json`` but deliberately do not
    select, rank, or collapse candidates here.
    """
    candidates: list[RuleCandidate] = []
    entities_wrapper = row.get("entities") if isinstance(row, dict) else None
    entities = entities_wrapper.get("entities", {}) if isinstance(entities_wrapper, dict) else {}
    entity_items = entities.items() if isinstance(entities, dict) else ()
    for label, items in entity_items:
        target_kind = _ENTITY_KINDS.get(str(label).casefold())
        if target_kind is None or not isinstance(items, list):
            continue
        for position, item in enumerate(items):
            span = _plain_span(item, segment_id=segment_id, source_text=source_text)
            if span is None:
                continue
            issue = f"gliner-entity-only:{str(label).casefold()}"
            rule = RuleIR("UNKNOWN", None, RuleTerm(target_kind, name=span.quote),
                          unresolved_references=(issue,))
            candidates.append(_gliner_candidate(
                rule=rule, spans=(span,), index=f"entity:{label}:{position}",
                model_name=model_name, segment_id=segment_id, unresolved=(issue,)))

    relations_wrapper = row.get("relations") if isinstance(row, dict) else None
    relations = (relations_wrapper.get("relation_extraction", {})
                 if isinstance(relations_wrapper, dict) else {})
    full_span = ((SourceSpan(segment_id, 0, len(source_text), source_text),)
                 if source_text else ())
    relation_items = relations.items() if isinstance(relations, dict) else ()
    for label, items in relation_items:
        relation = str(label).casefold()
        if not isinstance(items, list):
            continue
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            head = item.get("head")
            tail = item.get("tail")
            head_span = _plain_span(head, segment_id=segment_id, source_text=source_text)
            tail_span = _plain_span(tail, segment_id=segment_id, source_text=source_text)
            if head_span is None or tail_span is None or not full_span:
                continue
            unresolved: tuple[str, ...] = ()
            if relation in {"requires", "prohibits", "allows"}:
                modality = {"requires": "REQUIRE", "prohibits": "FORBID",
                            "allows": "ALLOW"}[relation]
                issue = "gliner-modal-relation-endpoints-unresolved"
                rule = RuleIR(modality, head_span.quote,
                              RuleTerm("ACTION", name=tail_span.quote),
                              unresolved_references=(issue,))
                unresolved = (issue,)
            elif relation in {"before", "after"}:
                issue = "gliner-temporal-modality-unknown"
                rule = RuleIR("UNKNOWN", None, RuleTerm("STATE", name=head_span.quote),
                              condition=RuleExpression("ATOM", term=RuleTerm(
                                  "STATE", name=tail_span.quote)),
                              temporal=relation.upper(), unresolved_references=(issue,))
                unresolved = (issue,)
            elif relation == "condition_for":
                issue = "gliner-condition-modality-unknown"
                rule = RuleIR("UNKNOWN", None, RuleTerm("ACTION", name=tail_span.quote),
                              relation="IF", condition=RuleExpression(
                                  "ATOM", term=RuleTerm("STATE", name=head_span.quote)),
                              unresolved_references=(issue,))
                unresolved = (issue,)
            elif relation in {"unless", "exception_to"}:
                issue = "gliner-exception-modality-unknown"
                target, exception = ((head_span, tail_span) if relation == "unless"
                                     else (tail_span, head_span))
                rule = RuleIR("UNKNOWN", None, RuleTerm("ACTION", name=target.quote),
                              relation="UNLESS", exception=RuleExpression(
                                  "ATOM", term=RuleTerm("STATE", name=exception.quote)),
                              unresolved_references=(issue,))
                unresolved = (issue,)
            else:
                continue
            candidates.append(_gliner_candidate(
                rule=rule, spans=full_span, index=f"relation:{relation}:{position}",
                model_name=model_name, segment_id=segment_id, unresolved=unresolved))

    unique = {}
    for candidate in candidates:
        key = (candidate.canonical_digest, candidate.source_spans,
               candidate.unresolved_components)
        unique.setdefault(key, candidate)
    return tuple(unique.values())


class GLiNER2SidecarError(RuntimeError):
    pass


class GLiNER2Sidecar:
    ENTITY_LABELS = {
        "action": "an action or operation",
        "state": "a state or property",
        "value": "a constrained value",
        "entity": "an object or identifier",
        "claim": "an asserted claim",
    }
    RELATION_LABELS = ("before", "after", "unless", "requires", "prohibits", "allows",
                       "condition_for", "exception_to")

    def __init__(self, *, model_name: str, python_executable: str,
                 timeout_seconds: float = 600.0, worker_path: str | Path | None = None,
                 run=None):
        self.model_name = model_name
        self.python_executable = python_executable
        self.timeout_seconds = timeout_seconds
        self.worker_path = Path(worker_path) if worker_path else (
            Path(__file__).resolve().parents[4] / "scripts" / "gliner2_semantic_sidecar.py")
        self._run = run or subprocess.run

    def extract_batch(self, items: list[dict], *, device: str = "cuda") -> dict:
        request = {
            "model": self.model_name,
            "device": device,
            "quantize": device.startswith("cuda"),
            "entity_labels": self.ENTITY_LABELS,
            "relation_labels": list(self.RELATION_LABELS),
            "items": items,
        }
        try:
            completed = self._run(
                [self.python_executable, str(self.worker_path)],
                input=json.dumps(request, ensure_ascii=False), text=True,
                capture_output=True, timeout=self.timeout_seconds, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise GLiNER2SidecarError(str(error)) from error
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "sidecar failed").strip()
            raise GLiNER2SidecarError(message[-2000:])
        try:
            response = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise GLiNER2SidecarError("sidecar did not return one JSON object") from error
        if response.get("status") != "EXECUTED":
            raise GLiNER2SidecarError(str(response.get("error") or "sidecar unavailable"))
        return response


# Compatibility alias for callers that imported the old optional adapter.
GLiNEREvidenceExtractor = GLiNER2Sidecar
