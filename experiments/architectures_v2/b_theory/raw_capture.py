"""Raw response capture wrappers for Architecture B donor adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class CapturedExtraction:
    candidates: tuple
    raw_response: dict


class RawMistralExtractor:
    """Mistral donor compatible extractor which retains pre-normalization output."""

    def __init__(self, *, model: str, api_key_env: str):
        from guardian_truth.semantic_pipeline_v1.models.mistral import MistralRuleExtractor
        self.donor = MistralRuleExtractor(model=model, api_key_env=api_key_env)
        self.client = self.donor.client
        self.model = model

    def extract_with_raw(self, *, segment_id: str, source_text: str, context=()):
        from guardian_truth.semantic_pipeline_v1.models.common import (
            EXTRACTION_INSTRUCTIONS, extract_json_object, normalize_candidates)
        from guardian_truth.semantic_pipeline_v1.rule_ir import RULE_IR_SCHEMA
        payload = {"segment_id": segment_id, "source": source_text,
                   "context": list(context), "schema_version": "rule-ir-v1"}
        messages = [{"role": "system", "content": EXTRACTION_INSTRUCTIONS},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        completion = self.client.complete(messages, schema=RULE_IR_SCHEMA)
        content = completion.content
        parsed = extract_json_object(content)
        candidates = normalize_candidates(parsed, extractor=f"mistral:{self.model}",
                                          segment_id=segment_id, source_text=source_text)
        return CapturedExtraction(tuple(candidates), {
            "kind": "MISTRAL_COMPLETION_PRE_NORMALIZATION",
            "completion_content": content, "parsed_object": parsed,
        })


class RawNuExtractExtractor:
    """NuExtract donor compatible extractor which retains decoded/template output."""

    def __init__(self, *, model_name: str, model, processor, max_new_tokens: int = 4096):
        self.model_name, self.model, self.processor = model_name, model, processor
        self.max_new_tokens = max_new_tokens

    def extract_with_raw(self, *, segment_id: str, source_text: str, context=()):
        import torch
        from guardian_truth.semantic_pipeline_v1.models.common import extract_json_object
        from guardian_truth.semantic_pipeline_v1.models.nuextract import (
            NUEXTRACT_RULE_TEMPLATE, normalize_nuextract)
        messages = [{"role": "user", "content": [{"type": "text", "text": source_text}]}]
        inputs = self.processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True, return_dict=True,
            return_tensors="pt", template=json.dumps(NUEXTRACT_RULE_TEMPLATE, indent=4),
            enable_thinking=False).to(self.model.device)
        with torch.inference_mode():
            output = self.model.generate(**inputs, do_sample=False,
                                         max_new_tokens=self.max_new_tokens)
        generated = output[:, inputs["input_ids"].shape[1]:]
        decoded = self.processor.batch_decode(
            generated, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0].strip()
        parsed = extract_json_object(decoded)
        candidates = normalize_nuextract(
            parsed, extractor=f"nuextract:{self.model_name}",
            segment_id=segment_id, source_text=source_text)
        return CapturedExtraction(tuple(candidates), {
            "kind": "NUEXTRACT_DECODED_PRE_NORMALIZATION",
            "decoded_text": decoded, "parsed_template": parsed,
        })
