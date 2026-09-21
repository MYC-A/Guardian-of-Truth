
import json
p = "/mnt/data/guardian/agent-workspace/superz_models/mistral-7b-instruct-v0.3/tokenizer_config.json"
d = json.load(open(p))
print("before:", d.get("tokenizer_class"))
d["tokenizer_class"] = "LlamaTokenizer"
json.dump(d, open(p, "w"), indent=2)
print("patched -> LlamaTokenizer")
