
import os, glob, json, sys, traceback
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
snap = glob.glob("/mnt/data/guardian/hf_cache/hub/models--numind--NuExtract3-W4A16/snapshots/*/")[0]
tok = AutoTokenizer.from_pretrained(snap, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(snap, local_files_only=True,
                                             torch_dtype=torch.bfloat16, device_map="cuda")
model.eval()
policy = "Refunds over 10000 rubles require supervisor confirmation."
template = json.dumps({"rules": [{"forbidden_action_text": None}]}, indent=2)
prompt = tok.apply_chat_template(
    [{"role": "user", "content": [{"type": "text", "text": policy}]}],
    mode="structured", template=template, instructions="Extract.",
    tokenize=False, add_generation_prompt=True)
inputs = tok(prompt, return_tensors="pt").to("cuda")
try:
    with torch.no_grad():
        gen = model.generate(**inputs, max_new_tokens=100, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    print("n_gen:", gen.shape, flush=True)
except Exception:
    tb = traceback.format_exc()
    sys.stderr.write(tb)
    print("TB_LINES:", len(tb.splitlines()), flush=True)
    print("TB_HEAD:", tb.splitlines()[-3:], flush=True)
