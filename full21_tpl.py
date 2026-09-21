#!/usr/bin/env python3
"""FULL_21: extract supported criteria_ids from granite guardian chat template."""
import json
import re

M = "/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda"

# find chat template
tpl = None
try:
    cfg = json.load(open(f"{M}/tokenizer_config.json"))
    tpl = cfg.get("chat_template")
except Exception:
    pass
if tpl is None:
    try:
        tpl = open(f"{M}/chat_template.jinja").read()
    except Exception:
        pass

print("template found:", tpl is not None, "len:", len(tpl) if tpl else 0)

if tpl:
    # find criteria mentions
    ids = sorted(set(re.findall(r'"([a-z_]+)"\s*[:,]', tpl)))
    print("quoted ids in template:", ids[:80])
    # guardian config keys
    keys = sorted(set(re.findall(r"guardian_config\.([a-z_]+)", tpl)))
    print("guardian_config keys:", keys)
    # look for criteria catalog dict
    m = re.findall(r"criteria_id[^}]{0,400}", tpl)
    for x in m[:8]:
        print("CTX:", x[:200].replace("\n", " "))
