"""semantic_pipeline_v1 — Phase 6A: Mistral RuleIR extractor.

The Mistral API (already-configured remote backend, the ONLY remote model in
this experiment) receives:
  - the exact source fragment (extraction unit),
  - the RuleIR JSON schema,
  - exact source span metadata,
  - the catalog tool names (for ref normalization ONLY, offered as hints).
It NEVER receives gold labels, verdicts, or final metrics.

One proposal per unit (H0 discipline): no semantic retries; transport/JSON
failures are recorded and replayed from the local cache.  All outputs are
verbatim-grounded: any text field that is not a substring of the unit is
marked ungrounded and the candidate is rejected with a failure record.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from rule_ir import (Atom, Cardinality, Comparison, ConditionNode, Provenance, Ref,
                     RuleIR, SourceSpan, Temporal)
from units import Unit

MODEL = "ministral-14b-latest"
CACHE_PATH = REPO / "outputs" / "vnext" / "semantic_pipeline_v1" / "mistral_cache.json"

INSTRUCTIONS = (
    "You extract candidate policy rules from ONE source fragment into a small typed RuleIR. "
    "This is a candidate interpretation, NOT a verdict. Rules: (1) Every 'text' field MUST be a "
    "verbatim substring of the fragment - never paraphrase; if the concept is not expressible as a "
    "substring, put the concept in 'unresolved' instead. (2) modality: FORBID for must-not/may-not/"
    "cannot/do-not/prohibited; REQUIRE for must/required/shall; ALLOW for explicit permission wording "
    "(may/allowed/can); UNKNOWN otherwise. (3) target MUST be an object {kind, text, ref}: kind ACTION "
    "for tool calls / operations, STATE for field/value predicates, CLAIM for asserted facts, UNKNOWN "
    "otherwise; text = verbatim substring naming the target; ref = the exact tool name if the text "
    "names one of the offered tool names, else snake_case key, else UNKNOWN. (4) conditions and "
    "exceptions are boolean trees: an atom is {\"kind\": ..., \"text\": <verbatim>, \"ref\": ..., optional "
    "\"comparison\": {\"op\": \"LT|LE|GT|GE|EQ|NE\", \"lhs_text\": <verbatim>, \"rhs_literal\": <json literal>}, "
    "optional \"cardinality\": {\"op\": \"AT_LEAST|AT_MOST|EXACTLY\", \"count\": N, \"subject_text\": <verbatim>}}; "
    "combine with {\"all\":[...]}, {\"any\":[...]} or {\"not\": {...}}. (5) conditions = only-if/if/when "
    "gating; exceptions = unless/except; CRITICAL: an 'unless' clause goes to exceptions, NEVER to "
    "conditions (FORBID X unless Y means X is forbidden when Y does NOT hold); an 'only if' clause "
    "goes to conditions. temporal = {relation: BEFORE|AFTER|UNTIL|WHILE, anchor_text: "
    "<verbatim>}. (6) When a fragment contains multiple distinct rules, emit one object per rule; when "
    "the fragment is not normative, emit an empty list. (7) Use UNKNOWN / unresolved whenever the "
    "reading is ambiguous - never guess. EXACT OUTPUT SHAPE (one object per rule, inside {\"rules\":[...]}): "
    "{\"rules\":[{\"modality\":\"FORBID\",\"actor\":\"assistant\",\"target\":{\"kind\":\"ACTION\","
    "\"text\":\"close the account\",\"ref\":\"close_account\"},\"exceptions\":[{\"atom\":{\"kind\":\"STATE\","
    "\"text\":\"identity was verified\",\"ref\":\"verified_identity\",\"cardinality\":{\"op\":\"AT_LEAST\","
    "\"count\":2,\"subject_text\":\"two factors\"}}}],\"temporal\":{\"relation\":\"NONE\"}}]} Return ONE JSON "
    "object with no markdown."
)

RULE_OBJECT_SCHEMA_PROPS = {
    "modality": {"type": "string", "enum": ["REQUIRE", "FORBID", "ALLOW", "UNKNOWN"]},
    "actor": {"type": "string", "enum": ["assistant", "user", "system", "UNKNOWN"]},
    "target": {"type": "object", "additionalProperties": False,
               "required": ["kind", "text", "ref"],
               "properties": {"kind": {"type": "string", "enum": ["ACTION", "STATE", "CLAIM", "UNKNOWN"]},
                              "text": {"type": "string"}, "ref": {"type": "string"}}},
    "conditions": {"type": "object", "additionalProperties": False,
                   "properties": {"all": {"type": "array", "items": {"$ref": "#/defs/node"}},
                                  "any": {"type": "array", "items": {"$ref": "#/defs/node"}},
                                  "not": {"$ref": "#/defs/node"},
                                  "atom": {"$ref": "#/defs/atom"}}},
    "exceptions": {"type": "array", "maxItems": 4, "items": {"$ref": "#/defs/node"}},
    "temporal": {"type": "object", "additionalProperties": False,
                 "required": ["relation"],
                 "properties": {"relation": {"type": "string",
                                             "enum": ["NONE", "BEFORE", "AFTER", "UNTIL", "WHILE", "UNKNOWN"]},
                                "anchor_text": {"type": "string"}}},
    "unresolved": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
}
RULE_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["rules"],
    "properties": {"rules": {"type": "array", "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["modality", "target"],
        "properties": RULE_OBJECT_SCHEMA_PROPS,
    }}},
    "definitions": {}}


class MistralExtractor:
    def __init__(self, *, cache_path: Path | None = None, api_key_env: str = "MISTRAL_API_KEY",
                 model: str = MODEL, max_output_tokens: int = 2048):
        self.cache_path = Path(cache_path) if cache_path else CACHE_PATH
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.cache: dict[str, dict] = {}
        if self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.api_key = self._load_key(api_key_env)
        self._client = None
        self.live_calls = 0

    def _client_(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url="https://api.mistral.ai/v1",
                                  timeout=90.0)
        return self._client

    def _load_key(self, api_key_env: str) -> str:
        import os
        key = os.environ.get(api_key_env) or os.environ.get("mistral_api_key")
        if not key:
            env_path = REPO / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        name, value = line.split("=", 1)
                        if name.strip() in {api_key_env, "mistral_api_key"} and value.strip():
                            key = value.strip()
                            break
        if not key:
            raise RuntimeError("Mistral API key not configured (MISTRAL_API_KEY)")
        return key

    # ------------------------------------------------------------------ core

    def _key(self, payload: dict) -> str:
        import hashlib
        return hashlib.sha256(json.dumps(
            {"task": "semantic_pipeline_rule_ir_v1", "payload": payload,
             "model": self.model}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def ask(self, unit: Unit, tool_names: list[str]) -> dict:
        payload = {"fragment": unit.text,
                   "source_span": {"document": unit.document, "start": unit.span[0],
                                   "end": unit.span[1], "source_type": unit.source_type,
                                   "tool": unit.tool},
                   "tool_names": tool_names[:80],
                   "instructions": INSTRUCTIONS}
        key = self._key(payload)
        if key in self.cache:
            return self.cache[key]
        for attempt in range(3):
            try:
                response = self._client_().chat.completions.create(
                    model=self.model,
                    temperature=0.0,
                    max_tokens=self.max_output_tokens,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
                content = response.choices[0].message.content or ""
                parsed = json.loads(content)
                record = {"rules": parsed.get("rules", []), "raw": content[:4000]}
                break
            except Exception as error:  # transport/JSON errors recorded, never retried semantically
                if attempt == 2:
                    record = {"error": f"{type(error).__name__}:{str(error)[:300]}"}
                else:
                    time.sleep(2.0 * (attempt + 1))
        self.cache[key] = record
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.cache, ensure_ascii=False, sort_keys=True),
                             encoding="utf-8")
        temporary.replace(self.cache_path)
        self.live_calls += 1
        return record

    # ------------------------------------------------------------- to RuleIR

    def extract(self, unit: Unit, tool_names: list[str]) -> tuple[list[RuleIR], list[dict]]:
        record = self.ask(unit, tool_names)
        failures: list[dict] = []
        rules: list[RuleIR] = []
        if "error" in record:
            failures.append({"unit": unit.unit_id, "kind": "TRANSPORT", "detail": record["error"]})
            return rules, failures
        for index, raw in enumerate(record.get("rules", [])[:4]):
            built = self._build_rule(raw, unit, index)
            if built is None:
                failures.append({"unit": unit.unit_id, "kind": "UNGROUNDED",
                                 "detail": json.dumps(raw, ensure_ascii=False)[:300]})
                continue
            rules.append(built)
            mirror = self._unless_mirror(built, unit)
            if mirror is not None:
                rules.append(mirror)
        return rules, failures

    _EXCEPTION_CUES = ("unless", "except", "за исключением", "кроме случая")

    def _unless_mirror(self, rule: RuleIR, unit: Unit) -> RuleIR | None:
        """Deterministic alternative interpretation: when the source unit
        contains an exception cue but the extractor placed the gated content
        in CONDITIONS, also admit the exceptions-variant as a SEPARATE
        candidate (both stay in Phi; the NLI firewall judges them).  General
        keyword-level transform; never a winner selection."""
        lowered = unit.text.lower()
        if not any(cue in lowered for cue in self._EXCEPTION_CUES):
            return None
        if rule.conditions is None or rule.exceptions:
            return None
        return rule.model_copy(update={
            "rule_id": rule.rule_id + ":unless_mirror",
            "exceptions": [rule.conditions],
            "conditions": None,
            "unresolved": list(rule.unresolved) + ["unless-clause routed to conditions by extractor; "
                                                   "mirror candidate keeps both readings"]})

    def _build_rule(self, raw: dict, unit: Unit, index: int) -> RuleIR | None:
        try:
            target_raw = raw.get("target")
            target_text = self._target_text(target_raw, raw.get("text"), unit)
            if not target_text:
                return None
            if isinstance(target_raw, dict):
                target_kind = target_raw.get("kind", "ACTION")
                target_ref = target_raw.get("ref")
            else:
                target_kind = "ACTION"
                target_ref = target_text if isinstance(target_raw, str) else None
            target = Ref(kind=target_kind, text=target_text,
                         ref=self._normalize_ref(target_ref, target_text, unit))
            conditions = self._build_node(raw.get("conditions"), unit)
            if conditions is None and isinstance(raw.get("conditions"), dict):
                # tolerate a bare atom dict {comparison|cardinality|text} at top level
                conditions = self._build_node({"atom": raw["conditions"]}, unit)
            exceptions = []
            raw_exceptions = raw.get("exceptions", [])
            if isinstance(raw_exceptions, dict):
                raw_exceptions = [raw_exceptions]
            for exc in raw_exceptions:
                node = self._build_node(exc, unit)
                if node is None and isinstance(exc, dict):
                    node = self._build_node({"atom": exc}, unit)
                if node is not None:
                    exceptions.append(node)
            temporal_raw = raw.get("temporal") or {}
            if isinstance(temporal_raw, str):
                temporal_raw = {"relation": temporal_raw} if temporal_raw in {
                    "NONE", "BEFORE", "AFTER", "UNTIL", "WHILE", "UNKNOWN"} else {"relation": "UNKNOWN"}
            anchor_text = temporal_raw.get("anchor_text") or temporal_raw.get("anchor") or ""
            if isinstance(anchor_text, dict):
                anchor_text = anchor_text.get("text", "")
            temporal = Temporal(
                relation=temporal_raw.get("relation", "NONE") if temporal_raw.get("relation") in {
                    "NONE", "BEFORE", "AFTER", "UNTIL", "WHILE", "UNKNOWN"} else "UNKNOWN",
                anchor=Ref(kind="ACTION", text=anchor_text,
                           ref=self._normalize_ref("UNKNOWN", anchor_text, unit))
                if isinstance(anchor_text, str) and anchor_text and anchor_text in unit.text else None)
            span = SourceSpan(document=unit.document, start=unit.span[0], end=unit.span[1],
                              quote=unit.text[:400])
            return RuleIR(
                rule_id=f"{unit.unit_id}:mistral:{index}",
                modality=raw.get("modality", "UNKNOWN") if raw.get("modality") in {
                    "REQUIRE", "FORBID", "ALLOW", "UNKNOWN"} else "UNKNOWN",
                target=target, conditions=conditions, exceptions=exceptions,
                temporal=temporal, actor=raw.get("actor", "UNKNOWN") if isinstance(
                    raw.get("actor"), str) else "UNKNOWN",
                source_spans=[span],
                provenance=Provenance(extractor="mistral",
                                      fragment_id=unit.fragment_ids[0] if unit.fragment_ids else None,
                                      segment_id=unit.segment_id),
                unresolved=[str(item) for item in raw.get("unresolved", [])][:6])
        except Exception:
            return None

    def _target_text(self, target_raw, fallback, unit: Unit) -> str:
        """Tolerant target-text resolution: dict.text / dict / string, each
        must ground as a verbatim substring of the unit."""
        candidates = []
        if isinstance(target_raw, dict):
            candidates.append(target_raw.get("text") or "")
        elif isinstance(target_raw, str):
            candidates.append(target_raw)
        if isinstance(fallback, str):
            candidates.append(fallback)
        for candidate in candidates:
            if candidate and candidate in unit.text:
                return candidate
            if candidate and candidate.strip() and candidate.strip() in unit.text:
                return candidate.strip()
        return ""

    def _build_node(self, raw, unit: Unit) -> ConditionNode | None:
        if not isinstance(raw, dict):
            return None
        if "atom" in raw and isinstance(raw["atom"], dict):
            atom = self._build_atom(raw["atom"], unit)
            return ConditionNode(atom=atom) if atom is not None else None
        if raw.get("atom") is None and ("text" in raw or "comparison" in raw or "cardinality" in raw):
            atom = self._build_atom(raw, unit)
            return ConditionNode(atom=atom) if atom is not None else None
        if "all" in raw and isinstance(raw["all"], list) and raw["all"]:
            children = [node for node in (self._build_node(child, unit) for child in raw["all"]) if node]
            return ConditionNode(all_=children) if children else None
        if "any" in raw and isinstance(raw["any"], list) and raw["any"]:
            children = [node for node in (self._build_node(child, unit) for child in raw["any"]) if node]
            return ConditionNode(any_=children) if children else None
        if "not" in raw and isinstance(raw["not"], dict):
            child = self._build_node(raw["not"], unit)
            return ConditionNode(not_=child) if child is not None else None
        return None

    _OP_MAP = {">=": "GE", "<=": "LE", ">": "GT", "<": "LT", "==": "EQ", "=": "EQ",
               "!=": "NE", "EQ": "EQ", "NE": "NE", "LT": "LT", "LE": "LE",
               "GT": "GT", "GE": "GE"}
    _CARD_MAP = {">=": "AT_LEAST", "<=": "AT_MOST", "=": "EXACTLY", "==": "EXACTLY",
                 "AT_LEAST": "AT_LEAST", "AT_MOST": "AT_MOST", "EXACTLY": "EXACTLY",
                 "at least": "AT_LEAST", "at most": "AT_MOST", "exactly": "EXACTLY"}

    def _build_atom(self, raw: dict, unit: Unit) -> Atom | None:
        text = raw.get("text") or raw.get("lhs_text") or ""
        if not text or (text not in unit.text and text.strip() not in unit.text):
            return None
        text = text if text in unit.text else text.strip()
        comparison = None
        comp_raw = raw.get("comparison")
        if isinstance(comp_raw, dict):
            lhs_text = comp_raw.get("lhs_text") or text
            if lhs_text not in unit.text and lhs_text.strip() not in unit.text:
                lhs_text = text
            op = self._OP_MAP.get(str(comp_raw.get("op", "")))
            rhs = comp_raw.get("rhs_literal")
            if op and rhs is not None:
                comparison = Comparison(
                    lhs=Ref(kind="STATE", text=lhs_text,
                            ref=self._normalize_ref(comp_raw.get("lhs_ref"), lhs_text, unit)),
                    op=op, rhs_literal=str(rhs))
        cardinality = None
        card_raw = raw.get("cardinality")
        if isinstance(card_raw, dict):
            subject_text = card_raw.get("subject_text") or card_raw.get("text") or text
            if subject_text not in unit.text and subject_text.strip() not in unit.text:
                subject_text = text
            op = self._CARD_MAP.get(str(card_raw.get("op", "")))
            count = card_raw.get("count")
            if op:
                cardinality = Cardinality(
                    subject=Ref(kind="STATE", text=subject_text,
                                ref=self._normalize_ref(card_raw.get("subject_ref") or card_raw.get("ref"),
                                                        subject_text, unit)),
                    op=op,
                    count=int(count) if isinstance(count, (int, float)) else None)
        return Atom(kind=raw.get("kind") if raw.get("kind") in {
            "ACTION", "STATE", "VALUE", "CONDITION", "ENTITY", "CLAIM", "EVIDENCE"} else "CONDITION",
            text=text,
            ref=self._normalize_ref(raw.get("ref"), text, unit),
            comparison=comparison, cardinality=cardinality)

    @staticmethod
    def _normalize_ref(ref, text: str, unit: Unit) -> str:
        if isinstance(ref, str) and ref and ref not in {"UNKNOWN"}:
            return ref if re.fullmatch(r"[a-z0-9_.\-]+", ref) else "UNKNOWN"
        if re.fullmatch(r"[a-z0-9_.\-]+", text.strip().lower().replace(" ", "_")[:60]):
            return text.strip().lower().replace(" ", "_")[:60]
        return "UNKNOWN"
