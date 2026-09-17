"""semantic_pipeline_v1 — Phase 6B: NuExtract local extractor.

NuExtract-1.5-tiny (494M, Qwen2.5-0.5B base, official NuMind model, run
locally on CPU) is a PURE VERBATIM EXTRACTOR by design: it fills a JSON
template with spans copied from the source.  We therefore ask it ONLY for
verbatim text spans and convert those spans to RuleIR with a DETERMINISTIC,
auditable mapper (cue-lexicon based).  No reasoning is delegated to the model.

NuExtract3 (the current 4B model) cannot run on this hardware — see
outputs/vnext/semantic_pipeline_v1/hardware.json for the exact reasons;
NuExtract-1.5-tiny is the smallest technically sound local variant of the
same model family, not an unrelated substitute.
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

MODEL_NAME = "numind/NuExtract-1.5-tiny"

TEMPLATE = json.dumps({
    "forbidden_action_text": None,
    "required_action_text": None,
    "allowed_action_text": None,
    "condition_text": None,
    "exception_text": None,
    "temporal_anchor_text": None,
    "numeric_threshold_text": None,
    "cardinality_text": None,
}, indent=4)

# One documented few-shot pair (NuExtract protocol) to pin span granularity.
_EXAMPLE_TEXT = ("Do not close an account unless the customer identity was verified with at "
                 "at least two factors.")
_EXAMPLE_TEXT = ("Do not close an account unless the customer identity was verified with at least "
                 "two factors.")
_EXAMPLE_FILLED = json.dumps({
    "forbidden_action_text": "close an account",
    "required_action_text": None,
    "allowed_action_text": None,
    "condition_text": None,
    "exception_text": "the customer identity was verified with at least two factors",
    "temporal_anchor_text": None,
    "numeric_threshold_text": "at least two factors",
    "cardinality_text": "at least two factors",
}, indent=4)

_THRESHOLD_RE = re.compile(
    r"(?:(less|more|greater|fewer) than|at least|at most|no more than|no less than|"
    r"minimum of|maximum of|exactly|under|over|above|below|не менее|не более|"
    r"минимум|максимум)\s+(\d+(?:\.\d+)?%?)", re.IGNORECASE)
_CARD_RE = re.compile(
    r"(at least|at most|no more than|no fewer than|exactly|минимум|максимум|не менее|не более)\s+"
    r"(\d+)\s+(factors?|documents?|methods?|items?|items|steps?|verifications?|sources?|approvals?)",
    re.IGNORECASE)


class NuExtractExtractor:
    """Loads the 0.5B model lazily; ~1 GB RAM while resident."""

    def __init__(self, *, model_name: str = MODEL_NAME, max_new_tokens: int = 160):
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self._model = None
        self._tokenizer = None

    def _load(self):
        if self._model is None:
            import os
            import torch
            torch.set_num_threads(2)
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
            # dtype is configurable: fp32 (faster CPU matmul, ~2 GB resident)
            # vs bfloat16 (~1 GB, emulated and much slower on this CPU)
            dtype = torch.float32 if os.environ.get("NUEXTRACT_DTYPE", "fp32") == "fp32" \
                else torch.bfloat16
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_name, dtype=dtype, trust_remote_code=True).eval()

    def fill_template(self, text: str) -> dict | None:
        """One generation (NuExtract single-input protocol, temperature 0).
        Returns the parsed JSON template or None.  NOTE: the documented
        few-shot concatenation confused the 0.5B model into re-emitting the
        input block instead of filling it, so the single-input protocol is
        used and slot-level quality is handled by deterministic gates."""
        self._load()
        import torch
        prompt = (f"<|input|>\n### Template:\n{TEMPLATE}\n### Text:\n{text}\n\n<|output|>")
        encodings = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4000)
        with torch.no_grad():
            out = self._model.generate(**encodings, max_new_tokens=self.max_new_tokens,
                                       do_sample=False, pad_token_id=self._tokenizer.eos_token_id)
        decoded = self._tokenizer.batch_decode(out, skip_special_tokens=True)[0]
        if "<|output|>" not in decoded:
            return None
        payload = decoded.split("<|output|>", 1)[1]
        try:
            value = json.loads(payload[payload.find("{"): payload.rfind("}") + 1])
            return value if isinstance(value, dict) else None
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------- deterministic map

    _MODALITY_CUES = {
        "FORBID": ("must not", "may not", "cannot", "do not", "don't", "not allowed",
                   "forbidden", "prohibited", "never", "нельзя", "запрещ"),
        "REQUIRE": ("must", "required", "shall", "need to", "has to", "обязан", "должен",
                    "необходимо", "требуется"),
        "ALLOW": ("may", "allowed", "can", "permitted", "разрешен", "можно"),
    }

    def _cue_supported(self, modality: str, unit: Unit, target_text: str) -> bool:
        """Deterministic modality gate: the modality cue must appear inside the
        target span or in the 40 characters of source preceding it (the tiny
        model sometimes copies whole sentences into the wrong slot)."""
        cues = self._MODALITY_CUES[modality]
        position = unit.text.find(target_text)
        if position < 0:
            return False
        window = unit.text[max(0, position - 40): position + len(target_text) + 8].lower()
        return any(cue in window for cue in cues)

    def extract(self, unit: Unit, tool_names: list[str]) -> tuple[list[RuleIR], list[dict]]:
        failures: list[dict] = []
        filled = self.fill_template(unit.text)
        if filled is None:
            failures.append({"unit": unit.unit_id, "kind": "TRANSPORT", "detail": "nuextract invalid output"})
            return [], failures
        rules: list[RuleIR] = []
        whole = unit.text.strip().rstrip(".")
        for modality, field in (("FORBID", "forbidden_action_text"),
                                ("REQUIRE", "required_action_text"),
                                ("ALLOW", "allowed_action_text")):
            target_text = filled.get(field)
            if not isinstance(target_text, str) or not target_text.strip():
                continue
            target_text = target_text.strip().rstrip(".")
            if target_text not in unit.text:
                failures.append({"unit": unit.unit_id, "kind": "UNGROUNDED",
                                 "detail": f"{field}:{target_text[:80]}"})
                continue
            if target_text.lower() == whole.lower() or len(target_text) > max(24, int(len(unit.text) * 0.7)):
                # whole-sentence copy: the tiny model failed slot granularity
                failures.append({"unit": unit.unit_id, "kind": "COARSE_SPAN",
                                 "detail": f"{field}:{target_text[:80]}"})
                continue
            if not self._cue_supported(modality, unit, target_text):
                failures.append({"unit": unit.unit_id, "kind": "MODALITY_UNSUPPORTED",
                                 "detail": f"{field}:{target_text[:80]}"})
                continue
            rule = self._build_rule(modality, target_text, filled, unit, tool_names, len(rules))
            rules.append(rule)
            mirror = self._unless_mirror(rule, unit)
            if mirror is not None:
                rules.append(mirror)
        # span-evidence harvesting: the tiny model reliably copies condition /
        # exception / threshold / temporal spans even when it fails the action
        # slots; these enter Phi as UNKNOWN-modality partial rules (semantic
        # atoms, never verdicts)
        if not rules:
            partial = self._partial_rule(filled, unit, tool_names)
            if partial is not None:
                rules.append(partial)
        return rules, failures

    def _partial_rule(self, filled: dict, unit: Unit, tool_names: list[str]) -> RuleIR | None:
        whole = unit.text.strip().rstrip(".")
        spans = []
        for field, kind in (("condition_text", "CONDITION"), ("exception_text", "CONDITION"),
                            ("numeric_threshold_text", "VALUE"), ("temporal_anchor_text", "ACTION"),
                            ("cardinality_text", "CONDITION")):
            value = _clean_span(filled.get(field))
            if value and value in unit.text and value.lower() != whole.lower() \
                    and len(value) < max(24, int(len(unit.text) * 0.8)):
                spans.append((kind, value))
        if not spans:
            return None
        node = ConditionNode(all_=[ConditionNode(atom=self._atom_for(value, unit, tool_names))
                                   for kind, value in spans[:4]])
        span = SourceSpan(document=unit.document, start=unit.span[0], end=unit.span[1],
                          quote=unit.text[:400])
        return RuleIR(
            rule_id=f"{unit.unit_id}:nuextract:partial",
            modality="UNKNOWN",
            target=Ref(kind="UNKNOWN", text=spans[0][1], ref=self._ref_for(spans[0][1], tool_names)),
            conditions=node,
            provenance=Provenance(extractor="nuextract",
                                  fragment_id=unit.fragment_ids[0] if unit.fragment_ids else None,
                                  segment_id=unit.segment_id,
                                  raw_output=json.dumps(filled, ensure_ascii=False)[:500]),
            unresolved=["nuextract-tiny action slot too coarse; span evidence only"],
            source_spans=[span], temporal=Temporal(), actor="UNKNOWN")

    _EXCEPTION_CUES = ("unless", "except", "за исключением", "кроме случая")

    def _unless_mirror(self, rule: RuleIR, unit: Unit) -> RuleIR | None:
        lowered = unit.text.lower()
        if not any(cue in lowered for cue in self._EXCEPTION_CUES):
            return None
        if rule.conditions is None or rule.exceptions:
            return None
        return rule.model_copy(update={
            "rule_id": rule.rule_id + ":unless_mirror",
            "exceptions": [rule.conditions], "conditions": None,
            "unresolved": list(rule.unresolved) + ["unless-cue present; mirror keeps the "
                                                   "exceptions-variant as a second interpretation"]})

    def _build_rule(self, modality: str, target_text: str, filled: dict, unit: Unit,
                    tool_names: list[str], index: int) -> RuleIR:
        target = Ref(kind="ACTION", text=target_text,
                     ref=self._ref_for(target_text, tool_names))
        conditions = None
        condition_text = _clean_span(filled.get("condition_text"))
        if condition_text and condition_text in unit.text:
            atom = self._atom_for(condition_text, unit, tool_names)
            conditions = ConditionNode(atom=atom)
        exceptions = []
        exception_text = _clean_span(filled.get("exception_text"))
        if exception_text and exception_text in unit.text:
            exceptions.append(ConditionNode(atom=self._atom_for(exception_text, unit, tool_names)))
        temporal = Temporal(relation="NONE")
        anchor_text = _clean_span(filled.get("temporal_anchor_text"))
        if anchor_text and anchor_text in unit.text:
            relation = _temporal_relation(unit.text, target_text, anchor_text)
            temporal = Temporal(relation=relation,
                                anchor=Ref(kind="ACTION", text=anchor_text,
                                           ref=self._ref_for(anchor_text, tool_names)))
        span = SourceSpan(document=unit.document, start=unit.span[0], end=unit.span[1],
                          quote=unit.text[:400])
        return RuleIR(
            rule_id=f"{unit.unit_id}:nuextract:{index}",
            modality=modality, target=target, conditions=conditions, exceptions=exceptions,
            temporal=temporal, actor="assistant", source_spans=[span],
            provenance=Provenance(extractor="nuextract",
                                  fragment_id=unit.fragment_ids[0] if unit.fragment_ids else None,
                                  segment_id=unit.segment_id,
                                  raw_output=json.dumps(filled, ensure_ascii=False)[:500]))

    def _atom_for(self, text: str, unit: Unit, tool_names: list[str]) -> Atom:
        comparison = None
        match = _THRESHOLD_RE.search(text)
        if match:
            number = match.group(2).rstrip("%")
            op = self._op_for(match.group(1), match.group(0))
            comparison = Comparison(lhs=Ref(kind="STATE", text=text,
                                            ref=self._ref_for(text, tool_names)),
                                    op=op, rhs_literal=number)
        cardinality = None
        card = _CARD_RE.search(unit.text)
        if card and card.group(0) in (text or "") + unit.text and card.group(2).isdigit():
            cardinality = Cardinality(
                subject=Ref(kind="STATE", text=card.group(3), ref=self._ref_for(card.group(3), tool_names)),
                op={"at least": "AT_LEAST", "no fewer than": "AT_LEAST", "минимум": "AT_LEAST",
                    "не менее": "AT_LEAST", "at most": "AT_MOST", "no more than": "AT_MOST",
                    "максимум": "AT_MOST", "не более": "AT_MOST", "exactly": "EXACTLY"}.get(
                    card.group(1).lower(), "AT_LEAST"),
                count=int(card.group(2)))
        return Atom(kind="CONDITION", text=text, ref=self._ref_for(text, tool_names),
                    comparison=comparison, cardinality=cardinality)

    @staticmethod
    def _op_for(direction: str | None, full: str) -> str:
        lowered = full.lower()
        if direction and direction.lower() in {"less", "fewer"} or "under" in lowered or "below" in lowered:
            return "LT"
        if direction and direction.lower() in {"more", "greater"} or "over" in lowered or "above" in lowered:
            return "GT"
        if "at least" in lowered or "no less than" in lowered or "minimum" in lowered:
            return "GE"
        if "at most" in lowered or "no more than" in lowered or "maximum" in lowered:
            return "LE"
        return "LT"

    @staticmethod
    def _ref_for(text: str, tool_names: list[str]) -> str:
        for tool in sorted(tool_names, key=len, reverse=True):
            if tool and re.search(r"(?<![\w.-])" + re.escape(tool) + r"(?![\w.-])", text):
                return tool
        key = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48]
        return key or "UNKNOWN"


def _clean_span(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().rstrip(".")
    return None


def _temporal_relation(unit_text: str, target_text: str, anchor_text: str) -> str:
    """Deterministic relation from source ordering: BEFORE when the target is
    mentioned before the anchor with a 'before' cue, AFTER with an 'after'
    cue; UNKNOWN otherwise (never guessed)."""
    t_pos, a_pos = unit_text.lower().find(target_text.lower()), unit_text.lower().find(anchor_text.lower())
    lowered = unit_text.lower()
    before_cue = "before" in lowered or "prior to" in lowered
    after_cue = "after" in lowered or "once" in lowered
    if before_cue and t_pos >= 0 and a_pos >= 0:
        # "verify X before Y": target mentioned first
        return "BEFORE" if t_pos < a_pos else "AFTER"
    if after_cue and t_pos >= 0 and a_pos >= 0:
        return "AFTER" if t_pos < a_pos else "BEFORE"
    return "UNKNOWN"
