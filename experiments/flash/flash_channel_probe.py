#!/usr/bin/env python3
"""flash: quick channel availability probe (blockrun / llm7 / pollinations)."""
import json

from openai import OpenAI

PROMPT = "Reply with ONLY this JSON: {\"verdict\": \"OK\"}"


def probe(name, base_url, api_key, model, max_tokens=40):
    try:
        c = OpenAI(base_url=base_url, api_key=api_key, timeout=90)
        r = c.chat.completions.create(model=model, messages=[{"role": "user", "content": PROMPT}],
                                      max_tokens=max_tokens, temperature=0)
        print(f"{name}: OK served={getattr(r, 'model', '?')} reply={repr((r.choices[0].message.content or '')[:80])}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"{name}: FAIL {type(e).__name__} {str(e)[:140]}")
        return False


if __name__ == "__main__":
    res = {}
    res["blockrun"] = probe("blockrun", "https://blockrun.ai/api/v1", "not-needed", "nvidia/gpt-oss-120b")
    res["llm7_fast"] = probe("llm7_fast", "https://api.llm7.io/v1", "unused", "fast")
    res["llm7_default"] = probe("llm7_default", "https://api.llm7.io/v1", "unused", "default")
    res["pollinations"] = probe("pollinations", "https://text.pollinations.ai/openai", "not-needed", "openai-fast")
    print(json.dumps(res))
