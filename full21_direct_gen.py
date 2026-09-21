#!/usr/bin/env python3
"""Direct transformers generation test for mistral-7b weights."""
import os

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

M = "/mnt/data/guardian/agent-workspace/superz_models/mistral-7b-instruct-v0.3"
tok = AutoTokenizer.from_pretrained(M, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(M, local_files_only=True, torch_dtype=torch.bfloat16, device_map="auto")

chat = tok.apply_chat_template([{"role": "user", "content": "Reply with exactly: LOCAL_MISTRAL_OK"}],
                               tokenize=False, add_generation_prompt=True)
print("chat:", repr(chat))
ids = tok.encode(chat, add_special_tokens=False, return_tensors="pt").to(model.device)
print("ids:", ids.tolist()[0][:12])
with torch.inference_mode():
    out = model.generate(ids, do_sample=False, max_new_tokens=15, pad_token_id=tok.eos_token_id)
text = tok.decode(out[0][ids.shape[-1]:], skip_special_tokens=False)
print("gen:", repr(text))
