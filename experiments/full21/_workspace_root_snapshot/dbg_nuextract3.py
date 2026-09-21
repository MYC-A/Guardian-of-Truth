
import os, glob, json
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import torch
snap = glob.glob("/mnt/data/guardian/hf_cache/hub/models--numind--NuExtract3-W4A16/snapshots/*/")[0]
import json as j
tc = j.load(open(snap + "tokenizer_config.json"))
print("tokenizer_class:", tc.get("tokenizer_class"), "| chat_template file exists")
from transformers import PreTrainedTokenizerFast
tok = PreTrainedTokenizerFast(tokenizer_file=snap + "tokenizer.json",
                               unk_token=None, eos_token="<|im_end|>", pad_token="<|endoftext|>")
print("tok loaded, vocab:", tok.vocab_size)
# chat template из jinja-файла подключим вручную
chat_src = open(snap + "chat_template.jinja").read()
tok.chat_template = chat_src
policy = "Refunds over 10000 rubles require supervisor confirmation, except when the order already has a valid confirmation. Agents must not promise instant refunds."
template = j.dumps({"rules": [{"forbidden_action_text": None, "required_action_text": None,
                              "allowed_action_text": None, "condition_text": None,
                              "exception_text": None}]}, indent=2)
prompt = tok.apply_chat_template(
    [{"role": "user", "content": [{"type": "text", "text": policy}]}],
    mode="structured", template=template,
    instructions="Extract policy rules as verbatim spans.",
    tokenize=False, add_generation_prompt=True)
print("PROMPT TAIL:", repr(prompt[-160:]))
from transformers import AutoModelForCausalLM
model = AutoModelForCausalLM.from_pretrained(snap, local_files_only=True,
                                             torch_dtype=torch.bfloat16, device_map="cuda")
model.eval()
inputs = tok(prompt, return_tensors="pt").to("cuda")
with torch.no_grad():
    gen = model.generate(**inputs, max_new_tokens=400, do_sample=False,
                         pad_token_id=tok.pad_token_id)
new = gen[0][inputs["input_ids"].shape[1]:]
out = tok.decode(new, skip_special_tokens=False)
print("N_GEN:", new.shape)
print("RAW_OUT:", repr(out[:700]))
