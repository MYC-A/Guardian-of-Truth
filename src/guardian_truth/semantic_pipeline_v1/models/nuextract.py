"""NuExtract3 structured extraction with deterministic RuleIR normalization."""

from __future__ import annotations

import hashlib
import json

from ..cache import ContentAddressedCache, content_key
from ..rule_ir import MODALITIES, RELATIONS, TARGET_KINDS, TEMPORAL, rule_digest
from ..types import RuleCandidate, RuleExpression, RuleIR, RuleTerm, SourceSpan
from .common import extract_json_object


# NuExtract templates are not JSON Schema. Leaves are NuExtract type markers,
# and the complete template must be passed to the chat template as a JSON string.
NUEXTRACT_RULE_TEMPLATE = {
    "rules": [{
        "modality": ["REQUIRE", "FORBID", "ALLOW", "UNKNOWN"],
        "subject": "verbatim-string",
        "target_kind": ["ACTION", "STATE", "CLAIM", "INFORMATION", "EFFECT"],
        "target_name": "verbatim-string",
        "relation": ["IF", "ONLY_IF", "UNLESS", "NONE"],
        "temporal": ["BEFORE", "AFTER", "UNTIL", "WHILE", "NONE"],
        "condition_text": "verbatim-string",
        "exception_text": "verbatim-string",
        "values": ["verbatim-string"],
        "entity_references": ["verbatim-string"],
        "source_quote": "verbatim-string",
    }],
    "actions": [{
        "action": "verbatim-string",
        "object": "verbatim-string",
        "subject": "verbatim-string",
        "modality": ["REQUIRE", "FORBID", "ALLOW", "UNKNOWN"],
        "condition": "verbatim-string",
        "exception": "verbatim-string",
        "source_quote": "verbatim-string",
    }],
    "temporal_relations": [{
        "first": "verbatim-string",
        "relation": ["before", "after", "until", "while"],
        "second": "verbatim-string",
        "source_quote": "verbatim-string",
    }],
}


def _text(value) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _atom(value: str | None) -> RuleExpression | None:
    return RuleExpression("ATOM", term=RuleTerm("STATE", name=value)) if value else None


def _strings(value) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, list) else [value]
    return tuple(text for item in values if (text := _text(item)) is not None)


def _ground_quote(source_text: str, segment_id: str, quote) -> tuple[tuple[SourceSpan, ...], tuple[str, ...]]:
    quote = _text(quote)
    if quote is None:
        return (), ("missing-exact-source-quote",)
    starts, offset = [], 0
    while True:
        found = source_text.find(quote, offset)
        if found < 0:
            break
        starts.append(found)
        offset = found + 1
    if not starts:
        return (), ("source-quote-not-found",)
    if len(starts) > 1:
        return (), (f"ambiguous-source-quote:{len(starts)}",)
    start = starts[0]
    return (SourceSpan(segment_id, start, start + len(quote), quote),), ()


def _candidate(*, rule: RuleIR, quote, index: int, kind: str,
               extractor: str, segment_id: str, source_text: str) -> RuleCandidate:
    spans, quote_issues = _ground_quote(source_text, segment_id, quote)
    unresolved = tuple(dict.fromkeys((*rule.unresolved_references, *quote_issues)))
    digest = rule_digest(rule)
    candidate_id = hashlib.sha256(
        f"{extractor}\0{segment_id}\0{kind}\0{index}\0{digest}".encode("utf-8")
    ).hexdigest()[:20]
    return RuleCandidate(candidate_id, rule, spans, (segment_id,), (extractor,),
                         unresolved_components=unresolved, canonical_digest=digest)


