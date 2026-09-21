
import os, glob, json, sys
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
snap = glob.glob("/mnt/data/guardian/hf_cache/hub/models--numind--NuExtract3-W4A16/snapshots/*/")[0]
tok = AutoTokenizer.from_pretrained(snap, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(snap, local_files_only=True,
                                             torch_dtype=torch.bfloat16, device_map="cuda")
model.eval()
policy = ("Refunds over 10000 rubles require supervisor confirmation, except when the order "
          "already has a valid confirmation. Agents must not promise instant refunds.")
template = json.dumps({"rules": [{"forbidden_action_text": None, "required_action_text": None,
                                  "allowed_action_text": None, "condition_text": None,
                                  "exception_text": None}]}, indent=2)
prompt = tok.apply_chat_template(
    [{"role": "user", "content": [{"type": "text", "text": policy}]}],
    mode="structured", template=template,
    instructions="Extract policy rules as verbatim spans.",
    tokenize=False, add_generation_prompt=True)
inputs = tok(prompt, return_tensors="pt").to("cuda")
with torch.no_grad():
    gen = model.generate(**inputs, max_new_tokens=400, do_sample=False,
                         pad_token_id=tok.eos_token_id)
new = gen[0][inputs["input_ids"].shape[1]:]
out = tok.decode(new, skip_special_tokens=False)
print("N_GEN:", new.shape)
print("RAW_OUT:", repr(out[:700]))
