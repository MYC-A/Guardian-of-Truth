#!/usr/bin/env python3
"""Probe: how does the loaded tokenizer treat [INST], <s>, </s>?"""
from transformers import AutoTokenizer

M = "/mnt/data/guardian/agent-workspace/superz_models/mistral-7b-instruct-v0.3"
tok = AutoTokenizer.from_pretrained(M, local_files_only=True)
print("class:", type(tok).__name__)
print("vocab size:", tok.vocab_size, "len:", len(tok))
for s in ("<s>", "</s>", "[INST]", "[/INST]"):
    ids = tok.encode(s, add_special_tokens=False)
    print(f"{s!r} -> {ids}")
ids = tok.encode("[INST] Say OK [/INST]", add_special_tokens=False)
print("full ->", ids)
print("bos:", tok.bos_token, tok.bos_token_id, "eos:", tok.eos_token, tok.eos_token_id)
# what does chat template produce + tokenize
chat = tok.apply_chat_template([{"role": "user", "content": "Say OK"}], tokenize=False, add_generation_prompt=True)
print("chat:", repr(chat))
ids2 = tok.encode(chat, add_special_tokens=False)
print("chat ids:", ids2[:20])
