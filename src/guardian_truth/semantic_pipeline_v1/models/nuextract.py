"""Local NuExtract3 adapter producing the same RuleIR candidates as Mistral."""

from __future__ import annotations

import json

from ..cache import ContentAddressedCache, content_key
from ..rule_ir import RULE_IR_SCHEMA
from .common import EXTRACTION_INSTRUCTIONS, extract_json_object, normalize_candidates


class NuExtractRuleExtractor:
    def __init__(self, *, model_name: str, model, tokenizer,
                 cache: ContentAddressedCache | None = None, max_new_tokens: int = 4096):
        self.model_name = model_name
        self.model = model
        self.tokenizer = tokenizer
        self.cache = cache
        self.max_new_tokens = max_new_tokens

    @staticmethod
    def load(model_name: str, device: str):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        kwargs = {"trust_remote_code": True, "device_map": device}
        model = AutoModelForCausalLM.from_pretrained(model_name, **kwargs)
        return model, tokenizer

    def extract(self, *, segment_id: str, source_text: str, context: tuple[str, ...] = ()):
        payload = {"segment_id": segment_id, "source": source_text, "context": list(context),
                   "schema": RULE_IR_SCHEMA, "instructions": EXTRACTION_INSTRUCTIONS}
        key = content_key(stage="nuextract", model=self.model_name,
                          config={"schema": "rule-ir-v1", "max_new_tokens": self.max_new_tokens},
                          payload=payload)
        cached = self.cache.get("nuextract", key) if self.cache else None
        if cached is None:
            messages = [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
            prompt = self.tokenizer.apply_chat_template(messages, tokenize=False,
                                                        add_generation_prompt=True)
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            output = self.model.generate(**inputs, do_sample=False,
                                         max_new_tokens=self.max_new_tokens)
            generated = output[0][inputs["input_ids"].shape[-1]:]
            cached = extract_json_object(self.tokenizer.decode(generated, skip_special_tokens=True))
            if self.cache:
                self.cache.put("nuextract", key, cached)
        return normalize_candidates(cached, extractor=f"nuextract:{self.model_name}",
                                    segment_id=segment_id, source_text=source_text)
