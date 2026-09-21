#!/usr/bin/env python3
import json

M = "/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda"
tpl = open(f"{M}/chat_template.jinja").read()
print(tpl)