def normalize_nuextract(value: dict, *, extractor: str, segment_id: str,
                        source_text: str) -> tuple[RuleCandidate, ...]:
    """Map NuExtract's extraction template into RuleIR without semantic guessing."""
    candidates: list[RuleCandidate] = []
    for index, item in enumerate(value.get("rules") or ()):
        if not isinstance(item, dict):
            continue
        unresolved = []
        modality = str(item.get("modality") or "UNKNOWN").upper()
        if modality not in MODALITIES:
            modality = "UNKNOWN"
            unresolved.append("invalid-modality")
        target_kind = str(item.get("target_kind") or "INFORMATION").upper()
        if target_kind not in TARGET_KINDS:
            target_kind = "INFORMATION"
            unresolved.append("invalid-target-kind")
        relation = str(item.get("relation") or "NONE").upper()
        if relation not in RELATIONS:
            relation = "NONE"
            unresolved.append("invalid-relation")
        temporal = str(item.get("temporal") or "NONE").upper()
        if temporal not in TEMPORAL:
            temporal = "NONE"
            unresolved.append("invalid-temporal")
        target_name = _text(item.get("target_name"))
        if target_name is None:
            unresolved.append("missing-target-name")
        rule = RuleIR(
            modality, _text(item.get("subject")), RuleTerm(target_kind, name=target_name),
            relation=relation, condition=_atom(_text(item.get("condition_text"))),
            exception=_atom(_text(item.get("exception_text"))), temporal=temporal,
            values=_strings(item.get("values")),
            entity_references=_strings(item.get("entity_references")),
            unresolved_references=tuple(unresolved),
        )
        candidates.append(_candidate(rule=rule, quote=item.get("source_quote"),
                                     index=index, kind="rule", extractor=extractor,
                                     segment_id=segment_id, source_text=source_text))

    for index, item in enumerate(value.get("actions") or ()):
        if not isinstance(item, dict) or not _text(item.get("action")):
            continue
        modality = str(item.get("modality") or "UNKNOWN").upper()
        unresolved = []
        if modality not in MODALITIES:
            modality = "UNKNOWN"
            unresolved.append("invalid-modality")
        if modality == "UNKNOWN":
            unresolved.append("action-modality-not-extracted")
        obj = _text(item.get("object"))
        if obj:
            # NuExtract's generic `object` slot does not tell us whether this
            # is an entity identifier, an argument, or merely the grammatical
            # object. Preserve it explicitly but do not turn it into an
            # equality or an entity binding without evidence.
            unresolved.append(f"unbound-action-object:{obj}")
        rule = RuleIR(
            modality, _text(item.get("subject")),
            RuleTerm("ACTION", name=_text(item.get("action"))),
            condition=_atom(_text(item.get("condition"))),
            exception=_atom(_text(item.get("exception"))),
            unresolved_references=tuple(unresolved),
        )
        candidates.append(_candidate(rule=rule, quote=item.get("source_quote"),
                                     index=index, kind="action", extractor=extractor,
                                     segment_id=segment_id, source_text=source_text))

    for index, item in enumerate(value.get("temporal_relations") or ()):
        if not isinstance(item, dict):
            continue
        first, second = _text(item.get("first")), _text(item.get("second"))
        temporal = str(item.get("relation") or "NONE").upper()
        unresolved = ["temporal-target-requires-binding"]
        if temporal not in TEMPORAL - {"NONE"}:
            temporal = "NONE"
            unresolved.append("invalid-temporal")
        if not first or not second:
            unresolved.append("incomplete-temporal-relation")
        rule = RuleIR(
            "UNKNOWN", None, RuleTerm("STATE", name=first),
            condition=_atom(second), temporal=temporal,
            unresolved_references=tuple(unresolved),
        )
        candidates.append(_candidate(rule=rule, quote=item.get("source_quote"),
                                     index=index, kind="temporal", extractor=extractor,
                                     segment_id=segment_id, source_text=source_text))

    # Multiple template branches may expose the same fact. Preserve one
    # deterministic candidate per meaning and grounding; never score-pick.
    unique = {}
    for candidate in candidates:
        key = (candidate.canonical_digest, candidate.source_spans,
               candidate.unresolved_components)
        unique.setdefault(key, candidate)
    return tuple(unique.values())


class NuExtractRuleExtractor:
    def __init__(self, *, model_name: str, model, processor,
                 cache: ContentAddressedCache | None = None, max_new_tokens: int = 4096):
        self.model_name = model_name
        self.model = model
        self.processor = processor
        self.cache = cache
        self.max_new_tokens = max_new_tokens

    @staticmethod
    def load(model_name: str, device: str):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
        kwargs = {"trust_remote_code": True, "device_map": device}
        if device.startswith("cuda"):
            kwargs["dtype"] = torch.bfloat16
        model = AutoModelForImageTextToText.from_pretrained(model_name, **kwargs).eval()
        return model, processor

    def extract(self, *, segment_id: str, source_text: str, context: tuple[str, ...] = ()):
        # Context is deliberately excluded from the model input so every
        # requested verbatim quote is groundable in this exact source fragment.
        payload = {"segment_id": segment_id, "source": source_text}
        key = content_key(stage="nuextract", model=self.model_name,
                          config={"template": NUEXTRACT_RULE_TEMPLATE,
                                  "max_new_tokens": self.max_new_tokens,
                                  "enable_thinking": False}, payload=payload)
        cached = self.cache.get("nuextract", key) if self.cache else None
        if cached is None:
            messages = [{"role": "user", "content": source_text}]
            inputs = self.processor.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=True, return_dict=True,
                return_tensors="pt", template=json.dumps(NUEXTRACT_RULE_TEMPLATE, indent=4),
                enable_thinking=False,
            ).to(self.model.device)
            import torch
            with torch.inference_mode():
                output = self.model.generate(**inputs, do_sample=False,
                                             max_new_tokens=self.max_new_tokens)
            generated = output[:, inputs["input_ids"].shape[1]:]
            text = self.processor.batch_decode(
                generated, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0].strip()
            cached = extract_json_object(text)
            if self.cache:
                self.cache.put("nuextract", key, cached)
        return normalize_nuextract(cached, extractor=f"nuextract:{self.model_name}",
                                   segment_id=segment_id, source_text=source_text)
