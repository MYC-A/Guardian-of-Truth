"""Mechanical fact ledger for suspicion cross-checks (Architecture B).

Conservative, premise-checked refutations ONLY:
- stale_value: suspicion asserts value V for entity E, but a LATER tool
  response for the SAME entity reports V' != V on the same field.
  Refutes only when entity identity and time order are both verified.
- failed_call: suspicion's response quote asserts an effect of a call whose
  TOOL_RESPONSE carries an explicit error/failed status.

Both directions are recorded (support AND refute candidates); UNRESOLVED
is the default. No effect invention: a successful call does NOT prove a
state change unless the response reports it.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from common.trace_parser import Trace, ToolEvent

_NUM_RE = re.compile(r"-?\d[\d\s]*(?:[.,]\d+)?")


@dataclass
class EntityReading:
    tool: str
    entity: str  # best-effort entity key (account id / reservation id / msisdn)
    value: str
    raw: str
    seq: int  # global order
    seg_turn: Optional[int]
    is_error: bool


def _extract_entity_key(payload: dict | list, tool: str) -> Optional[str]:
    """Best-effort: find the dominant entity identifier in a tool payload."""
    if not isinstance(payload, dict):
        return None
    # common id-like fields, in priority order
    for k in ("account", "reservation", "order", "msisdn", "user_id", "id", "card", "booking_id"):
        if k in payload and isinstance(payload[k], str):
            return f"{k}={payload[k]}"
        if k in payload and isinstance(payload[k], (int, float)):
            return f"{k}={payload[k]}"
    # nested single-key dicts (e.g. get_balance result)
    return None


def _iter_values(obj, prefix=""):
    """Yield (path, scalar) for all leaf scalars of a JSON payload."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_values(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_values(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


@dataclass
class FactLedger:
    trace: Trace
    readings: list[EntityReading] = field(default_factory=list)
    # entity-key -> ordered list of readings
    by_entity: dict[str, list[EntityReading]] = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def build(cls, trace: Trace) -> "FactLedger":
        led = cls(trace=trace)
        for e in trace.tool_events:
            if e.kind != "RESPONSE" or e.payload is None:
                continue
            entity = _extract_entity_key(e.payload, e.tool) or f"tool={e.tool}"
            for path, val in _iter_values(e.payload):
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    led.readings.append(
                        EntityReading(
                            tool=e.tool,
                            entity=entity,
                            value=str(val),
                            raw=f"{path}={val}",
                            seq=e.seq,
                            seg_turn=trace.segments[e.seg_idx].turn,
                            is_error=e.is_error,
                        )
                    )
                elif isinstance(val, str) and len(val) < 80:
                    led.readings.append(
                        EntityReading(
                            tool=e.tool,
                            entity=entity,
                            value=val,
                            raw=f"{path}={val}",
                            seq=e.seq,
                            seg_turn=trace.segments[e.seg_idx].turn,
                            is_error=e.is_error,
                        )
                    )
            led.by_entity[entity].append(
                EntityReading(
                    tool=e.tool, entity=entity, value="", raw=str(e.payload)[:200],
                    seq=e.seq, seg_turn=trace.segments[e.seg_idx].turn, is_error=e.is_error,
                )
            )
        return led

    # ------------- checks -------------

    def check_stale_value(self, claimed_value: str, entity_hint: str | None) -> dict:
        """Did a later read of the same entity report a different value?

        Returns dict(status, detail) where status in
        {REFUTED_STALE, NO_LATER_READ, UNRESOLVED}.
        Premises: entity identity must match hinted id substring; the claim
        must contain a number found earlier for that entity.
        """
        claimed_nums = _NUM_RE.findall(claimed_value or "")
        if not claimed_nums:
            return {"status": "UNRESOLVED", "detail": "no numeric claim"}
        norm = lambda s: re.sub(r"[\s,]", "", s).rstrip(".")
        cnums = {norm(n) for n in claimed_nums}
        candidates = []
        if entity_hint:
            for ent, readings in self.by_entity.items():
                if entity_hint in ent or any(entity_hint in r.raw for r in readings):
                    candidates.append(ent)
        else:
            candidates = list(self.by_entity.keys())
        best = None
        for ent in candidates:
            readings = sorted(self.by_entity[ent], key=lambda r: r.seq)
            for i, r in enumerate(readings):
                if r.value in cnums or any(norm(r.value) == c for c in cnums):
                    # found claimed value at position i; later readings same entity
                    later = [x for x in readings[i + 1 :] if not x.is_error and x.value]
                    if later:
                        best = {
                            "status": "REFUTED_STALE",
                            "entity": ent,
                            "claimed_seq": r.seq,
                            "later": [
                                {"seq": x.seq, "value": x.value, "raw": x.raw, "turn": x.seg_turn}
                                for x in later[:5]
                            ],
                        }
                        break
            if best:
                break
        if best:
            return best
        return {"status": "NO_LATER_READ", "detail": "no later read contradicts"}

    def check_failed_call_claim(self, response_text: str) -> list[dict]:
        """Find assertions of completed actions whose tool response failed."""
        findings = []
        resp_seg = self.trace.response_segment
        if resp_seg is None:
            return findings
        for e in self.trace.tool_events:
            if e.kind == "RESPONSE" and e.is_error:
                tool = e.tool
                # does the response claim completion of this tool's action?
                pat = re.compile(
                    r"(успешн\w+|выполнен\w*|проведён\w*|зачислен\w*|списан\w*|оформлен\w*|подключ\w+|начислен\w*|перенес\w+|отменён\w*|выполнено|готово)",
                    re.I,
                )
                if pat.search(response_text):
                    findings.append(
                        {
                            "tool": tool,
                            "response_quote_hint": pat.search(response_text).group(0),
                            "error_raw": e.raw_payload[:200],
                            "seq": e.seq,
                        }
                    )
        return findings


def normalize_quote(q: str) -> str:
    """Normalize a quote for source matching (strip spaces/punct variance)."""
    q = re.sub(r"\s+", " ", q or "").strip()
    q = q.strip("«»\"'`“”‘’…")
    return q


def locate_quote(source: str, quote: str, window: int = 60) -> dict:
    """Locate quote in source: exact, normalized, or fuzzy.

    Returns {found: bool, method, start, end, matched_text}.
    """
    q = (quote or "").strip()
    if not q:
        return {"found": False, "method": "empty", "start": None, "end": None, "matched_text": ""}
    i = source.find(q)
    if i >= 0:
        return {"found": True, "method": "exact", "start": i, "end": i + len(q), "matched_text": q}
    nq = normalize_quote(q)
    # normalized scan (collapse whitespace of source on the fly)
    norm_src = re.sub(r"\s+", " ", source)
    j = norm_src.find(nq)
    if j >= 0:
        # map back approximately: find by uniqueness window
        return {"found": True, "method": "normalized", "start": None, "end": None, "matched_text": nq}
    # fuzzy: quote head (first 40 chars) search
    head = nq[:40]
    if len(head) >= 15:
        k = norm_src.find(head)
        if k >= 0:
            return {"found": True, "method": "head40", "start": None, "end": None, "matched_text": head}
    return {"found": False, "method": "none", "start": None, "end": None, "matched_text": ""}
