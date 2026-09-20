"""Mistral-only remote RuleIR extractor."""

from __future__ import annotations

import json
import os

from guardian_truth.llm_client import ChatClient, ClientConfig

from ..cache import ContentAddressedCache, content_key
from ..rule_ir import RULE_IR_SCHEMA
from .common import EXTRACTION_INSTRUCTIONS, extract_json_object, normalize_candidates


class MistralRuleExtractor:
    def __init__(self, *, model: str, api_key_env: str = "MISTRAL_API_KEY",
                 max_output_tokens: int = 4096, timeout_seconds: float = 120.0,
                 client=None, cache: ContentAddressedCache | None = None):
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.api_key_env = ("MISTRAL_API_KEY" if os.environ.get("MISTRAL_API_KEY")
                            else "mistral_api_key" if os.environ.get("mistral_api_key")
                            else api_key_env)
        self.cache = cache
        if client is None:
            config = ClientConfig(base_url="https://api.mistral.ai/v1", model=model,
                                  api_key_env=self.api_key_env, timeout_seconds=timeout_seconds,
                                  max_output_tokens=max_output_tokens, max_retries=1,
                                  strict_schema=False,
                                  response_format_mode="auto")
            client = ChatClient(config)
        self.client = client

    def extract(self, *, segment_id: str, source_text: str, context: tuple[str, ...] = ()):
        payload = {"segment_id": segment_id, "source": source_text, "context": list(context),
                   "schema_version": "rule-ir-v1"}
        key = content_key(stage="mistral", model=self.model,
                          config={"schema": "rule-ir-v1",
                                  "max_output_tokens": self.max_output_tokens,
                                  "timeout_seconds": self.timeout_seconds}, payload=payload)
        cached = self.cache.get("mistral", key) if self.cache else None
        if cached is None:
            messages = [
                {"role": "system", "content": EXTRACTION_INSTRUCTIONS},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
            completion = self.client.complete(messages, schema=RULE_IR_SCHEMA)
            cached = extract_json_object(completion.content)
            if self.cache:
                self.cache.put("mistral", key, cached)
        return normalize_candidates(cached, extractor=f"mistral:{self.model}",
                                    segment_id=segment_id, source_text=source_text)
